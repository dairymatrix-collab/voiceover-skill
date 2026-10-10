"""Read-only diagnostics for acquiring a project-supported Python runtime.

This module never installs Python. It detects uv availability, inventories uv's
local cache at a high level, and optionally performs a bounded *offline-only*
uv acquisition probe. A failed probe is classified as unavailable-cache rather
than being confused with a successful runtime installation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

SUPPORTED = ((3, 10), (3, 11), (3, 12))
DEFAULT_TIMEOUT = 20.0
MAX_CACHE_FILES = 50_000


def _validate_version(version: str) -> tuple[int, int]:
    if not isinstance(version, str) or "\x00" in version:
        raise ValueError("version must be a string without NUL")
    parts = version.split(".")
    if len(parts) < 2 or any(not p.isdigit() for p in parts[:2]):
        raise ValueError("version must start with MAJOR.MINOR")
    result = (int(parts[0]), int(parts[1]))
    if result not in SUPPORTED:
        raise ValueError("version must be one of 3.10, 3.11, or 3.12")
    return result


def _uv_cache_dir() -> Path | None:
    value = os.environ.get("UV_CACHE_DIR")
    if value:
        return Path(value).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg).expanduser() / "uv"
    return Path.home() / ".cache" / "uv"


def inspect_uv(*, cache_dir: str | Path | None = None, max_files: int = MAX_CACHE_FILES) -> dict[str, Any]:
    if isinstance(max_files, bool) or not isinstance(max_files, int) or not 1 <= max_files <= MAX_CACHE_FILES:
        raise ValueError(f"max_files must be in [1, {MAX_CACHE_FILES}]")
    executable = shutil.which("uv")
    root = Path(cache_dir).expanduser() if cache_dir is not None else _uv_cache_dir()
    root = root.resolve()
    result: dict[str, Any] = {
        "uv_available": bool(executable),
        "uv_executable": str(Path(executable).resolve()) if executable else None,
        "cache_dir": str(root),
        "cache_dir_exists": root.is_dir(),
        "cache_file_count": 0,
        "cache_truncated": False,
    }
    if not root.is_dir():
        return result
    count = 0
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(current) / d).is_symlink()]
        count += sum(1 for name in files if not (Path(current) / name).is_symlink())
        if count >= max_files:
            result["cache_file_count"] = max_files
            result["cache_truncated"] = True
            return result
    result["cache_file_count"] = count
    return result


def offline_acquisition_probe(version: str = "3.12", *, timeout_seconds: float = DEFAULT_TIMEOUT,
                              uv_executable: str | None = None) -> dict[str, Any]:
    major_minor = _validate_version(version)
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 1 <= timeout_seconds <= 60:
        raise ValueError("timeout_seconds must be in [1, 60]")
    uv = uv_executable or shutil.which("uv")
    base = inspect_uv()
    report: dict[str, Any] = {
        "schema_version": 1,
        "diagnostic_only": True,
        "installation_performed": False,
        "runtime_acquired": False,
        "requested_version": f"{major_minor[0]}.{major_minor[1]}",
        **base,
        "status": "UV_UNAVAILABLE" if not uv else "NOT_PROBED",
    }
    if not uv:
        return report
    try:
        completed = subprocess.run(
            [uv, "python", "install", f"{major_minor[0]}.{major_minor[1]}", "--offline"],
            shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="replace", timeout=float(timeout_seconds), check=False,
            env={"PATH": os.environ.get("PATH", "")},
        )
    except subprocess.TimeoutExpired:
        report.update(status="OFFLINE_PROBE_TIMEOUT", detail="uv offline acquisition probe exceeded timeout")
        return report
    except OSError as exc:
        report.update(status="UV_LAUNCH_FAILED", detail=type(exc).__name__)
        return report
    report["probe_exit_code"] = completed.returncode
    stderr = completed.stderr[-500:].lower()
    if completed.returncode == 0:
        # --offline success is still not installation proof for this diagnostic: uv may
        # report an already-installed interpreter. Verify separately with discovery.
        report["status"] = "OFFLINE_RUNTIME_AVAILABLE"
        report["runtime_acquired"] = False
        return report
    if "wasn't found in the cache" in stderr or "network connectivity is disabled" in stderr:
        report["status"] = "OFFLINE_CACHE_MISS"
    else:
        report["status"] = "OFFLINE_PROBE_FAILED"
    return report


def collect_runtime_acquisition_report(*, versions: tuple[str, ...] = ("3.12", "3.11", "3.10"),
                                       timeout_seconds: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    if not versions:
        raise ValueError("versions must not be empty")
    probes = [offline_acquisition_probe(v, timeout_seconds=timeout_seconds) for v in versions]
    available = [p for p in probes if p["status"] == "OFFLINE_RUNTIME_AVAILABLE"]
    return {
        "schema_version": 1,
        "diagnostic_only": True,
        "installation_performed": False,
        "runtime_acquired": False,
        "status": "OFFLINE_RUNTIME_CANDIDATE" if available else "NO_OFFLINE_RUNTIME_AVAILABLE",
        "probes": probes,
    }
