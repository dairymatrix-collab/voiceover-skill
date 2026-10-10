"""Deterministic readiness checks for a real voiceover run.

Preflight never imports engine frameworks, downloads models, or claims inference works.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import platform
import shutil
import tempfile
from typing import Any

from tts_engine_adapters import probe_engines


@dataclass(frozen=True)
class Check:
    id: str
    status: str
    detail: str


@dataclass(frozen=True)
class PreflightReport:
    schema_version: int
    overall_status: str
    python_version: str
    platform: str
    checks: tuple[Check, ...]
    engines: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "overall_status": self.overall_status,
            "python_version": self.python_version,
            "platform": self.platform,
            "checks": [asdict(item) for item in self.checks],
            "engines": list(self.engines),
        }


def _check_writeable(path: Path) -> Check:
    try:
        path.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".voiceover-preflight-", dir=path)
        os.close(fd)
        Path(name).unlink()
        return Check("output_write", "PASS", "output directory can create and remove a temporary file")
    except OSError:
        return Check("output_write", "FAIL", "output directory is not writable")


def run_preflight(output_dir: str | Path, *, requested_engine: str | None = None,
                  require_gpu: bool = False) -> PreflightReport:
    checks: list[Check] = []
    out = Path(output_dir).expanduser()
    checks.append(_check_writeable(out))
    checks.append(Check("python", "PASS" if platform.python_version_tuple()[0] == "3" else "FAIL",
                        "Python " + platform.python_version()))
    import json
    try:
        json.dumps({"ok": True}, allow_nan=False)
        checks.append(Check("json_runtime", "PASS", "standard JSON runtime available"))
    except (TypeError, ValueError):
        checks.append(Check("json_runtime", "FAIL", "JSON runtime failed basic serialization"))
    if shutil.which("ffmpeg"):
        checks.append(Check("ffmpeg", "PASS", "ffmpeg executable found"))
    else:
        checks.append(Check("ffmpeg", "INFO", "ffmpeg not found; WAV-only assembly does not require it"))
    try:
        import torch
        cuda = bool(torch.cuda.is_available())
        mps_backend = getattr(getattr(torch, "backends", None), "mps", None)
        mps = bool(mps_backend and mps_backend.is_available())
        device = "cuda" if cuda else ("mps" if mps else "cpu")
        checks.append(Check("compute_device", "PASS" if (cuda or mps or not require_gpu) else "FAIL",
                            f"PyTorch available; detected device capability: {device}"))
    except (ImportError, AttributeError, RuntimeError):
        checks.append(Check("compute_device", "FAIL" if require_gpu else "INFO",
                            "PyTorch not installed or device detection unavailable"))
    engines = tuple(item.to_dict() for item in probe_engines())
    known_ids = {item["engine_id"] for item in engines}
    if requested_engine is not None:
        if requested_engine not in known_ids:
            checks.append(Check("requested_engine", "FAIL", "unknown engine ID"))
        else:
            selected = next(item for item in engines if item["engine_id"] == requested_engine)
            status = "PASS" if selected["package_available"] else "FAIL"
            checks.append(Check("requested_engine", status,
                                "optional package present" if status == "PASS" else "optional package missing"))
    status = "FAIL" if any(c.status == "FAIL" for c in checks) else (
        "READY_TO_ATTEMPT" if any(e["package_available"] for e in engines) else "BLOCKED_DEPENDENCIES")
    return PreflightReport(1, status, platform.python_version(), platform.platform(),
                           tuple(checks), engines)
