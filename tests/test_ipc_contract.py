from __future__ import annotations

import copy
import json

import pytest
from jsonschema import Draft202012Validator

from ipc_contract import (
    IPCContractError, MAX_LINE_BYTES, SCHEMA_DIR, canonical_jsonl_message, load_schema,
    parse_and_validate_request, parse_and_validate_result, parse_jsonl_message,
    validate_request, validate_result,
)


@pytest.fixture
def valid_request():
    return {
        "protocol_version": 1, "message_type": "synthesis.request",
        "request_id": "req_123", "job_id": "job_123", "engine_id": "kokoro",
        "text": "Hello, world!", "options": {"language": "en-us", "voice_id": "af_heart", "speed": 1.0, "seed": 42, "output_format": "wav"},
        "deadline_ms": 30000, "reference_audio": None,
    }


@pytest.fixture
def valid_result():
    return {
        "protocol_version": 1, "message_type": "synthesis.result",
        "request_id": "req_123", "job_id": "job_123", "status": "ok",
        "duration_ms": 1000,
        "output": {"relative_path": "output/result.wav", "format": "wav", "sample_rate_hz": 24000,
                   "channels": 1, "frame_count": 24000, "size_bytes": 48044},
        "error": None,
    }


def encode_line(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"


def test_both_json_schemas_are_valid_draft_2020_12():
    for name in ("synthesis-request-v1.schema.json", "synthesis-result-v1.schema.json"):
        schema = load_schema(name)
        Draft202012Validator.check_schema(schema)
        assert (SCHEMA_DIR / name).is_file()


def test_valid_request_round_trips(valid_request):
    assert parse_and_validate_request(encode_line(valid_request)) == valid_request


def test_valid_result_checks_correlation_ids(valid_result):
    assert parse_and_validate_result(encode_line(valid_result), expected_request_id="req_123", expected_job_id="job_123") == valid_result
    with pytest.raises(IPCContractError, match="PROTOCOL_REQUEST_ID_MISMATCH"):
        parse_and_validate_result(encode_line(valid_result), expected_request_id="different")
    with pytest.raises(IPCContractError, match="PROTOCOL_JOB_ID_MISMATCH"):
        parse_and_validate_result(encode_line(valid_result), expected_job_id="different")


@pytest.mark.parametrize("raw,code", [
    (b"{bad json}\n", "PROTOCOL_INVALID_JSON"),
    (b"\xff\n", "PROTOCOL_INVALID_UTF8"),
    (b"\n", "PROTOCOL_BLANK_LINE"),
    (b'{"a":1}', "PROTOCOL_TRUNCATED_LINE"),
    (b'{"a":1}\n{"b":2}\n', "PROTOCOL_MULTILINE_MESSAGE"),
    (b'[]\n', "PROTOCOL_OBJECT_REQUIRED"),
    (b'{"protocol_version":1,"protocol_version":1}\n', "PROTOCOL_DUPLICATE_KEY"),
    (b'{"x":NaN}\n', "PROTOCOL_NONFINITE_NUMBER"),
])
def test_strict_jsonl_framing_rejects_malformed_messages(raw, code):
    with pytest.raises(IPCContractError, match=code):
        parse_jsonl_message(raw)


def test_line_limit_is_enforced_before_json_parsing():
    with pytest.raises(IPCContractError, match="PROTOCOL_LINE_TOO_LARGE"):
        parse_jsonl_message(b" " * MAX_LINE_BYTES + b"\n")


@pytest.mark.parametrize("mutation", [
    lambda m: m.update(protocol_version=2),
    lambda m: m.update(message_type="other"),
    lambda m: m.update(engine_id="arbitrary"),
    lambda m: m.update(request_id="../escape"),
    lambda m: m.update(extra="not allowed"),
    lambda m: m.update(text="x\x00y"),
    lambda m: m.update(deadline_ms=True),
    lambda m: m["options"].update(speed=2.1),
    lambda m: m["options"].update(speed=True),
    lambda m: m["options"].update(unknown_option="x"),
    lambda m: m.update(reference_audio={"relative_path": "../../secret.wav", "media_type": "audio/wav"}),
    lambda m: m.update(reference_audio={"relative_path": "/tmp/secret.wav", "media_type": "audio/wav"}),
])
def test_request_schema_rejects_invalid_contracts(valid_request, mutation):
    mutation(valid_request)
    with pytest.raises(IPCContractError, match="PROTOCOL_(SCHEMA_INVALID|PATH_INVALID)"):
        validate_request(valid_request)


@pytest.mark.parametrize("status,output,error,valid", [
    ("ok", {"relative_path":"out.wav","format":"wav","sample_rate_hz":24000,"channels":1,"frame_count":10,"size_bytes":64}, None, True),
    ("ok", None, None, False),
    ("ok", {"relative_path":"../out.wav","format":"wav","sample_rate_hz":24000,"channels":1,"frame_count":10,"size_bytes":64}, None, False),
    ("error", None, {"code":"TIMEOUT","message":"deadline elapsed","retryable":True}, True),
    ("error", None, None, False),
    ("error", {"relative_path":"out.wav","format":"wav","sample_rate_hz":24000,"channels":1,"frame_count":10,"size_bytes":64}, {"code":"TIMEOUT","message":"x","retryable":True}, False),
    ("cancelled", None, None, True),
    ("cancelled", None, {"code":"CANCELLED","message":"cancelled","retryable":False}, False),
])
def test_result_status_invariants(valid_result, status, output, error, valid):
    valid_result.update(status=status, output=output, error=error)
    if valid:
        assert validate_result(valid_result)
    else:
        with pytest.raises(IPCContractError, match="PROTOCOL_(SCHEMA_INVALID|PATH_INVALID)"):
            validate_result(valid_result)


def test_reference_audio_requires_allowed_media_type_and_relative_path(valid_request):
    valid_request["reference_audio"] = {"relative_path":"inputs/ref.wav", "media_type":"audio/wav"}
    assert validate_request(valid_request)
    valid_request["reference_audio"]["media_type"] = "application/octet-stream"
    with pytest.raises(IPCContractError, match="PROTOCOL_SCHEMA_INVALID"):
        validate_request(valid_request)


@pytest.mark.parametrize("speed", [True, False, float("inf"), float("-inf"), float("nan")])
def test_speed_rejects_boolean_and_nonfinite_direct_python_values(valid_request, speed):
    valid_request["options"]["speed"] = speed
    with pytest.raises(IPCContractError):
        validate_request(valid_request)


@pytest.mark.parametrize("deadline", [True, False, 0, -1, 86400001, 1.5])
def test_deadline_rejects_boolean_and_out_of_range_values(valid_request, deadline):
    valid_request["deadline_ms"] = deadline
    with pytest.raises(IPCContractError):
        validate_request(valid_request)


@pytest.mark.parametrize("path", ["./output.wav", "output/./result.wav", "output//result.wav",
                                   "output/../secret.wav", "../secret.wav", "output\\result.wav",
                                   "/tmp/output.wav", "C:/output.wav", "output/", "output/   /result.wav"])
def test_result_rejects_noncanonical_relative_paths(valid_result, path):
    valid_result["output"]["relative_path"] = path
    with pytest.raises(IPCContractError):
        validate_result(valid_result)


def test_request_rejects_noncanonical_reference_path(valid_request):
    valid_request["reference_audio"] = {"relative_path": "./inputs/ref.wav", "media_type": "audio/wav"}
    with pytest.raises(IPCContractError, match="PROTOCOL_PATH_INVALID"):
        validate_request(valid_request)


def test_canonical_nested_posix_paths_remain_valid(valid_request, valid_result):
    valid_request["reference_audio"] = {"relative_path": "inputs/reference-01.wav", "media_type": "audio/wav"}
    valid_result["output"]["relative_path"] = "outputs/final_result.wav"
    assert validate_request(valid_request)
    assert validate_result(valid_result)


def test_line_size_boundary_accepts_exact_limit_when_payload_is_valid():
    # Construct a valid JSON object with ignorable whitespace padding to exactly the cap.
    base = b'{"a":1}'
    raw = base[:-1] + b" " * (MAX_LINE_BYTES - len(base) - 1) + b"}\n"
    assert len(raw) == MAX_LINE_BYTES
    assert parse_jsonl_message(raw) == {"a": 1}


@pytest.mark.parametrize("field,value", [
    ("sample_rate_hz", True), ("channels", True), ("frame_count", True), ("size_bytes", True),
])
def test_result_integer_fields_reject_booleans(valid_result, field, value):
    valid_result["output"][field] = value
    with pytest.raises(IPCContractError, match="PROTOCOL_SCHEMA_INVALID"):
        validate_result(valid_result)


def test_seed_rejects_boolean(valid_request):
    valid_request["options"]["seed"] = True
    with pytest.raises(IPCContractError, match="PROTOCOL_SCHEMA_INVALID"):
        validate_request(valid_request)


@pytest.mark.parametrize("mutation,expected_code", [
    (lambda m: m.update(protocol_version=2), "PROTOCOL_SCHEMA_INVALID"),
    (lambda m: m.update(deadline_ms=True), "PROTOCOL_SCHEMA_INVALID"),
    (lambda m: m["options"].update(speed=True), "PROTOCOL_SCHEMA_INVALID"),
    (lambda m: m.update(reference_audio={"relative_path": "../secret.wav", "media_type": "audio/wav"}), "PROTOCOL_PATH_INVALID"),
    (lambda m: m.update(unexpected=True), "PROTOCOL_SCHEMA_INVALID"),
])
def test_request_error_code_and_detail_match_parse_and_direct_validation(valid_request, mutation, expected_code):
    direct = copy.deepcopy(valid_request)
    mutation(direct)
    with pytest.raises(IPCContractError) as direct_error:
        validate_request(direct)
    with pytest.raises(IPCContractError) as parsed_error:
        parse_and_validate_request(json.dumps(direct, allow_nan=False).encode("utf-8") + b"\n")
    assert direct_error.value.code == parsed_error.value.code == expected_code
    assert direct_error.value.detail == parsed_error.value.detail
    assert str(direct_error.value) == str(parsed_error.value)


@pytest.mark.parametrize("mutation,expected_code", [
    (lambda m: m.update(status="unknown"), "PROTOCOL_SCHEMA_INVALID"),
    (lambda m: m["output"].update(sample_rate_hz=True), "PROTOCOL_SCHEMA_INVALID"),
    (lambda m: m["output"].update(relative_path="out//result.wav"), "PROTOCOL_PATH_INVALID"),
    (lambda m: m.update(extra="not allowed"), "PROTOCOL_SCHEMA_INVALID"),
])
def test_result_error_code_and_detail_match_parse_and_direct_validation(valid_result, mutation, expected_code):
    direct = copy.deepcopy(valid_result)
    mutation(direct)
    with pytest.raises(IPCContractError) as direct_error:
        validate_result(direct)
    with pytest.raises(IPCContractError) as parsed_error:
        parse_and_validate_result(json.dumps(direct, allow_nan=False).encode("utf-8") + b"\n")
    assert direct_error.value.code == parsed_error.value.code == expected_code
    assert direct_error.value.detail == parsed_error.value.detail
    assert str(direct_error.value) == str(parsed_error.value)


def test_protocol_error_exposes_machine_readable_code_and_detail():
    error = IPCContractError("PROTOCOL_SCHEMA_INVALID:options.speed")
    assert error.code == "PROTOCOL_SCHEMA_INVALID"
    assert error.detail == "options.speed"
    assert str(error) == "PROTOCOL_SCHEMA_INVALID:options.speed"


def test_protocol_error_without_detail_has_none_detail():
    error = IPCContractError("PROTOCOL_INVALID_JSON")
    assert error.code == "PROTOCOL_INVALID_JSON"
    assert error.detail is None


def test_nonfinite_numeric_error_is_classified_at_the_protocol_boundary(valid_request):
    valid_request["options"]["speed"] = float("nan")
    with pytest.raises(IPCContractError) as direct_error:
        validate_request(valid_request)
    assert direct_error.value.code == "PROTOCOL_SCHEMA_INVALID"
    raw = b'{"options":{"speed":NaN}}\n'
    with pytest.raises(IPCContractError) as parse_error:
        parse_and_validate_request(raw)
    assert parse_error.value.code == "PROTOCOL_NONFINITE_NUMBER"


# Versioned fixture contract: v1 is intentionally closed to unknown fields.
FIXTURE_DIR = SCHEMA_DIR.parent / "tests" / "fixtures" / "protocol-v1"

def read_fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))

