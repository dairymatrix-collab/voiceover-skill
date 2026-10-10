"""Independent, machine-readable v1 JSON Schema conformance vectors."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ipc_contract import (
    IPCContractError, load_schema, validate_request, validate_result,
)

ROOT = Path(__file__).resolve().parent
VECTOR_FILE = ROOT / "fixtures" / "schema-conformance-v1.json"


def _base_request() -> dict:
    return {
        "protocol_version": 1, "message_type": "synthesis.request",
        "request_id": "req_vectors", "job_id": "job_vectors", "engine_id": "kokoro",
        "text": "Conformance vector", "options": {"language": "en-us", "voice_id": "af_heart", "speed": 1.0, "seed": 1, "output_format": "wav"},
        "deadline_ms": 30000, "reference_audio": None,
    }


def _base_result() -> dict:
    return {
        "protocol_version": 1, "message_type": "synthesis.result",
        "request_id": "req_vectors", "job_id": "job_vectors", "status": "ok",
        "duration_ms": 1000,
        "output": {"relative_path": "outputs/final.wav", "format": "wav", "sample_rate_hz": 24000, "channels": 1, "frame_count": 24000, "size_bytes": 48044},
        "error": None,
    }


def _assign_path(target: dict, path: list[str], value) -> None:
    node = target
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


def _schema_valid(kind: str, message: dict) -> bool:
    schema_file = "synthesis-request-v1.schema.json" if kind == "request" else "synthesis-result-v1.schema.json"
    return Draft202012Validator(load_schema(schema_file)).is_valid(message)


def _public_valid(kind: str, message: dict) -> bool:
    try:
        (validate_request if kind == "request" else validate_result)(message)
    except IPCContractError:
        return False
    return True


@pytest.fixture(scope="module")
def vectors():
    return json.loads(VECTOR_FILE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("kind", ["request", "result"])
def test_conformance_vector_file_has_valid_json_schema(vectors, kind):
    assert vectors["protocol"] == "voiceover-ipc-v1-schema-vectors"
    schema_name = f"synthesis-{kind}-v1.schema.json"
    Draft202012Validator.check_schema(load_schema(schema_name))


@pytest.mark.parametrize("kind", ["request", "result"])
def test_schema_vectors_match_expected_and_public_validator(vectors, kind):
    base = _base_request() if kind == "request" else _base_result()
    failures = []
    for vector in vectors[kind]:
        candidate = copy.deepcopy(base)
        _assign_path(candidate, vector["path"], vector["value"])
        schema_ok = _schema_valid(kind, candidate)
        public_ok = _public_valid(kind, candidate)
        if schema_ok != vector["valid"] or public_ok != vector["valid"] or schema_ok != public_ok:
            failures.append({"name": vector["name"], "expected": vector["valid"], "schema": schema_ok, "public": public_ok})
    assert not failures, json.dumps(failures, ensure_ascii=False, sort_keys=True)


def test_python_only_nonfinite_numbers_are_rejected_even_though_not_json_values():
    request = _base_request()
    request["options"]["speed"] = float("nan")
    with pytest.raises(IPCContractError):
        validate_request(request)
    request["options"]["speed"] = float("inf")
    with pytest.raises(IPCContractError):
        validate_request(request)


def test_schema_vectors_are_deterministic_and_named(vectors):
    names = [v["name"] for kind in ("request", "result") for v in vectors[kind]]
    assert len(names) == len(set(names))
    assert len(names) >= 25
