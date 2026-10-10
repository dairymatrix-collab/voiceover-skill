"""Strict, model-free JSONL IPC contract validation for the voiceover harness.

This module validates protocol messages only. It does not launch workers, sandbox
processes, validate actual audio bytes, or implement a TTS engine.
"""
from __future__ import annotations

import json
import math
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator

MAX_LINE_BYTES = 1024 * 1024
MAX_JSON_NESTING = 128
MAX_INTEGER_DIGITS = 1024
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
ENGINE_IDS = {"qwen3_tts", "chatterbox", "kokoro"}


class IPCContractError(ValueError):
    """Stable validation error with machine-readable code and optional detail."""

    def __init__(self, message: str):
        super().__init__(message)
        self.code, separator, detail = message.partition(":")
        self.detail = detail if separator else None


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IPCContractError("PROTOCOL_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise IPCContractError("PROTOCOL_NONFINITE_NUMBER")


def _parse_bounded_int(value: str) -> int:
    """Bound integer-token conversion work and memory before calling int()."""
    digits = value[1:] if value.startswith("-") else value
    if len(digits) > MAX_INTEGER_DIGITS:
        raise IPCContractError("PROTOCOL_INTEGER_TOO_LONG")
    return int(value)


def _check_json_nesting(payload: str) -> None:
    """Reject excessive structural nesting while ignoring brackets inside strings."""
    depth = 0
    in_string = False
    escaped = False
    for char in payload:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > MAX_JSON_NESTING:
                raise IPCContractError("PROTOCOL_NESTING_TOO_DEEP")
        elif char in "]}":
            depth -= 1
            # Structural mismatch remains the JSON decoder's responsibility.


def _parse_finite_float(value: str) -> float:
    """Parse a JSON number while rejecting exponent overflow to infinity."""
    parsed = float(value)
    if not math.isfinite(parsed):
        raise IPCContractError("PROTOCOL_NONFINITE_NUMBER")
    return parsed


def _reject_unpaired_surrogates(value: Any) -> None:
    """Reject escaped lone UTF-16 surrogates that are not Unicode scalar values."""
    if isinstance(value, str):
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise IPCContractError("PROTOCOL_INVALID_UNICODE")
    elif isinstance(value, list):
        for item in value:
            _reject_unpaired_surrogates(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            _reject_unpaired_surrogates(key)
            _reject_unpaired_surrogates(item)


def load_schema(name: str) -> dict[str, Any]:
    if name not in {"synthesis-request-v1.schema.json", "synthesis-result-v1.schema.json"}:
        raise IPCContractError("SCHEMA_NOT_ALLOWLISTED")
    try:
        schema = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise IPCContractError("SCHEMA_INVALID") from exc
    return schema


_REQUEST_SCHEMA = load_schema("synthesis-request-v1.schema.json")
_RESULT_SCHEMA = load_schema("synthesis-result-v1.schema.json")
_REQUEST_VALIDATOR = Draft202012Validator(_REQUEST_SCHEMA)
_RESULT_VALIDATOR = Draft202012Validator(_RESULT_SCHEMA)


def _first_schema_error(message: dict[str, Any], validator: Draft202012Validator) -> None:
    """Return a stable contract error even for malformed direct-Python objects.

    JSONL callers only provide JSON values, but the public validator is also
    callable directly. Cyclic containers and other non-JSON Python objects must
    not leak RecursionError/TypeError from the schema library to callers.
    """
    try:
        errors = sorted(
            validator.iter_errors(message),
            key=lambda e: (list(map(str, e.absolute_path)), e.message),
        )
    except (RecursionError, TypeError, ValueError) as exc:
        raise IPCContractError("PROTOCOL_SCHEMA_INVALID:$") from exc
    if errors:
        path = ".".join(str(part) for part in errors[0].absolute_path) or "$"
        raise IPCContractError(f"PROTOCOL_SCHEMA_INVALID:{path}")


def _check_line_framing(raw: bytes) -> str:
    if not isinstance(raw, bytes):
        raise IPCContractError("PROTOCOL_BYTES_REQUIRED")
    if len(raw) > MAX_LINE_BYTES:
        raise IPCContractError("PROTOCOL_LINE_TOO_LARGE")
    if not raw.endswith(b"\n"):
        raise IPCContractError("PROTOCOL_TRUNCATED_LINE")
    payload = raw[:-1]
    if payload.endswith(b"\r"):
        payload = payload[:-1]
    if not payload:
        raise IPCContractError("PROTOCOL_BLANK_LINE")
    if b"\n" in payload or b"\r" in payload:
        raise IPCContractError("PROTOCOL_MULTILINE_MESSAGE")
    try:
        return payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise IPCContractError("PROTOCOL_INVALID_UTF8") from exc


def parse_jsonl_message(raw: bytes) -> dict[str, Any]:
    """Parse one newline-terminated UTF-8 JSON object, rejecting duplicate keys."""
    payload = _check_line_framing(raw)
    _check_json_nesting(payload)
    try:
        message = json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
            parse_float=_parse_finite_float,
            parse_int=_parse_bounded_int,
        )
        _reject_unpaired_surrogates(message)
    except IPCContractError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise IPCContractError("PROTOCOL_INVALID_JSON") from exc
    if not isinstance(message, dict):
        raise IPCContractError("PROTOCOL_OBJECT_REQUIRED")
    return message



def _validate_relative_path_fields(message: dict[str, Any]) -> None:
    """Reject non-canonical protocol paths before JSON Schema validation.

    IPC paths are POSIX-style relative paths. Filesystem containment and symlink
    safety must still be enforced by the eventual supervisor at open time.
    """
    candidates: list[tuple[str, Any]] = []
    reference_audio = message.get("reference_audio")
    if isinstance(reference_audio, dict) and "relative_path" in reference_audio:
        candidates.append(("reference_audio.relative_path", reference_audio["relative_path"]))
    output = message.get("output")
    if isinstance(output, dict) and "relative_path" in output:
        candidates.append(("output.relative_path", output["relative_path"]))

    for field, value in candidates:
        if not isinstance(value, str):
            continue  # JSON Schema reports the field type.
        parts = value.split("/")
        if (not value or value.startswith("/") or "\\" in value
                or any(part in {"", ".", ".."} or part != part.strip() for part in parts)
                or str(PurePosixPath(value)) != value):
            raise IPCContractError(f"PROTOCOL_PATH_INVALID:{field}")


def validate_request(message: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(message, dict):
        raise IPCContractError("PROTOCOL_OBJECT_REQUIRED")
    _validate_relative_path_fields(message)
    _first_schema_error(message, _REQUEST_VALIDATOR)
    # Keep numeric edge checks explicit for direct Python callers as well as JSON input.
    speed = message["options"].get("speed")
    if isinstance(speed, bool) or (speed is not None and not math.isfinite(speed)):
        raise IPCContractError("PROTOCOL_SCHEMA_INVALID:options.speed")
    return message


def validate_result(message: dict[str, Any], *, expected_request_id: str | None = None,
                    expected_job_id: str | None = None) -> dict[str, Any]:
    if not isinstance(message, dict):
        raise IPCContractError("PROTOCOL_OBJECT_REQUIRED")
    _validate_relative_path_fields(message)
    _first_schema_error(message, _RESULT_VALIDATOR)
    if expected_request_id is not None and message["request_id"] != expected_request_id:
        raise IPCContractError("PROTOCOL_REQUEST_ID_MISMATCH")
    if expected_job_id is not None and message["job_id"] != expected_job_id:
        raise IPCContractError("PROTOCOL_JOB_ID_MISMATCH")
    return message


def parse_and_validate_request(raw: bytes) -> dict[str, Any]:
    return validate_request(parse_jsonl_message(raw))


def parse_and_validate_result(raw: bytes, *, expected_request_id: str | None = None,
                              expected_job_id: str | None = None) -> dict[str, Any]:
    return validate_result(parse_jsonl_message(raw), expected_request_id=expected_request_id,
                           expected_job_id=expected_job_id)


def canonical_jsonl_message(message: dict[str, Any]) -> bytes:
    """Serialize a valid v1 request/result as deterministic UTF-8 JSONL.

    Canonical form uses lexicographically sorted object keys at every depth,
    compact separators, literal UTF-8 Unicode, finite JSON numbers only, and
    exactly one LF terminator. It is deterministic for this Python JSON
    implementation; it is not a claim of RFC 8785/JCS number canonicalization.
    """
    if not isinstance(message, dict):
        raise IPCContractError("PROTOCOL_OBJECT_REQUIRED")
    message_type = message.get("message_type")
    if message_type == "synthesis.request":
        validate_request(message)
    elif message_type == "synthesis.result":
        validate_result(message)
    else:
        raise IPCContractError("PROTOCOL_SCHEMA_INVALID:message_type")
    try:
        payload = json.dumps(
            message, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise IPCContractError("PROTOCOL_SERIALIZATION_INVALID") from exc
    raw = payload + b"\n"
    if len(raw) > MAX_LINE_BYTES:
        raise IPCContractError("PROTOCOL_LINE_TOO_LARGE")
    return raw
