"""Bound schema-validator work and keep consumer failures stable."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import audit_report_consumer as consumer
from audit_report_consumer import AuditReportContractError, UnsupportedAuditReportVersion

ROOT = Path(__file__).parents[1]
SCHEMA_PATH = ROOT / "schemas" / "evidence-bundle-audit-report-v1.schema.json"
FIXTURE = ROOT / "tests" / "fixtures" / "audit-report-consumer-v1.json"


def valid_report():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_schema_error_iteration_stops_at_cap_plus_one(monkeypatch):
    consumed = []

    class FakeValidator:
        FORMAT_CHECKER = object()

        @staticmethod
        def check_schema(schema):
            return None

        def __init__(self, schema, format_checker=None):
            pass

        def iter_errors(self, report):
            for index in range(10_000):
                consumed.append(index)
                yield SimpleNamespace(absolute_path=(str(index),), message="bad")

    monkeypatch.setattr(consumer, "Draft202012Validator", FakeValidator)
    with pytest.raises(AuditReportContractError, match="maximum schema validation error count"):
        consumer.validate_audit_report(valid_report(), SCHEMA_PATH)
    assert len(consumed) == consumer.MAX_SCHEMA_VALIDATION_ERRORS + 1


def test_schema_validation_error_cap_constant_is_documented_and_bounded():
    assert 1 <= consumer.MAX_SCHEMA_VALIDATION_ERRORS <= 1_000


def test_schema_setup_failure_has_stable_public_error(monkeypatch, tmp_path):
    bad_schema = tmp_path / "invalid.json"
    bad_schema.write_text("{ truncated", encoding="utf-8")
    with pytest.raises(AuditReportContractError) as error:
        consumer.validate_audit_report(valid_report(), bad_schema)
    assert str(error.value) == "audit report schema could not be loaded or validated"
    assert str(bad_schema) not in str(error.value)


def test_unsupported_version_fails_before_schema_io(tmp_path):
    report = valid_report()
    report["audit_report_schema_version"] = "999"
    with pytest.raises(UnsupportedAuditReportVersion, match="unsupported audit report schema version"):
        consumer.validate_audit_report(report, tmp_path / "missing-schema.json")
