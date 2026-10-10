"""D0-81..D0-90: fail-closed directory identity and atomic writer stress tests."""
import os
import threading
from pathlib import Path

import pytest

import scripts.verify_evidence_bundle as verifier


def _dirfd_supported():
    return verifier._supports_dirfd_atomic_replace()


def test_d0_81_parent_inode_swap_between_stat_and_open_fails_closed(tmp_path, monkeypatch):
    if not _dirfd_supported():
        pytest.skip("directory-fd atomic replacement unsupported")
    parent = tmp_path / "out"
    parent.mkdir()
    report = parent / "audit.json"
    report.write_bytes(b"previous")
    moved = tmp_path / "original-out"
    real_open = verifier.os.open
    swapped = False

    def swap_then_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if dir_fd is None and Path(path) == parent and flags & getattr(os, "O_DIRECTORY", 0) and not swapped:
            swapped = True
            parent.rename(moved)
            parent.mkdir()
        return real_open(path, flags, mode, dir_fd=dir_fd) if dir_fd is not None else real_open(path, flags, mode)

    monkeypatch.setattr(verifier.os, "open", swap_then_open)
    monkeypatch.setattr(verifier, "_supports_dirfd_atomic_replace", lambda: True)
    with pytest.raises(OSError, match="changed during open"):
        verifier._write_report_atomically(report, b"new")
    assert (moved / "audit.json").read_bytes() == b"previous"
    assert not (parent / "audit.json").exists()
    assert list(parent.iterdir()) == []


def test_d0_82_concurrent_writers_never_publish_torn_payload(tmp_path):
    report = tmp_path / "audit.json"
    payloads = [(str(i) * 100_000).encode() for i in range(8)]
    barrier = threading.Barrier(len(payloads))
    errors = []

    def writer(payload):
        try:
            barrier.wait(timeout=5)
            verifier._write_report_atomically(report, payload)
        except Exception as exc:  # collect worker failures for assertion in main thread
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(payload,)) for payload in payloads]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert report.read_bytes() in payloads
    assert list(tmp_path.glob(".audit.json.*.tmp")) == []


def test_d0_83_new_report_has_restrictive_mode_on_posix(tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX permission bits required")
    report = tmp_path / "audit.json"
    verifier._write_report_atomically(report, b"payload")
    assert report.stat().st_mode & 0o777 == 0o600


def test_d0_84_destination_symlink_target_is_not_overwritten(tmp_path):
    if os.name != "posix":
        pytest.skip("symlink semantics require POSIX")
    target = tmp_path / "target.txt"
    target.write_bytes(b"keep")
    report = tmp_path / "audit.json"
    report.symlink_to(target)
    verifier._write_report_atomically(report, b"new report")
    assert report.is_file() and not report.is_symlink()
    assert report.read_bytes() == b"new report"
    assert target.read_bytes() == b"keep"


def test_d0_85_existing_stage_name_collision_retries_safely(tmp_path, monkeypatch):
    if not _dirfd_supported():
        pytest.skip("directory-fd atomic replacement unsupported")
    tokens = iter(["collision", "fresh"])
    monkeypatch.setattr(verifier.secrets, "token_hex", lambda n: next(tokens))
    (tmp_path / ".audit.json.collision.tmp").write_bytes(b"attacker entry")
    report = tmp_path / "audit.json"
    verifier._write_report_atomically(report, b"complete")
    assert report.read_bytes() == b"complete"
    assert (tmp_path / ".audit.json.collision.tmp").read_bytes() == b"attacker entry"
    assert len(list(tmp_path.glob(".audit.json.*.tmp"))) == 1


def test_d0_86_stage_name_collision_exhaustion_fails_without_clobber(tmp_path, monkeypatch):
    if not _dirfd_supported():
        pytest.skip("directory-fd atomic replacement unsupported")
    report = tmp_path / "audit.json"
    report.write_bytes(b"previous")
    monkeypatch.setattr(verifier.secrets, "token_hex", lambda n: "same")
    collision = tmp_path / ".audit.json.same.tmp"
    collision.write_bytes(b"preserve")
    with pytest.raises(FileExistsError, match="unique report staging"):
        verifier._write_report_atomically(report, b"new")
    assert report.read_bytes() == b"previous"
    assert collision.read_bytes() == b"preserve"


def test_d0_87_fdopen_write_failure_preserves_previous_report(tmp_path, monkeypatch):
    report = tmp_path / "audit.json"
    report.write_bytes(b"previous")
    real_fdopen = verifier.os.fdopen

    class BrokenStream:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def write(self, data):
            raise OSError("injected write failure")
        def flush(self):
            return self.stream.flush()
        def fileno(self):
            return self.stream.fileno()

    monkeypatch.setattr(verifier.os, "fdopen", lambda *a, **k: BrokenStream(real_fdopen(*a, **k)))
    with pytest.raises(OSError, match="injected write failure"):
        verifier._write_report_atomically(report, b"new")
    assert report.read_bytes() == b"previous"
    assert list(tmp_path.glob(".audit.json.*.tmp")) == []


def test_d0_88_dirfd_replace_uses_same_source_and_destination_directory(tmp_path, monkeypatch):
    if not _dirfd_supported():
        pytest.skip("directory-fd atomic replacement unsupported")
    real_replace = verifier.os.replace
    calls = []

    def record_replace(src, dst, **kwargs):
        calls.append((src, dst, kwargs))
        return real_replace(src, dst, **kwargs)

    monkeypatch.setattr(verifier.os, "replace", record_replace)
    monkeypatch.setattr(verifier, "_supports_dirfd_atomic_replace", lambda: True)
    report = tmp_path / "audit.json"
    verifier._write_report_atomically(report, b"done")
    assert len(calls) == 1
    assert calls[0][1] == report.name
    assert calls[0][2]["src_dir_fd"] == calls[0][2]["dst_dir_fd"]


def test_d0_89_directory_destination_fails_without_stage_leak(tmp_path):
    report = tmp_path / "audit.json"
    report.mkdir()
    marker = report / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(OSError):
        verifier._write_report_atomically(report, b"replacement")
    assert marker.read_text(encoding="utf-8") == "keep"
    assert list(tmp_path.glob(".audit.json.*.tmp")) == []


def test_d0_90_randomized_atomic_replacement_round_trips_all_payloads(tmp_path):
    report = tmp_path / "audit.json"
    payloads = [bytes([i]) * (i * 257) for i in range(1, 24)]
    for payload in payloads:
        verifier._write_report_atomically(report, payload)
        assert report.read_bytes() == payload
        assert list(tmp_path.glob(".audit.json.*.tmp")) == []
