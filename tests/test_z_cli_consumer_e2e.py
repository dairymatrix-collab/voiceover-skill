"""Real subprocess workflows joining verifier CLI output to consumer CLI input."""
import json
from pathlib import Path
import subprocess
import sys

from test_evidence_bundle import make_bundle

ROOT = Path(__file__).parents[1]
VERIFIER = ROOT / "scripts" / "verify_evidence_bundle.py"
CONSUMER = ROOT / "scripts" / "consume_audit_report.py"


def run_verifier(bundle: Path, *args):
    return subprocess.run(
        [sys.executable, str(VERIFIER), str(bundle), *map(str, args)],
        cwd=ROOT, capture_output=True, timeout=15,
    )


def run_consumer(raw: bytes, *args):
    return subprocess.run(
        [sys.executable, str(CONSUMER), *map(str, args)],
        cwd=ROOT, input=raw, capture_output=True, timeout=15,
    )


def test_verifier_pass_json_flows_through_consumer_and_preserves_exit_status(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    make_bundle(bundle)
    producer = run_verifier(bundle)
    assert producer.returncode == 0, producer.stderr.decode()
    report = json.loads(producer.stdout)
    assert report["status"] == "PASS"

    consumer = run_consumer(producer.stdout)
    assert consumer.returncode == producer.returncode == 0, consumer.stderr.decode()
    result = json.loads(consumer.stdout)
    assert result == {"status": "PASS", "exit_code": 0, "error_count": 0, "diagnostics_by_code": {}}
    assert consumer.stderr == b""


def test_verifier_fail_json_flows_through_consumer_and_preserves_exit_status(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    make_bundle(bundle)
    (bundle / "payload" / "result.txt").write_bytes(b"tampered")
    producer = run_verifier(bundle)
    assert producer.returncode == 1
    report = json.loads(producer.stdout)
    assert report["status"] == "FAIL" and report["error_count"] > 0

    consumer = run_consumer(producer.stdout)
    assert consumer.returncode == producer.returncode == 1, consumer.stderr.decode()
    result = json.loads(consumer.stdout)
    assert result["status"] == "FAIL"
    assert result["exit_code"] == 1
    assert result["error_count"] == report["error_count"]
    assert sum(map(len, result["diagnostics_by_code"].values())) == result["error_count"]


def test_consumer_file_input_matches_stdin_input(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    make_bundle(bundle)
    producer = run_verifier(bundle)
    report_path = tmp_path / "report.json"
    report_path.write_bytes(producer.stdout)

    from_stdin = run_consumer(producer.stdout)
    from_file = subprocess.run(
        [sys.executable, str(CONSUMER), str(report_path)],
        cwd=ROOT, capture_output=True, timeout=15,
    )
    assert from_file.returncode == from_stdin.returncode == 0
    assert json.loads(from_file.stdout) == json.loads(from_stdin.stdout)


def test_invalid_report_fails_closed_without_json_success_output():
    result = run_consumer(b'{"audit_report_schema_version":"1.0",')
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr.strip() == b"ERROR: AUDIT_REPORT_MALFORMED_JSON"


def test_missing_input_file_has_stable_io_error_without_path_disclosure(tmp_path):
    missing = tmp_path / "secret-private-directory"
    missing.mkdir()
    result = subprocess.run(
        [sys.executable, str(CONSUMER), str(missing)],
        cwd=ROOT, capture_output=True, timeout=15,
    )
    assert result.returncode == 2
    assert result.stdout == b""
    assert b"AUDIT_REPORT_INPUT_IO" in result.stderr
    assert str(tmp_path).encode() not in result.stderr


def test_consumer_usage_error_is_exit_two_without_json():
    result = subprocess.run(
        [sys.executable, str(CONSUMER), "--unknown-option"],
        cwd=ROOT, capture_output=True, timeout=15,
    )
    assert result.returncode == 2
    assert result.stdout == b""
    assert b"usage:" in result.stderr.lower()
