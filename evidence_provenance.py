"""Model-free evidence provenance envelope and trust-boundary validator.

This module describes provenance claims; it does not authenticate them. Hashes
provide content integrity only when compared to a digest obtained independently.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping

from jsonschema import Draft202012Validator

ENVELOPE_SCHEMA_VERSION = "1.0"
TRUST_LEVELS = {"self_reported", "locally_measured", "independently_verified", "cryptographically_authenticated"}
VERIFICATION_STATES = {"unverified", "partially_verified", "verified", "rejected"}
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_PROVENANCE_JSON_BYTES = 1_048_576
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "evidence-provenance-envelope-v1.schema.json"


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    return parsed if parsed.tzinfo is not None else None


def _valid_timestamp(value: Any) -> bool:
    return _parse_timestamp(value) is not None


def _schema_errors(envelope: Mapping[str, Any]) -> list[str]:
    """Return structural errors from the published schema; fail closed on validator errors."""
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
        return [f"schema: {error.message}" for error in sorted(validator.iter_errors(envelope), key=lambda e: (list(map(str, e.absolute_path)), e.message))]
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        return [f"schema validation unavailable; failing closed ({type(exc).__name__})"]


def validate_provenance_envelope(envelope: Mapping[str, Any], *, verifier_evidence: bool = False) -> list[str]:
    """Return semantic errors. verifier_evidence must be supplied by a trusted verifier.

    The boolean is a caller trust boundary, not a fact the envelope can assert
    about itself. Production callers must not derive it from envelope contents.
    """
    errors: list[str] = []
    if not isinstance(envelope, Mapping):
        return ["envelope root must be an object"]
    structural_errors = _schema_errors(envelope)
    if structural_errors:
        return structural_errors
    required = {
        "envelope_schema_version", "evidence_id", "created_at", "evidence_digest",
        "source", "provider", "test_environment", "artifacts", "trust_level",
        "verification_state", "limitations", "signature",
    }
    missing = sorted(required - set(envelope))
    if missing:
        return ["missing required fields: " + ", ".join(missing)]
    if envelope.get("envelope_schema_version") != ENVELOPE_SCHEMA_VERSION:
        errors.append("unsupported envelope_schema_version")
    if not isinstance(envelope.get("evidence_id"), str) or not envelope["evidence_id"].strip():
        errors.append("evidence_id must be a non-empty string")
    if not _valid_timestamp(envelope.get("created_at")):
        errors.append("created_at must be an ISO-8601 timestamp with timezone")
    if not isinstance(envelope.get("evidence_digest"), str) or not HEX_SHA256.fullmatch(envelope.get("evidence_digest", "")):
        errors.append("evidence_digest must be a lowercase SHA-256 hex digest")

    source = envelope.get("source")
    if not isinstance(source, Mapping):
        errors.append("source must be an object")
    else:
        for field in ("kind", "tool", "version", "invocation_id"):
            if not isinstance(source.get(field), str) or not source[field].strip():
                errors.append(f"source.{field} must be a non-empty string")
        if source.get("kind") not in {"test_harness", "provider_report", "manual_import", "external_verifier"}:
            errors.append("source.kind is unsupported")

    provider = envelope.get("provider")
    if not isinstance(provider, Mapping):
        errors.append("provider must be an object")
    else:
        for field in ("provider_id", "provider_version", "target_platform"):
            if not isinstance(provider.get(field), str) or not provider[field].strip():
                errors.append(f"provider.{field} must be a non-empty string")
        if provider.get("identity_claim_basis") not in {"self_reported", "package_metadata", "independent_observation", "trusted_registry"}:
            errors.append("provider.identity_claim_basis is unsupported")

    env = envelope.get("test_environment")
    if not isinstance(env, Mapping):
        errors.append("test_environment must be an object")
    else:
        for field in ("os_name", "architecture", "runtime_version", "harness_version"):
            if not isinstance(env.get(field), str) or not env[field].strip():
                errors.append(f"test_environment.{field} must be a non-empty string")
        if not _valid_timestamp(env.get("started_at")) or not _valid_timestamp(env.get("finished_at")):
            errors.append("test_environment timestamps must be ISO-8601 with timezone")
        else:
            started = _parse_timestamp(env["started_at"])
            finished = _parse_timestamp(env["finished_at"])
            if started is not None and finished is not None and finished < started:
                errors.append("test_environment.finished_at precedes started_at")

    artifacts = envelope.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        errors.append("artifacts must be a non-empty array")
    else:
        seen_paths: set[str] = set()
        for i, artifact in enumerate(artifacts):
            if not isinstance(artifact, Mapping):
                errors.append(f"artifacts[{i}] must be an object")
                continue
            path, digest = artifact.get("path"), artifact.get("sha256")
            if (not isinstance(path, str) or not path.strip() or path.startswith("/")
                    or ".." in path.split("/") or "." in path.split("/")
                    or "\\" in path or "\x00" in path
                    or re.match(r"^[A-Za-z]:", path) is not None):
                errors.append(f"artifacts[{i}].path must be a safe relative path")
            elif path in seen_paths:
                errors.append(f"duplicate artifact path: {path}")
            else:
                seen_paths.add(path)
            if not isinstance(digest, str) or not HEX_SHA256.fullmatch(digest):
                errors.append(f"artifacts[{i}].sha256 must be a lowercase SHA-256 digest")
            if artifact.get("hash_basis") not in {"bytes_read_locally", "reported_by_source", "independently_recomputed"}:
                errors.append(f"artifacts[{i}].hash_basis is unsupported")

    trust = envelope.get("trust_level")
    state = envelope.get("verification_state")
    if trust not in TRUST_LEVELS:
        errors.append("trust_level is unsupported")
    if state not in VERIFICATION_STATES:
        errors.append("verification_state is unsupported")
    if trust in {"independently_verified", "cryptographically_authenticated"} and not verifier_evidence:
        errors.append("elevated trust_level requires external verifier evidence; envelope self-claims are insufficient")
    if trust == "cryptographically_authenticated":
        signature = envelope.get("signature")
        if not isinstance(signature, Mapping) or signature.get("status") != "verified":
            errors.append("cryptographically_authenticated requires separately verified signature evidence")
        elif not verifier_evidence:
            errors.append("signature verification must be asserted by a trusted external verifier")
    if state == "verified" and trust not in {"independently_verified", "cryptographically_authenticated"}:
        errors.append("verification_state verified conflicts with lower trust_level")
    if state == "rejected" and trust == "cryptographically_authenticated":
        errors.append("rejected provenance cannot be cryptographically_authenticated")

    limitations = envelope.get("limitations")
    if not isinstance(limitations, list) or any(not isinstance(item, str) or not item.strip() for item in limitations):
        errors.append("limitations must be an array of non-empty strings")
    signature = envelope.get("signature")
    if not isinstance(signature, Mapping):
        errors.append("signature must be an object")
    else:
        status = signature.get("status")
        if status not in {"not_present", "not_verified", "verified", "invalid"}:
            errors.append("signature.status is unsupported")
        if status == "verified" and (not verifier_evidence or trust != "cryptographically_authenticated"):
            errors.append("signature.status verified requires external verifier evidence and authenticated trust level")
        if status == "not_present" and trust == "cryptographically_authenticated":
            errors.append("signature cannot be absent for cryptographically_authenticated evidence")
        # No secret material is accepted as part of this envelope.
        forbidden = {"private_key", "secret_key", "access_token", "password", "secret"}
        if forbidden.intersection(signature.keys()):
            errors.append("signature object must not contain secret or private-key material")
    return errors


def canonical_provenance_json(envelope: Mapping[str, Any]) -> str:
    """Canonical JSON for stable serialization; not a signature or trust proof."""
    import json
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def parse_provenance_json(raw: str | bytes, *, verifier_evidence: bool = False, max_bytes: int = MAX_PROVENANCE_JSON_BYTES) -> dict[str, Any]:
    """Parse untrusted envelope JSON with duplicate-key, non-finite, and size defenses."""
    if not isinstance(raw, (str, bytes)):
        raise ValueError("provenance JSON input must be str or bytes")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    try:
        encoded = raw.encode("utf-8", errors="strict") if isinstance(raw, str) else raw
        if len(encoded) > max_bytes:
            raise ValueError("provenance JSON exceeds size limit")
        text = encoded.decode("utf-8", errors="strict")
        def no_duplicate_keys(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON object key: {key}")
                result[key] = value
            return result
        def reject_constant(value):
            raise ValueError(f"non-standard JSON constant rejected: {value}")
        value = json.loads(text, object_pairs_hook=no_duplicate_keys, parse_constant=reject_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"invalid provenance JSON ({type(exc).__name__})") from exc
    if not isinstance(value, dict):
        raise ValueError("provenance JSON root must be an object")
    errors = validate_provenance_envelope(value, verifier_evidence=verifier_evidence)
    if errors:
        raise ValueError("invalid provenance envelope: " + "; ".join(errors))
    return value
