"""D0-68: CLI output atomicity, failure cleanup, and stream/path parity."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_evidence_bundle import make_bundle
import scripts.verify_evidence_bundle as verifier

ROOT = Path(__file__).parents[1]
VERIFIER = ROOT / "scripts" / "verify_evidence_bundle.py"
CONSUMER = ROOT / "scripts" / "consume_audit_report.py"


def run_verifier(bundle: Path, *args):
    return subprocess.run(
        [sys.executable, str(VERIFIER), str(bundle), *map(str, args)],
        cwd=ROOT, capture_output=True, timeout=20,
    )


def run_consumer(raw: bytes, *args):
    return subprocess.run(
        [sys.executable, str(CONSUMER), *map(str, args)],
        cwd=ROOT, input=raw, capture_output=True, timeout=20,
    )


def temp_outputs(parent: Path, name: str) -> list[Path]:
    return list(parent.glob(f".{name}.*.tmp"))


def test_atomic_write_failure_preserves_existing_report_and_cleans_temp(tmp_path, monkeypatch, capsys):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    make_bundle(bundle)
    report = tmp_path / "audit.json"
    sentinel = b"PREVIOUS-VALID-REPORT\n"
    report.write_bytes(sentinel)

    def fail_replace(_source, _destination, **_kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(verifier.os, "replace", fail_replace)
    exit_code = verifier.main([str(bundle), "--json-report", str(report)])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert "could not write report (OSError)" in captured.err
    assert report.read_bytes() == sentinel
    assert temp_outputs(tmp_path, report.name) == []


def test_successful_atomic_write_replaces_destination_and_leaves_no_temp(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    make_bundle(bundle)
    report = tmp_path / "audit.json"
    report.write_text("stale content", encoding="utf-8")

    result = run_verifier(bundle, "--json-report", report)
    assert result.returncode == 0, result.stderr.decode()
    stdout_report = json.loads(result.stdout)
    assert json.loads(report.read_text(encoding="utf-8")) == stdout_report
    assert temp_outputs(tmp_path, report.name) == []


def test_destination_symlink_is_replaced_without_modifying_target(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    make_bundle(bundle)
    target = tmp_path / "target.json"
    target.write_bytes(b"TARGET-MUST-STAY-UNCHANGED")
    report_link = tmp_path / "audit.json"
    try:
        report_link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable in this environment")

    result = run_verifier(bundle, "--json-report", report_link)
    assert result.returncode == 0, result.stderr.decode()
    assert not report_link.is_symlink()
    assert json.loads(report_link.read_text(encoding="utf-8"))["status"] == "PASS"
    assert target.read_bytes() == b"TARGET-MUST-STAY-UNCHANGED"
    assert temp_outputs(tmp_path, report_link.name) == []


def test_parent_symlink_cannot_bypass_bundle_containment_check(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    make_bundle(bundle)
    alias = tmp_path / "bundle-alias"
    try:
        alias.symlink_to(bundle, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable in this environment")

    result = run_verifier(bundle, "--json-report", alias / "audit.json")
    assert result.returncode == 2
    assert b"outside the bundle" in result.stderr
    assert not (bundle / "audit.json").exists()
    assert temp_outputs(bundle, "audit.json") == []


@pytest.mark.parametrize(
    "raw,expected_code",
    [
        (b'{"audit_report_schema_version":"1.0",', b"AUDIT_REPORT_MALFORMED_JSON"),
        (b'\xff\xfe', b"AUDIT_REPORT_INVALID_UTF8"),
    ],
)
def test_stdin_and_file_input_have_identical_failure_contract(tmp_path, raw, expected_code):
    report_path = tmp_path / "input.json"
    report_path.write_bytes(raw)
    from_stdin = run_consumer(raw)
    from_file = subprocess.run(
        [sys.executable, str(CONSUMER), str(report_path)],
        cwd=ROOT, capture_output=True, timeout=20,
    )
    assert from_stdin.returncode == from_file.returncode == 2
    assert from_stdin.stdout == from_file.stdout == b""
    assert expected_code in from_stdin.stderr
    assert from_stdin.stderr == from_file.stderr


def test_consumer_directory_input_fails_without_success_output(tmp_path):
    result = subprocess.run(
        [sys.executable, str(CONSUMER), str(tmp_path)],
        cwd=ROOT, capture_output=True, timeout=20,
    )
    assert result.returncode == 2
    assert result.stdout == b""
    assert b"AUDIT_REPORT_INPUT_IO" in result.stderr
    assert str(tmp_path).encode() not in result.stderr


def test_consumer_oversized_file_and_stdin_have_same_stable_error(tmp_path, monkeypatch):
    # Lower the limit in an isolated interpreter without allocating a 5 MiB test
    # fixture; runpy preserves the actual CLI path and parser wiring.
    report_path = tmp_path / "oversized.json"
    report_path.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    from_stdin = run_consumer(report_path.read_bytes())
    from_file = subprocess.run(
        [sys.executable, str(CONSUMER), str(report_path)],
        cwd=ROOT, capture_output=True, timeout=20,
    )
    assert from_stdin.returncode == from_file.returncode == 2
    assert from_stdin.stdout == from_file.stdout == b""
    assert from_stdin.stderr == from_file.stderr == b"ERROR: AUDIT_REPORT_SIZE_LIMIT\n"
