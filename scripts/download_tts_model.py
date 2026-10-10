#!/usr/bin/env python3
"""Plan or explicitly acquire one pinned TTS model under local resource gates.

The downloader accepts only the reviewed model catalog; it never accepts an
arbitrary repository, branch, URL, token, or unrestricted file pattern.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import fnmatch
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cache_paths import hf_hub_cache_path
from resource_guard import ENGINE_POLICIES, MIB, resource_preflight, run_managed_process
from tts_artifact_readiness import write_report_atomic
from tts_model_catalog import ModelSpec, get_model_spec

MAX_WORKER_INPUT_BYTES = 16 * 1024
MAX_SNAPSHOT_FILES = 128
_DISK_HEADROOM_FRACTION = 0.25
SUPPORTED_MODEL_TARGETS = frozenset({("kokoro", "preset"), ("qwen3_tts", "voice_design")})
_SAFE_ENV_NAMES = (
    "PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
)


class DownloadValidationError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def normalize_cache_dir(value: str | Path | None = None) -> Path:
    """Resolve the effective Hub cache; reject NULs, final symlinks and files."""
    raw = hf_hub_cache_path() if value is None else Path(value).expanduser()
    if "\x00" in os.fspath(raw):
        raise ValueError("CACHE_DIR_INVALID")
    try:
        if raw.exists() and raw.is_symlink():
            raise ValueError("CACHE_DIR_SYMLINK")
        resolved = raw.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValueError("CACHE_DIR_INVALID") from exc
    if resolved.exists() and not resolved.is_dir():
        raise ValueError("CACHE_DIR_NOT_DIRECTORY")
    return resolved


def _nearest_existing(path: Path) -> Path:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def _free_disk_bytes(path: Path) -> int | None:
    try:
        return int(shutil.disk_usage(_nearest_existing(path)).free)
    except (OSError, RuntimeError, ValueError):
        return None


def required_free_bytes(spec: ModelSpec) -> int:
    policy = ENGINE_POLICIES[spec.engine_id]
    minimum = policy.minimum_free_disk_mb * MIB
    reserve = int(spec.max_download_bytes * _DISK_HEADROOM_FRACTION)
    return minimum + spec.max_download_bytes + reserve


def _safe_worker_environment(cache_dir: Path) -> dict[str, str]:
    """Pass only non-secret execution/cache/network settings to the worker."""
    env = {name: os.environ[name] for name in _SAFE_ENV_NAMES if name in os.environ}
    env["HOME"] = os.environ.get("HOME", str(Path.home()))
    env["HF_HUB_CACHE"] = str(cache_dir)
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    env["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    # Deliberately do not forward HF_TOKEN, HUGGINGFACE_HUB_TOKEN, API keys,
    # arbitrary Python path overrides, or unrelated process environment values.
    return env


def _allowed_path(relative: str, spec: ModelSpec) -> bool:
    return any(fnmatch.fnmatchcase(relative, pattern) for pattern in spec.allow_patterns)


def verify_snapshot(snapshot_path: str | Path, cache_dir: str | Path,
                    spec: ModelSpec) -> dict[str, Any]:
    """Verify a pinned cache snapshot, required files, path containment and size cap."""
    try:
        cache = Path(cache_dir).expanduser().resolve(strict=True)
        snapshot = Path(snapshot_path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise DownloadValidationError("SNAPSHOT_NOT_FOUND") from exc
    if not cache.is_dir() or not _is_within(snapshot, cache):
        raise DownloadValidationError("SNAPSHOT_PATH_UNSAFE")
    if not snapshot.is_dir() or snapshot.name != spec.revision:
        raise DownloadValidationError("SNAPSHOT_REVISION_MISMATCH")

    files: list[dict[str, Any]] = []
    relative_files: set[str] = set()
    total = 0
    for current, directories, names in os.walk(snapshot, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in list(directories):
            child = current_path / name
            if child.is_symlink():
                raise DownloadValidationError("SNAPSHOT_DIRECTORY_SYMLINK")
        directories.sort()
        names.sort()
        for name in names:
            candidate = current_path / name
            relative = candidate.relative_to(snapshot).as_posix()
            if not _allowed_path(relative, spec):
                raise DownloadValidationError("SNAPSHOT_CONTAINS_UNALLOWLISTED_FILE")
            try:
                resolved = candidate.resolve(strict=True)
                if not _is_within(resolved, cache):
                    raise DownloadValidationError("SNAPSHOT_FILE_ESCAPES_CACHE")
                info = resolved.stat()
            except DownloadValidationError:
                raise
            except (OSError, RuntimeError, ValueError) as exc:
                raise DownloadValidationError("SNAPSHOT_FILE_UNREADABLE") from exc
            if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
                raise DownloadValidationError("SNAPSHOT_FILE_INVALID")
            expected_size = spec.expected_file_size_map.get(relative)
            if expected_size is not None and info.st_size != expected_size:
                raise DownloadValidationError("SNAPSHOT_FILE_SIZE_MISMATCH")
            total += int(info.st_size)
            if total > spec.max_download_bytes:
                raise DownloadValidationError("MODEL_SIZE_LIMIT_EXCEEDED")
            relative_files.add(relative)
            files.append({"path": relative, "size_bytes": int(info.st_size),
                          "is_symlink_in_snapshot": candidate.is_symlink()})
            if len(files) > MAX_SNAPSHOT_FILES:
                raise DownloadValidationError("SNAPSHOT_FILE_COUNT_LIMIT_EXCEEDED")

    missing = [relative for relative in spec.required_files if relative not in relative_files]
    if missing:
        raise DownloadValidationError("SNAPSHOT_REQUIRED_FILES_MISSING")
    for pattern in spec.required_patterns:
        if not any(fnmatch.fnmatchcase(relative, pattern) for relative in relative_files):
            raise DownloadValidationError("SNAPSHOT_REQUIRED_PATTERN_MISSING")
    if not files:
        raise DownloadValidationError("SNAPSHOT_EMPTY")
    return {
        "snapshot_path": str(snapshot),
        "resolved_revision": snapshot.name,
        "actual_bytes": total,
        "file_count": len(files),
        "files": files,
        "hub_integrity": "huggingface_hub_download_verified; full-file hashes not recomputed locally",
    }


def _worker_download(engine_id: str, variant: str, cache_dir: Path) -> dict[str, Any]:
    """Download one pinned, allowlisted snapshot. Called only in monitored child."""
    if (engine_id, variant) not in SUPPORTED_MODEL_TARGETS:
        raise DownloadValidationError("MODEL_PATH_NOT_VERIFIED")
    spec = get_model_spec(engine_id, variant)
    cache_dir.mkdir(parents=True, exist_ok=True)
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    revision_arg = "main" if spec.uses_main_ref else spec.revision
    already_present = False
    snapshot: str | None = None
    try:
        snapshot = snapshot_download(
            repo_id=spec.model_id,
            revision=revision_arg,
            allow_patterns=list(spec.allow_patterns),
            cache_dir=str(cache_dir),
            max_workers=1,
            local_files_only=True,
        )
        # The library may return a cached but incomplete snapshot. Verify before
        # treating it as complete; a missing set is eligible for a bounded resume.
        verify_snapshot(snapshot, cache_dir, spec)
        already_present = True
    except LocalEntryNotFoundError:
        snapshot = None
    except DownloadValidationError as exc:
        if exc.code not in {"SNAPSHOT_REQUIRED_FILES_MISSING", "SNAPSHOT_REQUIRED_PATTERN_MISSING"}:
            raise
        snapshot = None

    if snapshot is None:
        snapshot = snapshot_download(
            repo_id=spec.model_id,
            revision=revision_arg,
            allow_patterns=list(spec.allow_patterns),
            cache_dir=str(cache_dir),
            max_workers=1,
            local_files_only=False,
        )
    # For Kokoro, KPipeline resolves the cached `main` ref. Require it to equal
    # the audited commit, rather than silently accepting a moved default branch.
    result = verify_snapshot(snapshot, cache_dir, spec)
    return {"ok": True, "already_present": already_present, **result}


def _worker_main() -> int:
    raw = sys.stdin.buffer.read(MAX_WORKER_INPUT_BYTES + 1)
    if len(raw) > MAX_WORKER_INPUT_BYTES:
        print(json.dumps({"ok": False, "error": "WORKER_INPUT_TOO_LARGE"}, separators=(",", ":")))
        return 2
    try:
        payload = json.loads(raw.decode("utf-8"))
        if (not isinstance(payload, dict) or set(payload) != {"engine_id", "variant", "cache_dir"}
                or any(not isinstance(payload[key], str) for key in payload)):
            raise ValueError("WORKER_INPUT_INVALID")
        cache_dir = normalize_cache_dir(payload["cache_dir"])
        with redirect_stdout(sys.stderr):
            result = _worker_download(payload["engine_id"], payload["variant"], cache_dir)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
        return 0
    except ImportError:
        result = {"ok": False, "error": "MODEL_DOWNLOAD_DEPENDENCY_MISSING"}
    except DownloadValidationError as exc:
        result = {"ok": False, "error": exc.code}
    except ValueError as exc:
        result = {"ok": False, "error": str(exc) if str(exc).isupper() else "WORKER_INPUT_INVALID"}
    except Exception as exc:
        result = {"ok": False, "error": "MODEL_DOWNLOAD_FAILED", "detail_type": type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 1


def _base_report(spec: ModelSpec, cache_dir: Path, *, requested: bool,
                 preflight: dict[str, Any], free_disk: int | None) -> dict[str, Any]:
    expected = sum(size for _, size in spec.expected_file_sizes) or None
    return {
        "schema_version": 1,
        "status": "PLAN_ONLY",
        "engine_id": spec.engine_id,
        "model_variant": spec.variant,
        "model_id": spec.model_id,
        "pinned_revision": spec.revision,
        "download_ref": "main (validated against pinned revision)" if spec.uses_main_ref else spec.revision,
        "license": spec.license,
        "cache_dir": str(cache_dir),
        "download_requested": requested,
        "installation_performed": False,
        "model_downloaded": False,
        "inference_verified": False,
        "allow_patterns": list(spec.allow_patterns),
        "required_files": list(spec.required_files),
        "expected_file_bytes": expected,
        "maximum_download_bytes": spec.max_download_bytes,
        "minimum_free_disk_bytes": required_free_bytes(spec),
        "observed_free_disk_bytes": free_disk,
        "resource_preflight": preflight,
        "blocking_reasons": [],
        "peak_process_tree_rss_mb": None,
        "elapsed_ms": 0,
        "files": [],
        "sources": list(spec.sources),
        "notes": [
            "Plan mode performs no installation, network request, directory creation, or model load.",
            "An explicit --download is required; downloads use a fixed repository, immutable revision, file allowlist, one worker, process-tree RSS monitor, timeout, and shared one-job lock.",
            "A completed download is artifact evidence only; it does not verify model loading or CPU inference.",
        ],
    }


def _run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    try:
        if (args.engine, args.variant or {"kokoro": "preset", "qwen3_tts": "voice_design"}.get(args.engine)) not in SUPPORTED_MODEL_TARGETS:
            raise ValueError("MODEL_PATH_NOT_VERIFIED")
        spec = get_model_spec(args.engine, args.variant)
        cache_dir = normalize_cache_dir(args.cache_dir)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if isinstance(args.timeout_seconds, bool) or not 1 <= args.timeout_seconds <= 3600:
        raise ValueError("TIMEOUT_INVALID")

    preflight = resource_preflight(spec.engine_id, model_root=cache_dir)
    free_disk = _free_disk_bytes(cache_dir)
    report = _base_report(spec, cache_dir, requested=args.download,
                          preflight=preflight, free_disk=free_disk)
    blockers = list(preflight.get("blocking_reasons", []))
    needed = report["minimum_free_disk_bytes"]
    if free_disk is None:
        blockers.append("DOWNLOAD_FREE_DISK_UNKNOWN")
    elif free_disk < needed:
        blockers.append("DOWNLOAD_DISK_HEADROOM_BELOW_MINIMUM")
    if blockers:
        report.update(status="BLOCKED_RESOURCE", blocking_reasons=sorted(set(blockers)))
        return report, 3
    if not args.download:
        return report, 0

    python = str(Path(args.python).expanduser()) if os.path.sep in args.python else shutil.which(args.python)
    if not python or not Path(python).is_file():
        report.update(status="DOWNLOAD_FAILED", blocking_reasons=["WORKER_PYTHON_NOT_FOUND"])
        return report, 2

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        report.update(status="DOWNLOAD_FAILED", blocking_reasons=["CACHE_DIR_NOT_WRITABLE"])
        return report, 2

    payload = json.dumps({"engine_id": spec.engine_id, "variant": spec.variant,
                          "cache_dir": str(cache_dir)}, separators=(",", ":"))
    argv = [python, str(Path(__file__).resolve()), "--_worker",
            "--engine", spec.engine_id, "--variant", spec.variant]
    started = time.monotonic()
    try:
        child = run_managed_process(
            argv,
            input_text=payload,
            timeout_seconds=float(args.timeout_seconds),
            environment=_safe_worker_environment(cache_dir),
            cwd=ROOT,
            engine_id=spec.engine_id,
            model_root=cache_dir,
        )
    except subprocess.TimeoutExpired as exc:
        detail = getattr(exc, "resource_report", {})
        report.update(status="DOWNLOAD_TIMEOUT", elapsed_ms=int((time.monotonic() - started) * 1000),
                      peak_process_tree_rss_mb=detail.get("peak_process_tree_rss_mb"),
                      blocking_reasons=["DOWNLOAD_TIMEOUT"])
        return report, 3
    report["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    report["peak_process_tree_rss_mb"] = getattr(child, "resource_report", {}).get("peak_process_tree_rss_mb")
    try:
        child_report = json.loads(child.stdout.strip())
    except (AttributeError, json.JSONDecodeError, TypeError):
        child_report = {"ok": False, "error": "WORKER_PROTOCOL_INVALID"}
    if child.returncode == 0 and isinstance(child_report, dict) and child_report.get("ok") is True:
        report.update(
            status="ALREADY_AVAILABLE" if child_report.get("already_present") else "DOWNLOADED",
            model_downloaded=True,
            snapshot_path=child_report.get("snapshot_path"),
            resolved_revision=child_report.get("resolved_revision"),
            downloaded_bytes=child_report.get("actual_bytes"),
            file_count=child_report.get("file_count"),
            files=child_report.get("files", []),
            hub_integrity=child_report.get("hub_integrity"),
            blocking_reasons=[],
        )
        return report, 0
    error = child_report.get("error", "MODEL_DOWNLOAD_FAILED") if isinstance(child_report, dict) else "MODEL_DOWNLOAD_FAILED"
    if error in {"RESOURCE_PREFLIGHT_BLOCKED", "RESOURCE_LIMIT_EXCEEDED", "RESOURCE_MONITOR_FAILED",
                 "ENGINE_JOB_ALREADY_RUNNING", "RESOURCE_LOCK_FAILED"}:
        status = "BLOCKED_RESOURCE"
    else:
        status = "DOWNLOAD_FAILED"
    report.update(status=status, blocking_reasons=[str(error)[:96]])
    return report, 3 if status == "BLOCKED_RESOURCE" else 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan or explicitly download one pinned TTS model under resource and file-size gates."
    )
    parser.add_argument("--engine", required=True, choices=("qwen3_tts", "kokoro"))
    parser.add_argument("--variant", help="profile model variant; defaults to the engine's safest primary variant")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--download", action="store_true", help="explicitly download the pinned allowlisted files")
    mode.add_argument("--plan-only", action="store_true", help="default: preflight/plan only, no downloads")
    parser.add_argument("--cache-dir", help="Hugging Face Hub cache directory; defaults to configured HF cache")
    parser.add_argument("--python", default=sys.executable,
                        help="Python executable for the isolated engine environment (default: current Python)")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if args._worker:
        return _worker_main()
    try:
        report, code = _run(args)
        if args.report:
            write_report_atomic(args.report, report, protected_root=Path(report["cache_dir"]))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2 if args.pretty else None,
                     allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
