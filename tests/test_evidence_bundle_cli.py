import json
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator

from test_evidence_bundle import make_bundle
from scripts.verify_evidence_bundle import make_report, report_exit_code

ROOT = Path(__file__).parents[1]
CLI = ROOT / "scripts" / "verify_evidence_bundle.py"
REPORT_SCHEMA = ROOT / "schemas" / "evidence-bundle-audit-report-v1.schema.json"


def run_cli(bundle: Path, *args, cwd: Path | None = None):
    return subprocess.run(
        [sys.executable, str(CLI), str(bundle), *map(str, args)],
        cwd=cwd, capture_output=True, text=True, timeout=15,
    )


def test_audit_report_schema_is_valid_and_closed():
    schema = json.loads(REPORT_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False


def test_cli_pass_report_is_machine_readable_and_explicit_about_authenticity(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    make_bundle(bundle)
    report_path = tmp_path / "audit.json"
    result = run_cli(bundle, "--json-report", report_path, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert json.loads(report_path.read_text(encoding="utf-8")) == report
    schema = json.loads(REPORT_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(report)
    assert report["status"] == "PASS"
    assert report["error_count"] == 0
    assert report["checks"]["cryptographic_authenticity"] == "NOT_ESTABLISHED"


def test_cli_fails_with_machine_readable_hash_error(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    make_bundle(bundle)
    (bundle / "payload" / "result.txt").write_text("changed", encoding="utf-8")
    result = run_cli(bundle)
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["status"] == "FAIL"
    assert report["error_count"] >= 1
    assert any("mismatch" in error["raw_message"] for error in report["errors"])
    assert any(error["code"] == "BUNDLE_FILE_HASH_MISMATCH" for error in report["errors"])
    assert all(error["remediation"] and error["category"] for error in report["errors"])


def test_cli_refuses_report_path_inside_verified_bundle(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    make_bundle(bundle)
    result = run_cli(bundle, "--json-report", bundle / "audit.json")
    assert result.returncode == 2
    assert "outside the bundle" in result.stderr
    assert not (bundle / "audit.json").exists()


def test_cli_missing_manifest_is_fail_not_success(tmp_path):
    bundle = tmp_path / "empty"
    bundle.mkdir()
    result = run_cli(bundle)
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["status"] == "FAIL"
    assert report["error_count"] == len(report["errors"]) > 0


def test_cli_report_output_failure_has_distinct_exit_code(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    make_bundle(bundle)
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("not a directory", encoding="utf-8")
    result = run_cli(bundle, "--json-report", blocked_parent / "audit.json")
    assert result.returncode == 2
    assert "could not write report" in result.stderr


def test_report_exit_code_contract_and_exact_error_cardinality(tmp_path):
    schema = json.loads(REPORT_SCHEMA.read_text(encoding="utf-8"))
    valid = tmp_path / "bundle"
    valid.mkdir()
    pass_report = make_report(valid, [])
    assert pass_report["status"] == "PASS"
    assert pass_report["error_count"] == len(pass_report["errors"]) == 0
    assert report_exit_code(pass_report) == 0
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(pass_report)

    fail_report = make_report(valid, ["size mismatch: a.wav", "SHA-256 mismatch: b.wav"])
    assert fail_report["status"] == "FAIL"
    assert fail_report["error_count"] == len(fail_report["errors"]) == 2
    assert report_exit_code(fail_report) == 1
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(fail_report)


def test_report_exit_code_rejects_status_or_count_drift():
    import pytest

    base = {"status": "PASS", "error_count": 0, "errors": []}
    assert report_exit_code(base) == 0
    for invalid in (
        {"status": "PASS", "error_count": 1, "errors": []},
        {"status": "FAIL", "error_count": 0, "errors": []},
        {"status": "FAIL", "error_count": 2, "errors": [{"code": "X"}]},
        {"status": "ERROR", "error_count": 1, "errors": [{"code": "X"}]},
    ):
        with pytest.raises(ValueError):
            report_exit_code(invalid)


def test_cli_usage_error_has_exit_two_and_no_json_report(tmp_path):
    result = subprocess.run(
        [sys.executable, str(CLI)], cwd=tmp_path,
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "usage:" in result.stderr.lower()


def test_report_write_error_has_exit_two_and_no_success_json(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    make_bundle(bundle)
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("not a directory", encoding="utf-8")
    result = run_cli(bundle, "--json-report", blocked_parent / "audit.json")
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("ERROR: could not write report")
