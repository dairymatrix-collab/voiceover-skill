#!/usr/bin/env python3
"""Run TTS in a killable subprocess with a bounded wall-clock timeout."""
from __future__ import annotations
import argparse
import json
import os
import re
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "scripts" / "voiceover_worker.py"
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
V2_OUTPUT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,123}\.wav$")
V1_SUPPORTED_ENGINES = frozenset({"kokoro"})
V2_SUPPORTED_ENGINES = frozenset({"kokoro", "qwen3_tts"})


def _normalize_v2(raw: dict, engine_override: str | None,
                  profile_store_dir: str | Path | None) -> tuple[dict, float]:
    allowed = {"protocol_version", "message_type", "request_id", "job_id", "engine_id", "text",
               "voice_profile_id", "options", "deadline_ms", "trace_id"}
    required = allowed - {"trace_id"}
    if set(raw) - allowed or not required.issubset(raw):
        raise ValueError("INVALID_REQUEST_FIELDS")
    if type(raw.get("protocol_version")) is not int or raw["protocol_version"] != 2:
        raise ValueError("INVALID_REQUEST_VERSION")
    if raw.get("message_type") != "synthesis.request":
        raise ValueError("INVALID_REQUEST_VERSION")
    for field, error in (("request_id", "INVALID_REQUEST_ID"), ("job_id", "INVALID_JOB_ID"),
                         ("voice_profile_id", "INVALID_VOICE_PROFILE_ID")):
        value = raw.get(field)
        if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
            raise ValueError(error)
    if "trace_id" in raw and (not isinstance(raw["trace_id"], str) or not ID_PATTERN.fullmatch(raw["trace_id"])):
        raise ValueError("INVALID_TRACE_ID")
    engine_id = raw.get("engine_id")
    if not isinstance(engine_id, str) or engine_id not in V2_SUPPORTED_ENGINES:
        raise ValueError("ENGINE_PATH_NOT_VERIFIED")
    if engine_override is not None and engine_override != engine_id:
        raise ValueError("PROFILE_ENGINE_OVERRIDE_MISMATCH")
    text = raw.get("text")
    if (not isinstance(text, str) or not text.strip() or len(text) > 100000
            or any((ord(char) < 32 and char not in "\r\n\t") or ord(char) == 127 for char in text)):
        raise ValueError("INVALID_TEXT")
    options = raw.get("options")
    if not isinstance(options, dict) or set(options) - {"chunk_chars", "output_name", "output_format"}:
        raise ValueError("INVALID_OPTIONS")
    if options.get("output_format") != "wav":
        raise ValueError("UNSUPPORTED_OUTPUT_FORMAT")
    chunk_chars = options.get("chunk_chars", 800)
    if isinstance(chunk_chars, bool) or not isinstance(chunk_chars, int) or not 100 <= chunk_chars <= 1200:
        raise ValueError("INVALID_CHUNK_LIMIT")
    output_name = options.get("output_name", "voiceover.wav")
    if not isinstance(output_name, str) or not V2_OUTPUT_PATTERN.fullmatch(output_name):
        raise ValueError("INVALID_OUTPUT_NAME")
    deadline = raw.get("deadline_ms")
    if isinstance(deadline, bool) or not isinstance(deadline, int) or not 1 <= deadline <= 3_600_000:
        raise ValueError("INVALID_DEADLINE")
    normalized = {
        "request_id": raw["request_id"],
        "text": text,
        # Worker resolves these two fields from the selected local profile before
        # constructing PipelineRequest; placeholders never reach a model adapter.
        "language": "en",
        "voice_id": "profile_voice",
        "speed": 1.0,
        "seed": None,
        "chunk_chars": chunk_chars,
        "output_name": output_name,
        "engine": engine_id,
        "voice_profile_id": raw["voice_profile_id"],
    }
    if profile_store_dir is not None:
        if not isinstance(profile_store_dir, (str, Path)):
            raise ValueError("PROFILE_STORE_PATH_INVALID")
        normalized["profile_store_dir"] = str(Path(profile_store_dir).expanduser())
    return normalized, deadline / 1000.0