def test_versioned_v1_fixtures_are_validated_through_public_entrypoints():
    request = read_fixture("valid-request.json")
    result = read_fixture("valid-result.json")
    assert validate_request(request) == request
    assert validate_result(result, expected_request_id="req_fixture_001", expected_job_id="job_fixture_001") == result
    assert parse_and_validate_request(encode_line(request)) == request
    assert parse_and_validate_result(encode_line(result)) == result

@pytest.mark.parametrize("name", [
    "invalid-request-unknown-field.json",
    "invalid-request-future-version.json",
])
def test_v1_rejects_unknown_fields_and_future_versions(name):
    with pytest.raises(IPCContractError) as exc:
        validate_request(read_fixture(name))
    assert exc.value.code == "PROTOCOL_SCHEMA_INVALID"

def test_protocol_version_boolean_is_not_integer_version_one(valid_request, valid_result):
    valid_request["protocol_version"] = True
    valid_result["protocol_version"] = True
    with pytest.raises(IPCContractError, match="PROTOCOL_SCHEMA_INVALID"):
        validate_request(valid_request)
    with pytest.raises(IPCContractError, match="PROTOCOL_SCHEMA_INVALID"):
        validate_result(valid_result)

def test_v1_fixture_policy_is_documented_and_fixture_files_exist():
    names = {p.name for p in FIXTURE_DIR.glob("*.json")}
    assert {"valid-request.json", "valid-result.json", "invalid-request-unknown-field.json", "invalid-request-future-version.json"} <= names
    readme = (SCHEMA_DIR.parent / "README.md").read_text(encoding="utf-8")
    assert "Protocol compatibility policy (D0-35)" in readme


