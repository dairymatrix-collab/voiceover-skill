"""Deterministic schema-boundary mutation and error-path regression suite."""
from __future__ import annotations

import copy
import json

import pytest
from jsonschema import Draft202012Validator

from ipc_contract import (
    IPCContractError, canonical_jsonl_message, load_schema,
    validate_request, validate_result,
)


def base_request():
    return {
        "protocol_version": 1, "message_type": "synthesis.request",
        "request_id": "req_mutation", "job_id": "job_mutation", "engine_id": "kokoro",
        "text": "Mutation testing", "options": {"language": "en-us", "voice_id": "af_heart", "speed": 1.0, "seed": 1, "output_format": "wav"},
        "deadline_ms": 30000, "reference_audio": None,
    }


def base_result():
    return {
        "protocol_version": 1, "message_type": "synthesis.result",
        "request_id": "req_mutation", "job_id": "job_mutation", "status": "ok",
        "duration_ms": 1000,
        "output": {"relative_path": "outputs/final.wav", "format": "wav", "sample_rate_hz": 24000, "channels": 1, "frame_count": 24000, "size_bytes": 48044},
        "error": None,
    }


def schema_accepts(kind, candidate):
    name = f"synthesis-{kind}-v1.schema.json"
    return Draft202012Validator(load_schema(name)).is_valid(candidate)


def public_accepts(kind, candidate):
    try:
        (validate_request if kind == "request" else validate_result)(candidate)
    except IPCContractError:
        return False
    return True


@pytest.mark.parametrize("kind", ["request", "result"])
def test_required_field_deletion_mutations_match_schema_and_public_validator(kind):
    base = base_request() if kind == "request" else base_result()
    schema = load_schema(f"synthesis-{kind}-v1.schema.json")
    for field in schema["required"]:
        candidate = copy.deepcopy(base)
        del candidate[field]
        assert not schema_accepts(kind, candidate), f"schema accepted missing {field}"
        assert not public_accepts(kind, candidate), f"public validator accepted missing {field}"


@pytest.mark.parametrize("kind", ["request", "result"])
def test_top_level_unknown_field_mutation_is_rejected_consistently(kind):
    candidate = base_request() if kind == "request" else base_result()
    candidate["mutation_probe"] = {"nested": [None, True, 0, "x"]}
    assert schema_accepts(kind, candidate) is False
    assert public_accepts(kind, candidate) is False


@pytest.mark.parametrize("kind", ["request", "result"])
@pytest.mark.parametrize("bad_value", [None, True, 1, 1.25, [], {}, "\ud800"])
def test_message_type_mutation_is_rejected_consistently(kind, bad_value):
    candidate = base_request() if kind == "request" else base_result()
    candidate["message_type"] = bad_value
    assert schema_accepts(kind, candidate) is False
    assert public_accepts(kind, candidate) is False


@pytest.mark.parametrize("kind", ["request", "result"])
def test_recursive_python_container_fails_as_structured_contract_error(kind):
    candidate = base_request() if kind == "request" else base_result()
    recursive = []
    recursive.append(recursive)
    if kind == "request":
        candidate["options"]["voice_id"] = recursive
    else:
        candidate["error"] = {"code": "INTERNAL_ERROR", "message": "x", "retryable": True, "extra": recursive}
    with pytest.raises(IPCContractError) as caught:
        (validate_request if kind == "request" else validate_result)(candidate)
    assert caught.value.code == "PROTOCOL_SCHEMA_INVALID"


def test_canonical_serializer_converts_recursive_object_failure_to_contract_error():
    candidate = base_request()
    recursive = []
    recursive.append(recursive)
    candidate["options"]["voice_id"] = recursive
    with pytest.raises(IPCContractError):
        canonical_jsonl_message(candidate)


@pytest.mark.parametrize("kind", ["request", "result"])
def test_nested_unknown_field_mutation_is_rejected(kind):
    candidate = base_request() if kind == "request" else base_result()
    if kind == "request":
        candidate["options"]["unexpected"] = {"nested": "value"}
    else:
        candidate["output"]["unexpected"] = [1, 2, 3]
    assert schema_accepts(kind, candidate) is False
    assert public_accepts(kind, candidate) is False


@pytest.mark.parametrize("kind", ["request", "result"])
def test_valid_baseline_is_accepted_by_both_validators(kind):
    candidate = base_request() if kind == "request" else base_result()
    assert schema_accepts(kind, candidate) is True
    assert public_accepts(kind, candidate) is True
    serialized = canonical_jsonl_message(candidate)
    assert serialized.endswith(b"\\n") is False  # exactly one literal LF, not backslash+n
    assert serialized.endswith(b"\n")
    assert serialized.count(b"\n") == 1
    assert json.loads(serialized.decode("utf-8")) == candidate