def normalize_request(raw: dict, engine_override: str | None = None,
                      profile_store_dir: str | Path | None = None) -> tuple[dict, float | None]:
    """Map public requests to internal pipeline fields; v1 and legacy inputs remain supported.

    Version 2 contains a profile ID only. Prompts, audio references, controls, and
    local profile-store paths are resolved/selected on the local computer.
    """
    envelope_markers = {"protocol_version", "message_type", "engine_id", "options", "deadline_ms",
                        "reference_audio", "job_id", "voice_profile_id"}
    if not envelope_markers.intersection(raw):
        normalized = dict(raw)
        selected_engine = engine_override or normalized.get("engine")
        if selected_engine is not None and selected_engine not in V1_SUPPORTED_ENGINES:
            raise ValueError("ENGINE_PATH_NOT_VERIFIED")
        if engine_override:
            normalized["engine"] = engine_override
        return normalized, None

    if type(raw.get("protocol_version")) is int and raw.get("protocol_version") == 2:
        return _normalize_v2(raw, engine_override, profile_store_dir)

    allowed = {"protocol_version", "message_type", "request_id", "job_id", "engine_id", "text",
               "options", "deadline_ms", "reference_audio", "trace_id"}
    if set(raw) - allowed:
        raise ValueError("INVALID_REQUEST_FIELDS")
    required = allowed - {"trace_id"}
    if not required.issubset(raw):
        raise ValueError("INVALID_REQUEST_FIELDS")
    if type(raw.get("protocol_version")) is not int or raw["protocol_version"] != 1 or raw.get("message_type") != "synthesis.request":
        raise ValueError("INVALID_REQUEST_VERSION")
    if not isinstance(raw.get("request_id"), str) or not ID_PATTERN.fullmatch(raw["request_id"]):
        raise ValueError("INVALID_REQUEST_ID")
    if not isinstance(raw.get("job_id"), str) or not ID_PATTERN.fullmatch(raw["job_id"]):
        raise ValueError("INVALID_JOB_ID")
    if "trace_id" in raw and (not isinstance(raw["trace_id"], str) or not ID_PATTERN.fullmatch(raw["trace_id"])):
        raise ValueError("INVALID_TRACE_ID")
    if not isinstance(raw.get("engine_id"), str) or raw.get("engine_id") not in {"qwen3_tts", "chatterbox", "kokoro"}:
        raise ValueError("INVALID_ENGINE_ID")
    selected_engine = engine_override or raw["engine_id"]
    if selected_engine not in V1_SUPPORTED_ENGINES:
        raise ValueError("ENGINE_PATH_NOT_VERIFIED")
    deadline = raw.get("deadline_ms")
    if isinstance(deadline, bool) or not isinstance(deadline, int) or not 1 <= deadline <= 86_400_000:
        raise ValueError("INVALID_DEADLINE")
    if raw.get("reference_audio") is not None:
        raise ValueError("REFERENCE_AUDIO_NOT_SUPPORTED")
    options = raw.get("options")
    if not isinstance(options, dict) or set(options) - {"language", "voice_id", "speed", "seed", "output_format"}:
        raise ValueError("INVALID_OPTIONS")
    if options.get("output_format", "wav") != "wav":
        raise ValueError("UNSUPPORTED_OUTPUT_FORMAT")
    if not isinstance(options.get("language"), str) or not isinstance(options.get("voice_id"), str):
        raise ValueError("MISSING_LANGUAGE_OR_VOICE")
    normalized = {
        "request_id": raw["request_id"], "text": raw.get("text"),
        "language": options["language"], "voice_id": options["voice_id"],
        "speed": options.get("speed", 1.0), "seed": options.get("seed"),
        "engine": selected_engine,
    }
    return normalized, deadline / 1000.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path, help="UTF-8 JSON request file")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--engine", choices=("qwen3_tts", "kokoro"))
    parser.add_argument("--profile-store", type=Path, help="local voice-profile store root (v2 requests only)")
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    args = parser.parse_args()
    if not (0.1 <= args.timeout_seconds <= 86400):
        parser.error("--timeout-seconds must be between 0.1 and 86400")
    try:
        raw = json.loads(args.request.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        print(json.dumps({"ok": False, "error": "REQUEST_FILE_INVALID"}, sort_keys=True))
        return 2
    if not isinstance(raw, dict):
        print(json.dumps({"ok": False, "error": "REQUEST_MUST_BE_OBJECT"}, sort_keys=True))
        return 2
    if "output_dir" in raw or "engine" in raw or "profile_store_dir" in raw:
        print(json.dumps({"ok": False, "error": "RESERVED_REQUEST_FIELD"}, sort_keys=True))
        return 2
    try:
        raw, request_deadline = normalize_request(raw, args.engine, args.profile_store)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2
    raw["output_dir"] = str(args.output_dir.expanduser().resolve())
    payload = json.dumps(raw, ensure_ascii=False, allow_nan=False)
    effective_timeout = min(args.timeout_seconds, request_deadline) if request_deadline is not None else args.timeout_seconds
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        profile_request = isinstance(raw.get("voice_profile_id"), str)
        completed = execute_worker(payload, effective_timeout, env, managed=profile_request,
                                   engine_id=raw.get("engine"))
    except subprocess.TimeoutExpired as exc:
        timeout_response = {"ok": False, "error": "INFERENCE_TIMEOUT",
                            "timeout_seconds": effective_timeout}
        resource_usage = getattr(exc, "resource_report", None)
        if isinstance(resource_usage, dict):
            timeout_response["resource_usage"] = resource_usage
        print(json.dumps(timeout_response, sort_keys=True))
        return 124
    try:
        response = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        print(json.dumps({"ok": False, "error": "WORKER_PROTOCOL_ERROR",
                          "worker_exit_code": completed.returncode}, sort_keys=True))
        return 3
    resource_report = getattr(completed, "resource_report", None)
    if isinstance(response, dict) and isinstance(resource_report, dict):
        response["resource_usage"] = resource_report
    print(json.dumps(response, ensure_ascii=False, sort_keys=True))
    return completed.returncode


def execute_worker(payload: str, timeout_seconds: float, env: dict[str, str], *,
                   managed: bool = False, engine_id: str | None = None,
                   model_root: str | Path | None = None) -> subprocess.CompletedProcess:
    """Run the trusted worker entry point without a shell and with a hard deadline."""
    argv = [sys.executable, str(WORKER)]
    if managed:
        try:
            from resource_guard import run_managed_process
        except ImportError:
            completed = subprocess.CompletedProcess(argv, 75,
                json.dumps({"ok": False, "error": "RESOURCE_MONITOR_UNAVAILABLE"}, sort_keys=True), "")
            completed.resource_report = {"monitor_available": False}
            return completed
        return run_managed_process(argv, input_text=payload, timeout_seconds=timeout_seconds,
                                   environment=env, cwd=ROOT, engine_id=engine_id or "",
                                   model_root=model_root)
    return subprocess.run(
        argv, input=payload, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_seconds,
        cwd=ROOT, env=env, check=False,
    )


if __name__ == "__main__":
    raise SystemExit(main())
