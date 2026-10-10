"""Mutation matrix and stable machine-readable failure taxonomy tests."""
import copy
import json
from pathlib import Path

import pytest

import audit_report_consumer as consumer

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "schemas" / "evidence-bundle-audit-report-v1.schema.json"
FIXTURE = ROOT / "tests" / "fixtures" / "audit-report-consumer-v1.json"


def valid_report():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("raw", "expected_code"),
    [
        (b"{", "AUDIT_REPORT_MALFORMED_JSON"),
        (b"\xff", "AUDIT_REPORT_INVALID_UTF8"),
        (b'{"x":1,"x":2}', "AUDIT_REPORT_DUPLICATE_KEYS"),
        (b'{"n":NaN}', "AUDIT_REPORT_NON_FINITE_NUMBER"),
        (b"[[[[0]]]]", "AUDIT_REPORT_INVALID_INPUT"),  # valid JSON, but not a report object
    ],
)
def test_parser_failure_taxonomy_is_stable(raw, expected_code):
    with pytest.raises(consumer.AuditReportContractError) as caught:
        consumer.parse_audit_report_json(raw, SCHEMA)
    assert caught.value.code == expected_code


def test_schema_version_failure_has_dedicated_stable_code(tmp_path):
    report = valid_report()
    report["audit_report_schema_version"] = "999"
    with pytest.raises(consumer.UnsupportedAuditReportVersion) as caught:
        consumer.validate_audit_report(report, tmp_path / "should-not-be-read.json")
    assert caught.value.code == "AUDIT_REPORT_UNSUPPORTED_VERSION"


@pytest.mark.parametrize(
    ("mutator", "path"),
    [
        (lambda r: r.update(unexpected_field=True), "top-level additional property"),
        (lambda r: r.update(status=17), "status type"),
        (lambda r: r.update(errors="not-an-array"), "errors type"),
        (lambda r: r["errors"][0].update(code=7), "diagnostic code type"),
        (lambda r: r.update(status="PASS", error_count=0), "PASS requires no errors"),
    ],
)
def test_schema_mutation_matrix_returns_same_schema_violation_code(mutator, path):
    report = copy.deepcopy(valid_report())
    mutator(report)
    with pytest.raises(consumer.AuditReportContractError) as caught:
        consumer.validate_audit_report(report, SCHEMA)
    assert caught.value.code == "AUDIT_REPORT_SCHEMA_VIOLATION", path


def test_resource_limit_failure_codes_are_machine_readable(monkeypatch):
    report = valid_report()
    raw = json.dumps(report).encode("utf-8")
    monkeypatch.setattr(consumer, "MAX_REPORT_BYTES", len(raw) - 1)
    with pytest.raises(consumer.AuditReportContractError) as too_large:
        consumer.parse_audit_report_json(raw, SCHEMA)
    assert too_large.value.code == "AUDIT_REPORT_SIZE_LIMIT"

    monkeypatch.setattr(consumer, "MAX_REPORT_BYTES", 5 * 1024 * 1024)
    monkeypatch.setattr(consumer, "MAX_DIAGNOSTICS", 0)
    with pytest.raises(consumer.AuditReportContractError) as too_many:
        consumer.validate_audit_report(report, SCHEMA)
    assert too_many.value.code == "AUDIT_REPORT_DIAGNOSTIC_LIMIT"


def test_schema_failure_and_error_amplification_have_distinct_codes(tmp_path, monkeypatch):
    with pytest.raises(consumer.AuditReportContractError) as schema_load:
        consumer.validate_audit_report(valid_report(), tmp_path / "missing.json")
    assert schema_load.value.code == "AUDIT_REPORT_SCHEMA_LOAD_FAILURE"

    class FakeValidator:
        FORMAT_CHECKER = object()

        @staticmethod
        def check_schema(schema):
            return None

        def __init__(self, schema, format_checker=None):
            pass

        def iter_errors(self, report):
            for i in range(consumer.MAX_SCHEMA_VALIDATION_ERRORS + 1):
                yield type("E", (), {"absolute_path": (str(i),), "message": "bad"})()

    monkeypatch.setattr(consumer, "Draft202012Validator", FakeValidator)
    with pytest.raises(consumer.AuditReportContractError) as error_cap:
        consumer.validate_audit_report(valid_report(), SCHEMA)
    assert error_cap.value.code == "AUDIT_REPORT_SCHEMA_ERROR_LIMIT"


def test_error_codes_are_unique_and_namespaced():
    values = [item.value for item in consumer.AuditReportErrorCode]
    assert len(values) == len(set(values))
    assert all(value.startswith("AUDIT_REPORT_") for value in values)


def test_nesting_limit_has_dedicated_stable_code(monkeypatch):
    monkeypatch.setattr(consumer, "MAX_JSON_NESTING_DEPTH", 2)
    with pytest.raises(consumer.AuditReportContractError) as caught:
        consumer.parse_audit_report_json(b'{"a":{"b":{}}}', SCHEMA)
    assert caught.value.code == "AUDIT_REPORT_NESTING_LIMIT"
