"""End-to-end JSONL framing, parsing, validation, and failure-classification matrix."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipc_contract import (
    IPCContractError,
    canonical_jsonl_message,
    parse_and_validate_request,
    parse_and_validate_result,
)

FIXTURES = Path(__file__).parent / "fixtures" / "protocol-v1"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_request_fixture_full_jsonl_round_trip_preserves_payload():
    request = fixture("valid-request.json")
    wire = canonical_jsonl_message(request)
    assert wire.endswith(b"\n") and not wire.endswith(b"\n\n")
    assert b"\r" not in wire
    assert parse_and_validate_request(wire) == request


def test_result_fixture_full_jsonl_round_trip_preserves_payload():
    result = fixture("valid-result.json")
    wire = canonical_jsonl_message(result)
    assert wire.endswith(b"\n") and not wire.endswith(b"\n\n")
    assert parse_and_validate_result(
        wire, expected_request_id=result["request_id"], expected_job_id=result["job_id"]
    ) == result


@pytest.mark.parametrize("name", [
    "invalid-request-future-version.json",
    "invalid-request-unknown-field.json",
])
def test_invalid_v1_fixtures_fail_with_schema_classification(name):
    message = fixture(name)
    with pytest.raises(IPCContractError) as error:
        parse_and_validate_request(json.dumps(message, separators=(",", ":")).encode() + b"\n")
    assert error.value.code == "PROTOCOL_SCHEMA_INVALID"


@pytest.mark.parametrize("raw,expected_code", [
    (b"", "PROTOCOL_TRUNCATED_LINE"),
    (b"{\"message_type\":\"x\"}", "PROTOCOL_TRUNCATED_LINE"),
    (b"\n", "PROTOCOL_BLANK_LINE"),
    (b"{broken}\n", "PROTOCOL_INVALID_JSON"),
    (b"[]\n", "PROTOCOL_OBJECT_REQUIRED"),
    (b"{\"x\":1,\"x\":2}\n", "PROTOCOL_DUPLICATE_KEY"),
    (b"{\"x\":NaN}\n", "PROTOCOL_NONFINITE_NUMBER"),
    (b"{\"x\":1e999}\n", "PROTOCOL_NONFINITE_NUMBER"),
    (b"{\"x\":\"\\ud800\"}\n", "PROTOCOL_INVALID_UNICODE"),
    (b"\xff\n", "PROTOCOL_INVALID_UTF8"),
    (b"{\"x\":1}\n{\"y\":2}\n", "PROTOCOL_MULTILINE_MESSAGE"),
])
def test_jsonl_failure_matrix_has_stable_classification(raw, expected_code):
    # The public request pipeline first classifies framing/parsing failures;
    # valid JSON objects then continue to request-schema validation.
    with pytest.raises(IPCContractError) as error:
        parse_and_validate_request(raw)
    assert error.value.code == expected_code


@pytest.mark.parametrize("mutation,expected_code", [
    (lambda m: m.update(protocol_version=2), "PROTOCOL_SCHEMA_INVALID"),
    (lambda m: m.update(message_type="wrong.type"), "PROTOCOL_SCHEMA_INVALID"),
    (lambda m: m.update(deadline_ms=True), "PROTOCOL_SCHEMA_INVALID"),
    (lambda m: m.update(unexpected_field="x"), "PROTOCOL_SCHEMA_INVALID"),
    (lambda m: m.update(reference_audio={"relative_path": "../secret.wav", "media_type": "audio/wav"}), "PROTOCOL_PATH_INVALID"),
])
def test_request_e2e_semantic_failures_are_classified(mutation, expected_code):
    request = fixture("valid-request.json")
    mutation(request)
    raw = json.dumps(request, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"
    with pytest.raises(IPCContractError) as error:
        parse_and_validate_request(raw)
    assert error.value.code == expected_code


@pytest.mark.parametrize("expected_kwargs,expected_code", [
    ({"expected_request_id": "wrong"}, "PROTOCOL_REQUEST_ID_MISMATCH"),
    ({"expected_job_id": "wrong"}, "PROTOCOL_JOB_ID_MISMATCH"),
])
def test_result_e2e_correlation_failures_are_classified(expected_kwargs, expected_code):
    valid_result = fixture("valid-result.json")
    raw = canonical_jsonl_message(valid_result)
    with pytest.raises(IPCContractError) as error:
        parse_and_validate_result(raw, **expected_kwargs)
    assert error.value.code == expected_code


def test_utf8_multilingual_text_survives_full_request_pipeline():
    request = fixture("valid-request.json")
    request["text"] = "Salam دنیا — مرحبا — こんにちは — 🎙️"
    wire = canonical_jsonl_message(request)
    assert "دنیا".encode("utf-8") in wire
    assert parse_and_validate_request(wire)["text"] == request["text"]


def test_failure_matrix_documents_stage_order_for_nonfinite_number():
    # Invalid numeric tokens are parser errors; equivalent direct Python values
    # are handled at the semantic validation layer (covered by contract tests).
    raw = b'{"protocol_version":1,"message_type":"synthesis.request","options":{"speed":NaN}}\n'
    with pytest.raises(IPCContractError) as error:
        parse_and_validate_request(raw)
    assert error.value.code == "PROTOCOL_NONFINITE_NUMBER"
