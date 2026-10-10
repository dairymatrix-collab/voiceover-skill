import json
from pathlib import Path

import pytest

import audit_report_consumer as consumer
from audit_report_consumer import AuditReportContractError, parse_audit_report_json

ROOT = Path(__file__).parents[1]
SCHEMA_PATH = ROOT / "schemas" / "evidence-bundle-audit-report-v1.schema.json"
FIXTURE = ROOT / "tests" / "fixtures" / "audit-report-consumer-v1.json"


def valid_report():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parser_accepts_utf8_bytes_and_text():
    report = valid_report()
    assert parse_audit_report_json(json.dumps(report).encode(), SCHEMA_PATH) == report
    assert parse_audit_report_json(json.dumps(report), SCHEMA_PATH) == report


@pytest.mark.parametrize("raw", [b"", b"{", b'{"errors":', b'{"x":1,}', b"not json"])
def test_parser_rejects_malformed_or_truncated_json(raw):
    with pytest.raises(AuditReportContractError, match="malformed JSON"):
        parse_audit_report_json(raw, SCHEMA_PATH)


@pytest.mark.parametrize("raw", [b"\xff", b'{"x":"\xff"}'])
def test_parser_rejects_invalid_utf8(raw):
    with pytest.raises(AuditReportContractError, match="valid UTF-8"):
        parse_audit_report_json(raw, SCHEMA_PATH)


@pytest.mark.parametrize("raw", [b"[]", b"null", b"42", b'"text"'])
def test_parser_rejects_non_object_json(raw):
    with pytest.raises(AuditReportContractError, match="JSON object"):
        parse_audit_report_json(raw, SCHEMA_PATH)


def test_parser_rejects_duplicate_object_keys():
    with pytest.raises(AuditReportContractError, match="duplicate JSON object keys"):
        parse_audit_report_json(b'{"audit_report_schema_version":"1.0","audit_report_schema_version":"1.0"}', SCHEMA_PATH)


def test_report_size_limit_accepts_exact_boundary_and_rejects_one_over(monkeypatch):
    report = valid_report()
    raw = json.dumps(report).encode()
    monkeypatch.setattr(consumer, "MAX_REPORT_BYTES", len(raw))
    assert parse_audit_report_json(raw, SCHEMA_PATH)["audit_report_schema_version"] == "1.0"
    monkeypatch.setattr(consumer, "MAX_REPORT_BYTES", len(raw) - 1)
    with pytest.raises(AuditReportContractError, match="maximum allowed size"):
        parse_audit_report_json(raw, SCHEMA_PATH)


def test_diagnostic_limit_accepts_exact_boundary_and_rejects_one_over(monkeypatch):
    report = valid_report()
    diagnostic = report["errors"][0]
    report["errors"] = [diagnostic.copy() for _ in range(3)]
    report["error_count"] = 3
    report["status"] = "FAIL"
    monkeypatch.setattr(consumer, "MAX_DIAGNOSTICS", 3)
    assert parse_audit_report_json(json.dumps(report), SCHEMA_PATH)["error_count"] == 3
    report["errors"].append(diagnostic.copy())
    report["error_count"] = 4
    with pytest.raises(AuditReportContractError, match="maximum diagnostic count"):
        parse_audit_report_json(json.dumps(report), SCHEMA_PATH)


def test_broken_schema_path_has_generic_contract_error():
    with pytest.raises(AuditReportContractError, match="schema could not be loaded") as error:
        parse_audit_report_json(json.dumps(valid_report()), ROOT / "does-not-exist.schema.json")
    assert "does-not-exist" not in str(error.value)


@pytest.mark.parametrize("token", [b"NaN", b"Infinity", b"-Infinity"])
def test_parser_rejects_non_finite_json_tokens(token):
    raw = b'{"audit_report_schema_version":"1.0","value":' + token + b'}'
    with pytest.raises(AuditReportContractError, match="non-finite JSON number"):
        parse_audit_report_json(raw, SCHEMA_PATH)


def test_nesting_scanner_accepts_limit_and_rejects_one_over():
    consumer._check_json_nesting_depth('{"a":{"b":{}}}', maximum=3)
    with pytest.raises(AuditReportContractError, match="maximum JSON nesting depth"):
        consumer._check_json_nesting_depth('{"a":{"b":{"c":{}}}}', maximum=3)


def test_nesting_scanner_ignores_brackets_and_escaped_quotes_inside_strings():
    consumer._check_json_nesting_depth('{"text":"[ { \" ] }"}', maximum=1)


def test_deeply_nested_adversarial_input_fails_with_contract_error():
    raw = b"[" * 2000 + b"0" + b"]" * 2000
    with pytest.raises(AuditReportContractError, match="maximum JSON nesting depth"):
        parse_audit_report_json(raw, SCHEMA_PATH)
