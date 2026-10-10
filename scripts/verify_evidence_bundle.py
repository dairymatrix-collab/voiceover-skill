#!/usr/bin/env python3
"""Verify a provenance evidence bundle and emit a machine-readable audit report.

Exit codes: 0=integrity checks passed, 1=bundle failed verification,
2=CLI/report-output error. A PASS establishes local consistency only, not authorship.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import secrets
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evidence_bundle import MANIFEST_NAME, verify_evidence_bundle  # noqa: E402
from audit_diagnostics import classify_errors  # noqa: E402

REPORT_SCHEMA_VERSION = "1.0"


def make_report(bundle: Path, errors: list[str]) -> dict:
    """Build a report whose status and count are derived only from its errors."""
    resolved = bundle.resolve()
    diagnostics = classify_errors(errors)
    return {
        "audit_report_schema_version": REPORT_SCHEMA_VERSION,
        "verifier": {"name": "voiceover-evidence-bundle-verifier", "version": "1.0"},
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "bundle_path": str(resolved),
        "manifest_name": MANIFEST_NAME,
        "status": "PASS" if not diagnostics else "FAIL",
        "checks": {
            "manifest_schema": "PASS" if not errors else "SEE_ERRORS",
            "file_inventory_and_hashes": "PASS" if not errors else "SEE_ERRORS",
            "envelope_payload_binding": "PASS" if not errors else "SEE_ERRORS",
            "cryptographic_authenticity": "NOT_ESTABLISHED",
        },
        "error_count": len(diagnostics),
        "errors": diagnostics,
        "limitations": [
            "PASS means local bundle consistency only; it does not authenticate the manifest author.",
            "SHA-256 hashes detect changes only relative to a trusted digest or manifest.",
            "No digital signature, trusted timestamp, external verifier, provider inference, or OS sandbox is exercised by this CLI.",
        ],
    }


def report_exit_code(report: dict) -> int:
    """Enforce the public report/exit-code contract before returning to callers."""
    errors = report.get("errors")
    count = report.get("error_count")
    status = report.get("status")
    if not isinstance(errors, list) or not isinstance(count, int) or isinstance(count, bool):
        raise ValueError("audit report has invalid errors/error_count fields")
    if count != len(errors):
        raise ValueError("audit report error_count does not match errors length")
    if status == "PASS" and count == 0:
        return 0
    if status == "FAIL" and count > 0:
        return 1
    raise ValueError("audit report status is inconsistent with error_count")


def canonical_report(report: dict) -> bytes:
    return (json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _report_destination(requested_path: Path, bundle: Path) -> Path:
    """Canonicalize the parent but not the final path component.

    This keeps containment checks correct through parent-directory symlinks while
    ensuring an existing destination symlink is replaced as a directory entry,
    rather than followed and used to overwrite its target.
    """
    parent = requested_path.parent.resolve()
    report_path = parent / requested_path.name
    if report_path == bundle or report_path.is_relative_to(bundle):
        raise ValueError("report path must be outside the bundle being verified")
    return report_path


def _supports_dirfd_atomic_replace() -> bool:
    """Return whether this runtime exposes the POSIX primitives we need."""
    if os.name != "posix":
        return False
    if not all(fn in os.supports_dir_fd for fn in (os.open, os.unlink, os.rename)):
        return False
    # os.replace accepts src_dir_fd/dst_dir_fd on platforms where os.rename's
    # dir_fd support is exposed; verify the call signature rather than assuming.
    try:
        import inspect
        params = inspect.signature(os.replace).parameters
    except (TypeError, ValueError):
        return False
    return "src_dir_fd" in params and "dst_dir_fd" in params


def _write_report_atomically(report_path: Path, output: bytes) -> None:
    """Atomically replace a report, anchoring POSIX operations to an opened directory.

    On supported POSIX systems, temp creation, replacement and cleanup are
    relative to the same directory file descriptor. Renaming/replacing the
    parent path after it is opened therefore cannot redirect the write. Other
    platforms use a same-directory path-based fallback with weaker race
    resistance; neither path promises durability across every filesystem or
    power-loss scenario.
    """
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if not _supports_dirfd_atomic_replace():
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{report_path.name}.", suffix=".tmp", dir=report_path.parent
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(output)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, report_path)
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return

    # Record the intended directory identity before opening it. The descriptor
    # must refer to that same inode; otherwise fail closed rather than silently
    # writing into a replacement directory installed between stat and open.
    expected_parent = os.stat(report_path.parent, follow_symlinks=False)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(report_path.parent, flags)
    try:
        opened_parent = os.fstat(directory_fd)
        if (opened_parent.st_dev, opened_parent.st_ino) != (expected_parent.st_dev, expected_parent.st_ino):
            raise OSError("report parent directory changed during open")
    except BaseException:
        os.close(directory_fd)
        raise
    temporary_name = None
    file_fd = None
    try:
        # O_EXCL plus unpredictable names avoids clobbering attacker-created entries.
        for _ in range(32):
            candidate = f".{report_path.name}.{secrets.token_hex(12)}.tmp"
            try:
                file_fd = os.open(
                    candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600, dir_fd=directory_fd,
                )
                temporary_name = candidate
                break
            except FileExistsError:
                continue
        if file_fd is None or temporary_name is None:
            raise FileExistsError("could not allocate a unique report staging file")
        with os.fdopen(file_fd, "wb") as stream:
            file_fd = None  # fdopen now owns the descriptor
            stream.write(output)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(
            temporary_name, report_path.name,
            src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
        )
        temporary_name = None
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="bundle directory containing evidence-bundle-manifest-v1.json")
    parser.add_argument("--json-report", type=Path, help="also write report JSON to a path outside the bundle")
    args = parser.parse_args(argv)
    bundle = args.bundle.resolve()
    errors = verify_evidence_bundle(bundle)
    report = make_report(bundle, errors)
    try:
        exit_code = report_exit_code(report)
    except ValueError as exc:
        print(f"ERROR: internal audit report consistency failure ({type(exc).__name__})", file=sys.stderr)
        return 2
    output = canonical_report(report)
    if args.json_report is not None:
        try:
            report_path = _report_destination(args.json_report, bundle)
            _write_report_atomically(report_path, output)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        except OSError as exc:
            print(f"ERROR: could not write report ({type(exc).__name__})", file=sys.stderr)
            return 2
    sys.stdout.buffer.write(output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
