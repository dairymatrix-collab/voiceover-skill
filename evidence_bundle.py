"""Cross-file integrity manifest for evidence bundles (model-free; no authenticity claim).

The bundle manifest hashes every regular payload file, including the provenance
 envelope. The envelope lists payload artifacts other than itself and the manifest.
This avoids a circular hash dependency. A verifier checks both directions and rejects
missing, extra, unsafe, symlinked, or changed files. SHA-256 is not a signature.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any

from jsonschema import Draft202012Validator

MANIFEST_NAME = "evidence-bundle-manifest-v1.json"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / MANIFEST_NAME.replace(".json", ".schema.json")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CANONICALIZATION = "utf8-json-sort-keys-compact-v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative_path(raw: Any) -> bool:
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        return False
    path = PurePosixPath(raw)
    return (not path.is_absolute() and path.as_posix() == raw
            and all(part not in {"", ".", ".."} for part in path.parts)
            and re.match(r"^[A-Za-z]:", raw) is None)


def canonical_bundle_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def build_evidence_bundle_manifest(root: str | Path, envelope_path: str = "provenance-envelope.json") -> dict[str, Any]:
    """Create a manifest in memory; caller writes it after the envelope and payload are final."""
    base = Path(root).resolve()
    if not base.is_dir():
        raise ValueError("bundle root must be an existing directory")
    if not _safe_relative_path(envelope_path) or envelope_path == MANIFEST_NAME:
        raise ValueError("envelope_path must be a safe relative path distinct from the manifest")
    envelope_file = base.joinpath(*PurePosixPath(envelope_path).parts)
    if not envelope_file.is_file() or envelope_file.is_symlink() or not envelope_file.resolve().is_relative_to(base):
        raise ValueError("provenance envelope must be a regular file inside the bundle")
    files = []
    for path in sorted(base.rglob("*"), key=lambda item: item.relative_to(base).as_posix()):
        if path.is_symlink():
            raise ValueError(f"symlink is not allowed in evidence bundle: {path.relative_to(base).as_posix()}")
        if not path.is_file():
            continue
        rel = path.relative_to(base).as_posix()
        if rel == MANIFEST_NAME:
            continue
        if not _safe_relative_path(rel):
            raise ValueError(f"unsafe bundle file path: {rel!r}")
        files.append({"path": rel, "sha256": _sha256(path), "size_bytes": path.stat().st_size})
    envelope_entry = next((item for item in files if item["path"] == envelope_path), None)
    if envelope_entry is None:
        raise ValueError("provenance envelope missing from file inventory")
    return {
        "manifest_schema_version": "1.0",
        "hash_algorithm": "sha256",
        "canonicalization": CANONICALIZATION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "envelope_path": envelope_path,
        "envelope_sha256": envelope_entry["sha256"],
        "files": files,
        "limitations": ["SHA-256 detects byte changes only relative to a trusted manifest; this manifest is unsigned and does not authenticate its author."],
    }


def verify_evidence_bundle(root: str | Path, *, manifest_name: str = MANIFEST_NAME) -> list[str]:
    """Return all integrity/relationship errors; empty list means local consistency only."""
    base = Path(root).resolve()
    errors: list[str] = []
    manifest_path = base / manifest_name
    if not _safe_relative_path(manifest_name) or not manifest_path.is_file() or manifest_path.is_symlink():
        return ["manifest is missing or unsafe"]
    try:
        raw = manifest_path.read_bytes()
        if len(raw) > 4 * 1024 * 1024:
            return ["manifest exceeds size limit"]
        def no_dupes(pairs):
            out = {}
            for key, value in pairs:
                if key in out:
                    raise ValueError(f"duplicate JSON key: {key}")
                out[key] = value
            return out
        manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=no_dupes,
                              parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid constant {value}")))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
        return [f"manifest parse failed: {type(exc).__name__}"]
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        schema_errors = list(Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).iter_errors(manifest))
        errors.extend(f"manifest schema: {e.message}" for e in schema_errors)
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        return [f"manifest schema unavailable; failing closed ({type(exc).__name__})"]
    if errors:
        return errors
    if manifest.get("manifest_schema_version") != "1.0" or manifest.get("hash_algorithm") != "sha256" or manifest.get("canonicalization") != CANONICALIZATION:
        errors.append("unsupported manifest version, hash algorithm, or canonicalization")
    envelope_path = manifest.get("envelope_path")
    if not _safe_relative_path(envelope_path) or envelope_path == manifest_name:
        errors.append("envelope_path is unsafe or points to manifest")
    entries = manifest.get("files", [])
    by_path: dict[str, dict[str, Any]] = {}
    for entry in entries:
        rel = entry.get("path")
        if not _safe_relative_path(rel):
            errors.append(f"unsafe manifest file path: {rel!r}")
            continue
        if rel in by_path:
            errors.append(f"duplicate manifest path: {rel}")
            continue
        by_path[rel] = entry
        path = base.joinpath(*PurePosixPath(rel).parts)
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(base):
            errors.append(f"missing or unsafe file: {rel}")
            continue
        if path.stat().st_size != entry["size_bytes"]:
            errors.append(f"size mismatch: {rel}")
        if _sha256(path) != entry["sha256"]:
            errors.append(f"SHA-256 mismatch: {rel}")
    actual: set[str] = set()
    for path in base.rglob("*"):
        if path.is_symlink():
            errors.append(f"symlink is not allowed: {path.relative_to(base).as_posix()}")
        elif path.is_file() and path != manifest_path:
            actual.add(path.relative_to(base).as_posix())
    for rel in sorted(actual - set(by_path)):
        errors.append(f"unlisted file: {rel}")
    for rel in sorted(set(by_path) - actual):
        errors.append(f"manifest lists absent file: {rel}")
    env_entry = by_path.get(envelope_path) if isinstance(envelope_path, str) else None
    if not env_entry:
        errors.append("manifest envelope_path is not in file inventory")
    elif manifest.get("envelope_sha256") != env_entry.get("sha256"):
        errors.append("envelope_sha256 does not match envelope file inventory")
    else:
        try:
            from evidence_provenance import parse_provenance_json
            envelope = parse_provenance_json((base / envelope_path).read_bytes())
            payload_artifacts = {item["path"]: item["sha256"] for item in envelope["artifacts"]}
            expected_payload = {rel: entry["sha256"] for rel, entry in by_path.items() if rel != envelope_path}
            if payload_artifacts != expected_payload:
                errors.append("envelope artifact hashes do not exactly match bundle payload files (excluding envelope and manifest)")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"envelope verification failed: {type(exc).__name__}")
    return errors
