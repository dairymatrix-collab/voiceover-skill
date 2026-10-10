"""D0-91..D0-100: CLI/path integration and atomic-writer boundary contracts."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import scripts.verify_evidence_bundle as verifier

ROOT = Path(__file__).resolve().parents[1]


def test_d0_91_relative_destination_is_anchored_to_resolved_cwd(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.chdir(out)
    resolved = verifier._report_destination(Path("audit.json"), bundle.resolve())
    assert resolved == out.resolve() / "audit.json"


def test_d0_92_parent_symlink_is_resolved_before_bundle_containment_check(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    alias = tmp_path / "bundle-alias"
    try:
        alias.symlink_to(bundle, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink unavailable")
    with pytest.raises(ValueError, match="outside the bundle"):
        verifier._report_destination(alias / "report.json", bundle.resolve())


def test_d0_93_missing_parent_is_created_and_report_is_private(tmp_path):
    report = tmp_path / "new" / "nested" / "audit.json"
    verifier._write_report_atomically(report, b"payload\n")
    assert report.read_bytes() == b"payload\n"
    assert not list(report.parent.glob(f".{report.name}.*.tmp"))
    if os.name == "posix":
        assert report.stat().st_mode & 0o777 == 0o600


def test_d0_94_replacing_existing_broad_mode_report_installs_private_inode(tmp_path):
    report = tmp_path / "audit.json"
    report.write_bytes(b"old")
    if os.name == "posix":
        report.chmod(0o644)
    old_inode = report.stat().st_ino
    verifier._write_report_atomically(report, b"new")
    assert report.read_bytes() == b"new"
    if os.name == "posix":
        assert report.stat().st_mode & 0o777 == 0o600
        assert report.stat().st_ino != old_inode


def test_d0_95_fsync_failure_preserves_previous_report_and_cleans_stage(tmp_path, monkeypatch):
    report = tmp_path / "audit.json"
    report.write_bytes(b"previous")
    def fail_fsync(_fd):
        raise OSError("injected fsync failure")
    monkeypatch.setattr(verifier.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="fsync"):
        verifier._write_report_atomically(report, b"new")
    assert report.read_bytes() == b"previous"
    assert list(tmp_path.glob(".audit.json.*.tmp")) == []


def test_d0_96_fallback_fdopen_failure_closes_descriptor_and_removes_stage(tmp_path, monkeypatch):
    monkeypatch.setattr(verifier, "_supports_dirfd_atomic_replace", lambda: False)
    report = tmp_path / "audit.json"
    report.write_bytes(b"previous")
    real_fdopen = verifier.os.fdopen
    opened_fd = None
    real_mkstemp = verifier.tempfile.mkstemp
    def capture_mkstemp(*args, **kwargs):
        nonlocal opened_fd
        opened_fd, name = real_mkstemp(*args, **kwargs)
        return opened_fd, name
    def fail_fdopen(*args, **kwargs):
        raise OSError("injected fdopen failure")
    monkeypatch.setattr(verifier.tempfile, "mkstemp", capture_mkstemp)
    monkeypatch.setattr(verifier.os, "fdopen", fail_fdopen)
    with pytest.raises(OSError, match="fdopen"):
        verifier._write_report_atomically(report, b"new")
    assert report.read_bytes() == b"previous"
    assert list(tmp_path.glob(".audit.json.*.tmp")) == []
    with pytest.raises(OSError):
        os.fstat(opened_fd)
    monkeypatch.setattr(verifier.os, "fdopen", real_fdopen)


def test_d0_97_fallback_replaces_final_symlink_entry_without_touching_target(tmp_path, monkeypatch):
    monkeypatch.setattr(verifier, "_supports_dirfd_atomic_replace", lambda: False)
    target = tmp_path / "target"
    target.write_bytes(b"keep")
    report = tmp_path / "audit.json"
    try:
        report.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unavailable")
    verifier._write_report_atomically(report, b"new")
    assert not report.is_symlink()
    assert report.read_bytes() == b"new"
    assert target.read_bytes() == b"keep"


def test_d0_98_cli_rejects_report_destination_inside_bundle(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    report = bundle / "audit.json"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_evidence_bundle.py"), str(bundle), "--json-report", str(report)],
        cwd=ROOT, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 2
    assert "outside the bundle" in proc.stderr
    assert not report.exists()


def test_d0_99_cli_stdout_and_written_report_are_identical_canonical_json(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    report = tmp_path / "audit.json"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_evidence_bundle.py"), str(bundle), "--json-report", str(report)],
        cwd=ROOT, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 1  # empty bundle is a verification failure, not a CLI error
    assert proc.stdout.endswith("\n")
    assert json.loads(proc.stdout) == json.loads(report.read_text(encoding="utf-8"))
    assert proc.stdout == report.read_text(encoding="utf-8")


def test_d0_100_report_write_failure_is_cli_error_and_does_not_claim_success(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    report = bundle / "nested" / "audit.json"  # rejected before attempting write
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_evidence_bundle.py"), str(bundle), "--json-report", str(report)],
        cwd=ROOT, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert "outside the bundle" in proc.stderr
