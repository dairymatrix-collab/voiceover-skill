import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from evidence_bundle import (MANIFEST_NAME, build_evidence_bundle_manifest,
                             canonical_bundle_json, verify_evidence_bundle)
from evidence_provenance import canonical_provenance_json
from test_evidence_provenance import envelope


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_bundle(root: Path):
    (root / "payload").mkdir(parents=True)
    (root / "payload" / "result.txt").write_bytes(b"verified locally\n")
    value = envelope()
    value["artifacts"] = [{"path": "payload/result.txt", "sha256": sha(b"verified locally\n"), "hash_basis": "bytes_read_locally"}]
    (root / "provenance-envelope.json").write_text(canonical_provenance_json(value), encoding="utf-8")
    manifest = build_evidence_bundle_manifest(root)
    (root / MANIFEST_NAME).write_bytes(canonical_bundle_json(manifest))


def test_bundle_manifest_schema_and_cross_file_binding_pass(tmp_path):
    make_bundle(tmp_path)
    schema = json.loads((Path(__file__).parents[1] / "schemas/evidence-bundle-manifest-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    manifest = json.loads((tmp_path / MANIFEST_NAME).read_text())
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(manifest)
    assert verify_evidence_bundle(tmp_path) == []


def test_payload_mutation_is_detected(tmp_path):
    make_bundle(tmp_path)
    (tmp_path / "payload/result.txt").write_bytes(b"tampered\n")
    assert any("SHA-256 mismatch" in error for error in verify_evidence_bundle(tmp_path))


def test_unlisted_extra_file_fails_closed(tmp_path):
    make_bundle(tmp_path)
    (tmp_path / "extra.bin").write_bytes(b"extra")
    assert any("unlisted file" in error for error in verify_evidence_bundle(tmp_path))


def test_envelope_artifact_list_must_match_manifest_exactly(tmp_path):
    make_bundle(tmp_path)
    path = tmp_path / "provenance-envelope.json"
    value = json.loads(path.read_text())
    value["artifacts"][0]["sha256"] = "b" * 64
    path.write_text(canonical_provenance_json(value))
    # Update only the manifest's envelope digest to isolate cross-file relationship check.
    manifest_path = tmp_path / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text())
    digest = sha(path.read_bytes())
    manifest["envelope_sha256"] = digest
    for item in manifest["files"]:
        if item["path"] == "provenance-envelope.json":
            item["sha256"] = digest
            item["size_bytes"] = path.stat().st_size
    manifest_path.write_bytes(canonical_bundle_json(manifest))
    assert any("artifact hashes do not exactly match" in error for error in verify_evidence_bundle(tmp_path))


def test_duplicate_manifest_paths_and_unsafe_paths_rejected(tmp_path):
    make_bundle(tmp_path)
    manifest_path = tmp_path / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text())
    manifest["files"].append(dict(manifest["files"][0]))
    manifest_path.write_bytes(canonical_bundle_json(manifest))
    assert any("duplicate manifest path" in error for error in verify_evidence_bundle(tmp_path))

    make_bundle(tmp_path / "other")
    manifest_path = tmp_path / "other" / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][0]["path"] = "../escape"
    manifest_path.write_bytes(canonical_bundle_json(manifest))
    assert any("unsafe manifest file path" in error for error in verify_evidence_bundle(tmp_path / "other"))


def test_manifest_digest_is_not_claimed_as_authenticity(tmp_path):
    make_bundle(tmp_path)
    manifest = json.loads((tmp_path / MANIFEST_NAME).read_text())
    assert any("unsigned" in item and "does not authenticate" in item for item in manifest["limitations"])
