"""Cross-entry invariants and end-to-end reference-consumer integration simulation."""
import json
from pathlib import Path

import pytest

import audit_report_consumer as consumer

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "schemas" / "evidence-bundle-audit-report-v1.schema.json"
FIXTURE = ROOT / "tests" / "fixtures" / "audit-report-consumer-v1.json"


def report():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fail_report_consumption_maps_exit_and_groups_unknown_codes():
    item = report()
    item["errors"][0]["code"] = "FUTURE_VENDOR_DIAGNOSTIC"
    consumed = consumer.consume_audit_report_json(json.dumps(item), SCHEMA)
    assert consumed["status"] == "FAIL"
    assert consumed["exit_code"] == 1
    assert consumed["error_count"] == 1
    assert list(consumed["diagnostics_by_code"]) == ["FUTURE_VENDOR_DIAGNOSTIC"]
    assert len(consumed["diagnostics_by_code"]["FUTURE_VENDOR_DIAGNOSTIC"]) == 1


def test_pass_report_consumption_maps_to_zero_and_empty_groups():
    item = report()
    item["status"] = "PASS"
    item["checks"].update({
        "manifest_schema": "PASS",
        "file_inventory_and_hashes": "PASS",
        "envelope_payload_binding": "PASS",
    })
    item["error_count"] = 0
    item["errors"] = []
    consumed = consumer.consume_audit_report_json(json.dumps(item), SCHEMA)
    assert consumed == {"status": "PASS", "exit_code": 0, "error_count": 0, "diagnostics_by_code": {}}


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(error_count=0),
    lambda r: r.update(error_count=2),
])
def test_error_count_must_equal_errors_array_length(mutate):
    item = report()
    mutate(item)
    with pytest.raises(consumer.AuditReportContractError) as caught:
        consumer.validate_audit_report(item, SCHEMA)
    assert caught.value.code == "AUDIT_REPORT_INVARIANT_VIOLATION"


def test_fail_status_requires_check_that_points_to_errors():
    item = report()
    item["checks"].update({
        "manifest_schema": "PASS",
        "file_inventory_and_hashes": "PASS",
        "envelope_payload_binding": "PASS",
    })
    with pytest.raises(consumer.AuditReportContractError) as caught:
        consumer.validate_audit_report(item, SCHEMA)
    assert caught.value.code == "AUDIT_REPORT_INVARIANT_VIOLATION"


def test_error_status_requires_diagnostic_and_maps_to_exit_two():
    item = report()
    item["status"] = "ERROR"
    item["error_count"] = 0
    item["errors"] = []
    with pytest.raises(consumer.AuditReportContractError) as caught:
        consumer.validate_audit_report(item, SCHEMA)
    assert caught.value.code == "AUDIT_REPORT_INVARIANT_VIOLATION"

    item = report()
    item["status"] = "ERROR"
    consumed = consumer.consume_audit_report_json(json.dumps(item), SCHEMA)
    assert consumed["exit_code"] == 2


def test_integration_rejects_invalid_payload_before_returning_success():
    with pytest.raises(consumer.AuditReportContractError) as caught:
        consumer.consume_audit_report_json(b'{"audit_report_schema_version":"1.0",', SCHEMA)
    assert caught.value.code == "AUDIT_REPORT_MALFORMED_JSON"
