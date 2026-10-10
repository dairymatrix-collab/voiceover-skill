"""D0-69: destination-race and atomic-report fault-injection regression tests."""
import json
import os
from pathlib import Path

import pytest

from test_evidence_bundle import make_bundle
import scripts.verify_evidence_bundle as verifier


def temps(parent: Path, name: str) -> list[Path]:
    return list(parent.glob(f".{name}.*.tmp"))


def test_destination_symlink_created_at_replace_race_is_not_followed(tmp_path, monkeypatch):
    """A symlink inserted after staging must be replaced as a link, not followed."""
    report = tmp_path / "audit.json"
    target = tmp_path / "target.json"
    target.write_bytes(b"DO-NOT-OVERWRITE")
    real_replace = verifier.os.replace
    raced = False

    def race_then_replace(source, destination, **kwargs):
        nonlocal raced
        if not raced:
            raced = True
            if kwargs.get("dst_dir_fd") is not None:
                os.symlink(target, destination, dir_fd=kwargs["dst_dir_fd"])
            else:
                Path(destination).symlink_to(target)
        return real_replace(source, destination, **kwargs)

    monkeypatch.setattr(verifier.os, "replace", race_then_replace)
    verifier._write_report_atomically(report, b'{"status":"PASS"}\n')

    assert raced
    assert not report.is_symlink()
    assert json.loads(report.read_text(encoding="utf-8")) == {"status": "PASS"}
    assert target.read_bytes() == b"DO-NOT-OVERWRITE"
    assert temps(tmp_path, report.name) == []


