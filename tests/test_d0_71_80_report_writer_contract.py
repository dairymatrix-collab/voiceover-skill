"""D0-71..D0-80: report-writer portability, cleanup, and contract regressions."""
import inspect
import json
import os
from pathlib import Path

import pytest

import scripts.verify_evidence_bundle as verifier


def test_d0_71_dirfd_capability_requires_all_required_primitives(monkeypatch):
    if os.name != "posix":
        pytest.skip("current host is not POSIX")
    monkeypatch.setattr(os, "supports_dir_fd", set(os.supports_dir_fd) - {os.unlink})
    assert verifier._supports_dirfd_atomic_replace() is False


def test_d0_71_dirfd_capability_rejects_non_posix(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    assert verifier._supports_dirfd_atomic_replace() is False


def test_d0_71_dirfd_capability_rejects_replace_without_dirfd_signature(monkeypatch):
    def path_only_replace(src, dst):
        return None
    monkeypatch.setattr(verifier.os, "replace", path_only_replace)
    assert verifier._supports_dirfd_atomic_replace() is False


def test_d0_72_report_destination_rejects_bundle_and_descendants(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    with pytest.raises(ValueError, match="outside the bundle"):
        verifier._report_destination(bundle / "report.json", bundle)
    with pytest.raises(ValueError, match="outside the bundle"):
        verifier._report_destination(bundle / "inside" / "report.json", bundle)


def test_d0_72_report_destination_allows_sibling_and_preserves_final_name(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    requested = tmp_path / "outside" / "audit.json"
    resolved = verifier._report_destination(requested, bundle)
    assert resolved == requested.parent.resolve() / "audit.json"


def test_d0_73_supported_writer_opens_parent_with_directory_and_nofollow_flags(tmp_path, monkeypatch):
    if not verifier._supports_dirfd_atomic_replace():
        pytest.skip("directory-fd atomic replacement unsupported")
    report = tmp_path / "audit.json"
    real_open = verifier.os.open
    calls = []
    def record_open(path, flags, mode=0o777, *, dir_fd=None):
        calls.append((path, flags, dir_fd))
        if dir_fd is None and Path(path) == report.parent:
            assert flags & getattr(os, "O_DIRECTORY", 0)
            if getattr(os, "O_NOFOLLOW", 0):
                assert flags & os.O_NOFOLLOW
        return real_open(path, flags, mode, dir_fd=dir_fd) if dir_fd is not None else real_open(path, flags, mode)
    monkeypatch.setattr(verifier.os, "open", record_open)
    monkeypatch.setattr(verifier, "_supports_dirfd_atomic_replace", lambda: True)
    verifier._write_report_atomically(report, b'{"status":"PASS"}\n')
    assert report.exists()
    assert any(dir_fd is None and Path(path) == report.parent for path, _, dir_fd in calls)


def test_d0_73_stage_files_are_created_exclusively_with_restrictive_mode(tmp_path, monkeypatch):
    if not verifier._supports_dirfd_atomic_replace():
        pytest.skip("directory-fd atomic replacement unsupported")
    report = tmp_path / "audit.json"
    real_open = verifier.os.open
    stage = {}
    def inspect_open(path, flags, mode=0o777, *, dir_fd=None):
        if dir_fd is not None and str(path).startswith(".audit.json."):
            stage["flags"] = flags
            stage["mode"] = mode
        return real_open(path, flags, mode, dir_fd=dir_fd) if dir_fd is not None else real_open(path, flags, mode)
    monkeypatch.setattr(verifier.os, "open", inspect_open)
    monkeypatch.setattr(verifier, "_supports_dirfd_atomic_replace", lambda: True)
    verifier._write_report_atomically(report, b"ok")
    assert stage["flags"] & os.O_CREAT
    assert stage["flags"] & os.O_EXCL
    assert stage["mode"] == 0o600


def test_d0_74_directory_fd_closed_after_replace_failure(tmp_path, monkeypatch):
    if not verifier._supports_dirfd_atomic_replace():
        pytest.skip("directory-fd atomic replacement unsupported")
    report = tmp_path / "audit.json"
    real_close = verifier.os.close
    closed = []
    def record_close(fd):
        closed.append(fd)
        return real_close(fd)
    monkeypatch.setattr(verifier.os, "close", record_close)
    monkeypatch.setattr(verifier.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("replace fail")))
    with pytest.raises(OSError, match="replace fail"):
        verifier._write_report_atomically(report, b"new")
    assert closed, "directory descriptor should be closed in finally"
    assert list(tmp_path.glob(".audit.json.*.tmp")) == []


def test_d0_75_path_fallback_preserves_existing_file_on_replace_failure(tmp_path, monkeypatch):
    report = tmp_path / "audit.json"
    report.write_bytes(b"previous")
    monkeypatch.setattr(verifier, "_supports_dirfd_atomic_replace", lambda: False)
    monkeypatch.setattr(verifier.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("replace fail")))
    with pytest.raises(OSError, match="replace fail"):
        verifier._write_report_atomically(report, b"new")
    assert report.read_bytes() == b"previous"
    assert list(tmp_path.glob(".audit.json.*.tmp")) == []


def test_d0_76_successful_report_is_valid_utf8_json_with_terminal_newline(tmp_path):
    report = tmp_path / "audit.json"
    payload = '{"message":"café","status":"PASS"}\n'.encode("utf-8")
    verifier._write_report_atomically(report, payload)
    data = report.read_bytes()
    assert data == payload
    assert data.endswith(b"\n")
    assert json.loads(data.decode("utf-8"))["message"] == "café"


def test_d0_77_zero_length_payload_is_atomically_written(tmp_path):
    report = tmp_path / "audit.json"
    report.write_bytes(b"old")
    verifier._write_report_atomically(report, b"")
    assert report.read_bytes() == b""
    assert list(tmp_path.glob(".audit.json.*.tmp")) == []


def test_d0_78_failed_directory_open_does_not_create_staging_files(tmp_path, monkeypatch):
    report = tmp_path / "audit.json"
    real_open = verifier.os.open
    def fail_parent(path, flags, mode=0o777, *, dir_fd=None):
        if dir_fd is None and Path(path) == report.parent and flags & getattr(os, "O_DIRECTORY", 0):
            raise OSError("parent open fail")
        return real_open(path, flags, mode, dir_fd=dir_fd) if dir_fd is not None else real_open(path, flags, mode)
    if not verifier._supports_dirfd_atomic_replace():
        pytest.skip("directory-fd atomic replacement unsupported")
    monkeypatch.setattr(verifier.os, "open", fail_parent)
    monkeypatch.setattr(verifier, "_supports_dirfd_atomic_replace", lambda: True)
    with pytest.raises(OSError, match="parent open fail"):
        verifier._write_report_atomically(report, b"new")
    assert list(tmp_path.glob(".audit.json.*.tmp")) == []


def test_d0_79_path_fallback_success_leaves_no_staging_files(tmp_path, monkeypatch):
    report = tmp_path / "audit.json"
    monkeypatch.setattr(verifier, "_supports_dirfd_atomic_replace", lambda: False)
    verifier._write_report_atomically(report, b"fallback")
    assert report.read_bytes() == b"fallback"
    assert list(tmp_path.glob(".audit.json.*.tmp")) == []


def test_d0_80_writer_contract_documented_and_test_file_has_ten_task_labels():
    readme = (Path(verifier.__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert "Directory-FD anchored report writes (D0-70)" in readme
    assert "path-based fallback" in readme
    for task in range(71, 81):
        assert any(f"test_d0_{task}_" in line for line in Path(__file__).read_text(encoding="utf-8").splitlines())
