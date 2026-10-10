import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from evidence_provenance import canonical_provenance_json, validate_provenance_envelope

ROOT = Path(__file__).parents[1]
DIGEST = "a" * 64


def envelope():
    return {
        "envelope_schema_version": "1.0",
        "evidence_id": "ev-test-001",
        "created_at": "2026-10-04T10:00:00Z",
        "evidence_digest": DIGEST,
        "source": {"kind": "test_harness", "tool": "pytest", "version": "9.0-test", "invocation_id": "run-001"},
        "provider": {"provider_id": "fake-provider", "provider_version": "1.0", "target_platform": "test-os", "identity_claim_basis": "self_reported"},
        "test_environment": {"os_name": "Linux", "architecture": "x86_64", "runtime_version": "Python 3.13", "harness_version": "0.1", "started_at": "2026-10-04T09:59:00Z", "finished_at": "2026-10-04T10:00:00Z"},
        "artifacts": [{"path": "evidence/report.json", "sha256": DIGEST, "hash_basis": "bytes_read_locally"}],
        "trust_level": "self_reported",
        "verification_state": "unverified",
        "limitations": ["Synthetic fixture; no real provider or sandbox tested."],
        "signature": {"status": "not_present"},
    }


def test_valid_unverified_envelope_passes_schema_and_semantics():
    value = envelope()
    schema = json.loads((ROOT / "schemas/evidence-provenance-envelope-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(value)
    assert validate_provenance_envelope(value) == []
    assert canonical_provenance_json(value) == canonical_provenance_json(deepcopy(value))


def test_self_claimed_independent_verification_rejected_without_external_verifier():
    value = envelope()
    value["trust_level"] = "independently_verified"
    value["verification_state"] = "verified"
    assert any("external verifier" in e for e in validate_provenance_envelope(value))


def test_authenticated_claim_requires_verified_signature_and_verifier_boundary():
    value = envelope()
    value["trust_level"] = "cryptographically_authenticated"
    value["verification_state"] = "verified"
    value["signature"] = {"status": "verified", "algorithm": "Ed25519", "key_id": "test-key"}
    errors = validate_provenance_envelope(value)
    assert any("trusted external verifier" in e for e in errors)
    assert validate_provenance_envelope(value, verifier_evidence=True) == []


def test_external_verifier_does_not_allow_signature_claim_without_signature_record():
    value = envelope()
    value["trust_level"] = "cryptographically_authenticated"
    value["verification_state"] = "verified"
    value["signature"] = {"status": "not_present"}
    assert any("signature cannot be absent" in e for e in validate_provenance_envelope(value, verifier_evidence=True))


@pytest.mark.parametrize("field,value", [
    ("created_at", "2026-10-04T10:00:00"),
    ("evidence_digest", "not-a-digest"),
    ("artifacts", [{"path": "../escape", "sha256": DIGEST, "hash_basis": "bytes_read_locally"}]),
    ("artifacts", [{"path": "same", "sha256": DIGEST, "hash_basis": "bytes_read_locally"}, {"path": "same", "sha256": DIGEST, "hash_basis": "reported_by_source"}]),
])
def test_invalid_timestamp_digest_and_artifact_paths_rejected(field, value):
    payload = envelope()
    payload[field] = value
    assert validate_provenance_envelope(payload)


def test_finished_before_started_rejected():
    payload = envelope()
    payload["test_environment"]["finished_at"] = "2026-10-04T09:58:00Z"
    assert any("precedes" in e for e in validate_provenance_envelope(payload))


def test_secret_material_never_allowed_in_signature_envelope():
    payload = envelope()
    payload["signature"]["private_key"] = "must-not-be-here"
    assert validate_provenance_envelope(payload)  # schema rejects undeclared secret fields


def test_verified_state_conflicts_with_low_trust():
    payload = envelope()
    payload["verification_state"] = "verified"
    assert any("conflicts with lower trust_level" in e for e in validate_provenance_envelope(payload))


def test_schema_rejected_mutations_are_never_accepted_by_semantic_validator():
    baseline = envelope()
    mutations = []
    for field in baseline:
        candidate = deepcopy(baseline)
        del candidate[field]
        mutations.append(candidate)
    candidate = deepcopy(baseline)
    candidate["unexpected"] = {"deep": [1, 2, 3]}
    mutations.append(candidate)
    candidate = deepcopy(baseline)
    candidate["source"]["unexpected"] = "x"
    mutations.append(candidate)
    candidate = deepcopy(baseline)
    candidate["artifacts"][0]["unexpected"] = True
    mutations.append(candidate)
    candidate = deepcopy(baseline)
    candidate["provider"]["identity_claim_basis"] = {"self_reported": True}
    mutations.append(candidate)

    schema = json.loads((ROOT / "schemas/evidence-provenance-envelope-v1.schema.json").read_text())
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    for candidate in mutations:
        assert not validator.is_valid(candidate)
        assert validate_provenance_envelope(candidate), "semantic validator accepted schema-invalid input"


def test_semantic_validator_is_stricter_than_schema_for_unsafe_paths_and_trust_claims():
    schema = json.loads((ROOT / "schemas/evidence-provenance-envelope-v1.schema.json").read_text())
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    for path in ("../escape", "./dot", "C:/windows/file", "folder\\file", "nul\x00path"):
        candidate = envelope()
        candidate["artifacts"][0]["path"] = path
        assert validator.is_valid(candidate), f"test expects path policy to be semantic: {path!r}"
        assert validate_provenance_envelope(candidate)
    candidate = envelope()
    candidate["trust_level"] = "independently_verified"
    candidate["verification_state"] = "verified"
    assert validator.is_valid(candidate)
    assert validate_provenance_envelope(candidate)


def test_timezone_comparison_uses_instants_not_lexical_strings():
    candidate = envelope()
    candidate["test_environment"]["started_at"] = "2026-10-04T12:30:00+02:00"
    candidate["test_environment"]["finished_at"] = "2026-10-04T09:00:00Z"
    assert any("precedes" in error for error in validate_provenance_envelope(candidate))


def test_parse_provenance_json_rejects_duplicate_keys_at_nested_levels():
    from evidence_provenance import parse_provenance_json
    raw = json.dumps(envelope(), separators=(",", ":"))
    assert parse_provenance_json(raw)["evidence_id"] == "ev-test-001"
    assert "duplicate JSON object key" in str(pytest.raises(ValueError, parse_provenance_json, '{"a":{"x":1,"x":2}}').value)


@pytest.mark.parametrize("raw", [
    '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', '[]', 'null', '"text"',
])
def test_parse_provenance_json_rejects_nonstandard_constants_and_nonobject_roots(raw):
    from evidence_provenance import parse_provenance_json
    with pytest.raises(ValueError):
        parse_provenance_json(raw)


def test_parse_provenance_json_enforces_byte_limit_and_utf8():
    from evidence_provenance import parse_provenance_json
    with pytest.raises(ValueError, match="size limit"):
        parse_provenance_json(b" " * 32, max_bytes=16)
    with pytest.raises(ValueError, match="invalid provenance JSON"):
        parse_provenance_json(b"\xff\xfe")
    with pytest.raises(ValueError, match="invalid provenance JSON"):
        parse_provenance_json("\ud800")


def test_parser_and_validator_fail_closed_on_deeply_nested_hostile_input():
    from evidence_provenance import parse_provenance_json
    with pytest.raises(ValueError):
        parse_provenance_json(("[" * 2000) + ("]" * 2000))
    candidate = envelope()
    recursive = {}
    recursive["self"] = recursive
    candidate["source"]["tool"] = recursive
    assert validate_provenance_envelope(candidate)


def test_canonical_serializer_rejects_non_json_values_and_nonfinite_numbers():
    candidate = envelope()
    candidate["unexpected"] = object()
    with pytest.raises((TypeError, ValueError)):
        canonical_provenance_json(candidate)
    candidate = envelope()
    candidate["extra"] = float("nan")
    with pytest.raises(ValueError):
        canonical_provenance_json(candidate)