def test_parent_alias_swapped_after_destination_resolution_stays_on_resolved_parent(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    make_bundle(bundle)
    original_parent = tmp_path / "original-parent"
    attacker_parent = tmp_path / "attacker-parent"
    original_parent.mkdir()
    attacker_parent.mkdir()
    alias = tmp_path / "output-alias"
    try:
        alias.symlink_to(original_parent, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable in this environment")

    original_writer = verifier._write_report_atomically
    swapped = False

    def swap_alias_after_resolution(report_path, output):
        nonlocal swapped
        if not swapped:
            alias.unlink()
            alias.symlink_to(attacker_parent, target_is_directory=True)
            swapped = True
        return original_writer(report_path, output)

    monkeypatch.setattr(verifier, "_write_report_atomically", swap_alias_after_resolution)
    exit_code = verifier.main([str(bundle), "--json-report", str(alias / "audit.json")])

    assert exit_code == 0
    assert swapped
    assert json.loads((original_parent / "audit.json").read_text()) ["status"] == "PASS"
    assert not (attacker_parent / "audit.json").exists()
    assert temps(original_parent, "audit.json") == []
    assert temps(attacker_parent, "audit.json") == []


def test_fsync_failure_preserves_existing_report_and_removes_stage(tmp_path, monkeypatch):
    report = tmp_path / "audit.json"
    sentinel = b"PREVIOUS-REPORT"
    report.write_bytes(sentinel)

    def fail_fsync(_fd):
        raise OSError("injected fsync failure")

    monkeypatch.setattr(verifier.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="injected fsync failure"):
        verifier._write_report_atomically(report, b'{"status":"PASS"}\n')

    assert report.read_bytes() == sentinel
    assert temps(tmp_path, report.name) == []


def test_temp_creation_failure_preserves_existing_report_without_artifacts(tmp_path, monkeypatch):
    report = tmp_path / "audit.json"
    sentinel = b"PREVIOUS-REPORT"
    report.write_bytes(sentinel)

    real_open = verifier.os.open

    def fail_staging_open(path, flags, mode=0o777, *, dir_fd=None):
        if dir_fd is not None and str(path).startswith(f".{report.name}."):
            raise OSError("injected temp creation failure")
        return real_open(path, flags, mode, dir_fd=dir_fd) if dir_fd is not None else real_open(path, flags, mode)

    monkeypatch.setattr(verifier, "_supports_dirfd_atomic_replace", lambda: True)
    monkeypatch.setattr(verifier.os, "open", fail_staging_open)
    with pytest.raises(OSError, match="injected temp creation failure"):
        verifier._write_report_atomically(report, b"new report")

    assert report.read_bytes() == sentinel
    assert temps(tmp_path, report.name) == []


def test_write_failure_preserves_existing_report_and_removes_stage(tmp_path, monkeypatch):
    report = tmp_path / "audit.json"
    sentinel = b"PREVIOUS-REPORT"
    report.write_bytes(sentinel)
    real_fdopen = verifier.os.fdopen

    class FailingWriter:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.wrapped.close()
            return False

        def write(self, _data):
            raise OSError("injected write failure")

        def flush(self):
            return self.wrapped.flush()

        def fileno(self):
            return self.wrapped.fileno()

    monkeypatch.setattr(verifier.os, "fdopen", lambda fd, mode: FailingWriter(real_fdopen(fd, mode)))
    with pytest.raises(OSError, match="injected write failure"):
        verifier._write_report_atomically(report, b"new report")

    assert report.read_bytes() == sentinel
    assert temps(tmp_path, report.name) == []


def test_replace_failure_after_racing_destination_directory_preserves_directory(tmp_path, monkeypatch):
    report = tmp_path / "audit.json"
    report.mkdir()
    marker = report / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    real_replace = verifier.os.replace

    def fail_replace(source, destination, **_kwargs):
        assert Path(destination).name == report.name
        raise OSError("injected directory replacement failure")

    monkeypatch.setattr(verifier.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected directory replacement failure"):
        verifier._write_report_atomically(report, b"new report")

    assert report.is_dir()
    assert marker.read_text(encoding="utf-8") == "keep"
    assert temps(tmp_path, report.name) == []


def test_open_directory_fd_anchors_write_when_actual_parent_path_is_replaced(tmp_path, monkeypatch):
    """Renaming the opened directory and replacing its old path cannot redirect dirfd I/O."""
    parent = tmp_path / "parent"
    moved_parent = tmp_path / "parent-moved"
    attacker_parent = tmp_path / "attacker"
    parent.mkdir()
    attacker_parent.mkdir()
    report = parent / "audit.json"
    real_open = verifier.os.open
    swapped = False

    def open_then_swap(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        fd = real_open(path, flags, mode, dir_fd=dir_fd) if dir_fd is not None else real_open(path, flags, mode)
        if not swapped and dir_fd is None and Path(path) == parent and flags & getattr(os, "O_DIRECTORY", 0):
            parent.rename(moved_parent)
            parent.symlink_to(attacker_parent, target_is_directory=True)
            swapped = True
        return fd

    if not verifier._supports_dirfd_atomic_replace():
        pytest.skip("directory-fd atomic replacement is unsupported on this platform")
    monkeypatch.setattr(verifier, "_supports_dirfd_atomic_replace", lambda: True)
    monkeypatch.setattr(verifier.os, "open", open_then_swap)
    verifier._write_report_atomically(report, b'{"status":"PASS"}\n')

    assert swapped
    assert json.loads((moved_parent / "audit.json").read_text()) == {"status": "PASS"}
    assert not (attacker_parent / "audit.json").exists()
    assert temps(moved_parent, "audit.json") == []
    assert temps(attacker_parent, "audit.json") == []


def test_dirfd_replace_failure_preserves_previous_report_and_cleans_stage(tmp_path, monkeypatch):
    report = tmp_path / "audit.json"
    sentinel = b"PREVIOUS-REPORT"
    report.write_bytes(sentinel)

    def fail_replace(_source, _destination, **_kwargs):
        raise OSError("injected dirfd replacement failure")

    monkeypatch.setattr(verifier.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected dirfd replacement failure"):
        verifier._write_report_atomically(report, b"new report")

    assert report.read_bytes() == sentinel
    assert temps(tmp_path, report.name) == []


def test_unsupported_platform_uses_documented_path_fallback(tmp_path, monkeypatch):
    report = tmp_path / "audit.json"
    monkeypatch.setattr(verifier, "_supports_dirfd_atomic_replace", lambda: False)
    verifier._write_report_atomically(report, b'{"status":"PASS"}\n')
    assert json.loads(report.read_text()) == {"status": "PASS"}
    assert temps(tmp_path, report.name) == []