def test_canonical_serialization_is_stable_across_mapping_insertion_order(valid_request):
    reversed_top = dict(reversed(list(valid_request.items())))
    reversed_top["options"] = dict(reversed(list(valid_request["options"].items())))
    assert canonical_jsonl_message(valid_request) == canonical_jsonl_message(reversed_top)


def test_canonical_serialization_uses_sorted_keys_compact_utf8_and_one_lf(valid_request):
    valid_request["text"] = "Héllo 🌍 — مرحبا\nsecond line"
    raw = canonical_jsonl_message(valid_request)
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert b"H\xc3\xa9llo \xf0\x9f\x8c\x8d" in raw
    assert b"\\nsecond line" in raw
    assert raw == canonical_jsonl_message(parse_and_validate_request(raw))
    assert raw.startswith(b'{"deadline_ms":30000,"engine_id":"kokoro"')


def test_canonical_serialization_rejects_invalid_protocol_and_nonfinite_values(valid_request):
    valid_request["options"]["speed"] = float("nan")
    with pytest.raises(IPCContractError):
        canonical_jsonl_message(valid_request)
    valid_request["options"]["speed"] = 1.0
    valid_request["unknown"] = "field"
    with pytest.raises(IPCContractError, match="PROTOCOL_SCHEMA_INVALID"):
        canonical_jsonl_message(valid_request)


def test_canonical_serialization_enforces_line_size_limit(valid_request):
    valid_request["text"] = "x" * 100000
    raw = canonical_jsonl_message(valid_request)
    assert len(raw) <= MAX_LINE_BYTES
    valid_request["text"] = "x" * 100000
    valid_request["trace_id"] = "t" * 64
    assert canonical_jsonl_message(valid_request).endswith(b"\n")


def test_valid_versioned_fixtures_have_canonical_round_trip_bytes():
    for name, validator in (("valid-request.json", validate_request), ("valid-result.json", validate_result)):
        value = read_fixture(name)
        raw = canonical_jsonl_message(value)
        parsed = parse_jsonl_message(raw)
        assert validator(parsed) == value
        assert canonical_jsonl_message(parsed) == raw
