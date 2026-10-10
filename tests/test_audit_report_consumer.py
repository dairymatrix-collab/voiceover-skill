import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from audit_report_consumer import (
    AuditReportContractError,
    UnsupportedAuditReportVersion,
    diagnostics_by_code,
    validate_audit_report,
)

ROOT = Path(__file__).parents[1]
SCHEMA_PATH = ROOT / "schemas" / "evidence-bundle-audit-report-v1.schema.json"
CONTRACT_FIXTURE = ROOT / "tests" / "fixtures" / "audit-report-consumer-v1.json"


def test_versioned_consumer_fixture_validates_against_v1_schema():
    report = json.loads(CONTRACT_FIXTURE.read_text(encoding="utf-8"))
    validated = validate_audit_report(report, SCHEMA_PATH)
    assert validated is report
    Draft202012Validator(
        json.loads(SCHEMA_PATH.read_text(encoding="utf-8")),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    ).validate(report)


def test_consumer_rejects_unknown_or_missing_schema_version():
    report = json.loads(CONTRACT_FIXTURE.read_text(encoding="utf-8"))
    for version in ("2.0", "1.1", None):
        candidate = copy.deepcopy(report)
        if version is None:
            candidate.pop("audit_report_schema_version")
        else:
            candidate["audit_report_schema_version"] = version
        with pytest.raises(UnsupportedAuditReportVersion):
            validate_audit_report(candidate, SCHEMA_PATH)


def test_consumer_rejects_non_object_and_schema_drift():
    with pytest.raises(AuditReportContractError):
        validate_audit_report([], SCHEMA_PATH)
    report = json.loads(CONTRACT_FIXTURE.read_text(encoding="utf-8"))
    report["unexpected_field"] = True
    with pytest.raises(AuditReportContractError, match="violates schema"):
        validate_audit_report(report, SCHEMA_PATH)


def test_consumer_branches_on_stable_codes_not_prose_and_preserves_duplicates():
    report = json.loads(CONTRACT_FIXTURE.read_text(encoding="utf-8"))
    report["errors"].append(copy.deepcopy(report["errors"][0]))
    report["error_count"] = len(report["errors"])
    report["status"] = "FAIL"
    grouped = diagnostics_by_code(validate_audit_report(report, SCHEMA_PATH))
    assert len(grouped["BUNDLE_FILE_HASH_MISMATCH"]) == 2
    report["errors"][0]["message"] = "Human wording changed"
    grouped_after_copy_change = diagnostics_by_code(report)
    assert list(grouped_after_copy_change) == list(grouped)


def test_new_diagnostic_code_is_forward_compatible_within_v1_shape():
    report = json.loads(CONTRACT_FIXTURE.read_text(encoding="utf-8"))
    report["errors"][0]["code"] = "BUNDLE_NEW_DIAGNOSTIC_CODE"
    validated = validate_audit_report(report, SCHEMA_PATH)
    assert diagnostics_by_code(validated)["BUNDLE_NEW_DIAGNOSTIC_CODE"][0]["raw_message"]


def test_report_schema_has_explicit_version_and_closed_top_level_contract():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["properties"]["audit_report_schema_version"]["const"] == "1.0"
    assert schema["additionalProperties"] is False
    Draft202012Validator.check_schema(schema)
