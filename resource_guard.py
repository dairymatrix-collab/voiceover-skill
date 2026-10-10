"""Conservative local resource gates and monitored subprocess execution.

RSS enforcement is polling-based, not an OS hard memory limit. Use OS/container
limits as an additional boundary where available; this module never claims a
sandbox or that a model fits merely because preflight passes.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence

from file_locking import FileLockError, exclusive_file_lock

MIB = 1024 * 1024
GIB = 1024 * MIB
MAX_CHILD_STDOUT_BYTES = 256 * 1024


@dataclass(frozen=True)
class ResourcePolicy:
    minimum_available_memory_mb: int
    maximum_process_tree_rss_mb: int
    minimum_free_disk_mb: int
    cpu_threads: int
    max_chunk_chars: int
    smoke_timeout_seconds: int


# Conservative starting budgets, not performance claims. Qwen's 14 GiB free
# RAM gate and 10 GiB RSS cap reflect the recorded local CPU trial plan.
ENGINE_POLICIES: dict[str, ResourcePolicy] = {
    "kokoro": ResourcePolicy(2048, 3072, 1024, 2, 1200, 120),
    "qwen3_tts": ResourcePolicy(14336, 10240, 8192, 2, 800, 300),
    "chatterbox": ResourcePolicy(8192, 6144, 6144, 2, 800, 300),
}


def _available_cpu_count() -> int | None:
    try:
        if hasattr(os, "sched_getaffinity"):
            return max(1, len(os.sched_getaffinity(0)))
    except (OSError, ValueError):
        pass
    try:
        count = os.cpu_count()
        return int(count) if count and count > 0 else None
    except (OSError, TypeError, ValueError):
        return None


def _default_model_cache() -> Path:
    try:
        from cache_paths import hf_hub_cache_path
        return hf_hub_cache_path()
    except (ImportError, OSError, RuntimeError, ValueError):
        return Path.home() / ".cache" / "huggingface" / "hub"


def _disk_free_bytes(path: str | Path | None) -> int | None:
    candidate = Path(path).expanduser() if path is not None else _default_model_cache()
    try:
        candidate = candidate.resolve(strict=False)
        while not candidate.exists() and candidate != candidate.parent:
            candidate = candidate.parent
        return int(shutil.disk_usage(candidate).free)
    except (OSError, RuntimeError, ValueError):
        return None


def process_tree_rss_bytes(pid: int) -> int | None:
    """Sum unique RSS of one process and descendants; return None if monitoring is unavailable."""
    try:
        import psutil
    except ImportError:
        return None
    try:
        root = psutil.Process(pid)
        processes = [root, *root.children(recursive=True)]
    except psutil.NoSuchProcess:
        return 0
    except (psutil.AccessDenied, OSError):
        return None
    total = 0
    seen: set[int] = set()
    for process in processes:
        if process.pid in seen:
            continue
        seen.add(process.pid)
        try:
            total += int(process.memory_info().rss)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    return total


def probe_system_resources() -> dict[str, Any]:
    """Read available RAM, current agent-process RSS and CPU visibility only."""
    cpu_count = _available_cpu_count()
    try:
        import psutil
    except ImportError:
        return {
            "monitor_available": False,
            "available_memory_bytes": None,
            "current_process_tree_rss_bytes": None,
            "available_cpu_count": cpu_count,
        }
    try:
        memory = int(psutil.virtual_memory().available)
        own_rss = process_tree_rss_bytes(os.getpid())
    except (psutil.Error, OSError, RuntimeError, ValueError):
        return {
            "monitor_available": False,
            "available_memory_bytes": None,
            "current_process_tree_rss_bytes": None,
            "available_cpu_count": cpu_count,
        }
    return {
        "monitor_available": own_rss is not None and memory >= 0,
        "available_memory_bytes": memory,
        "current_process_tree_rss_bytes": own_rss,
        "available_cpu_count": cpu_count,
    }


def _mb(value: int | None) -> int | None:
    return None if value is None else max(0, int(value) // MIB)


def resource_preflight(engine_id: str, *, model_root: str | Path | None = None) -> dict[str, Any]:
    """Return a read-only, schema-versioned resource decision without loading a model."""
    if not isinstance(engine_id, str) or engine_id not in ENGINE_POLICIES:
        raise ValueError("UNKNOWN_ENGINE")
    policy = ENGINE_POLICIES[engine_id]
    observed = probe_system_resources()
    disk = _disk_free_bytes(model_root)
    available_memory = observed.get("available_memory_bytes")
    available_cpus = observed.get("available_cpu_count")
    blockers: list[str] = []
    if not observed.get("monitor_available"):
        blockers.append("RESOURCE_MONITOR_UNAVAILABLE")
    if not isinstance(available_memory, int) or available_memory < policy.minimum_available_memory_mb * MIB:
        blockers.append("AVAILABLE_MEMORY_BELOW_MINIMUM")
    if not isinstance(disk, int) or disk < policy.minimum_free_disk_mb * MIB:
        blockers.append("FREE_DISK_BELOW_MINIMUM")
    if not isinstance(available_cpus, int) or available_cpus < 1:
        blockers.append("CPU_COUNT_UNAVAILABLE")
    return {
        "schema_version": 1,
        "engine_id": engine_id,
        "status": "READY_TO_ATTEMPT" if not blockers else "BLOCKED",
        "diagnostic_only": True,
        "installation_performed": False,
        "model_downloaded": False,
        "inference_verified": False,
        "limits": {
            "minimum_available_memory_mb": policy.minimum_available_memory_mb,
            "maximum_process_tree_rss_mb": policy.maximum_process_tree_rss_mb,
            "minimum_free_disk_mb": policy.minimum_free_disk_mb,
            "cpu_threads": policy.cpu_threads,
            "max_chunk_chars": policy.max_chunk_chars,
            "smoke_timeout_seconds": policy.smoke_timeout_seconds,
        },
        "observed": {
            "resource_monitor_available": bool(observed.get("monitor_available")),
            "available_memory_mb": _mb(available_memory),
            "current_process_tree_rss_mb": _mb(observed.get("current_process_tree_rss_bytes")),
            "free_disk_mb": _mb(disk),
            "available_cpu_count": available_cpus,
        },
        "blocking_reasons": blockers,
        "notes": [
            "A passing preflight does not prove that model weights are present, load, or synthesize audio.",
            "RSS limits are enforced by polling and may overshoot between samples; this is not an OS hard memory limit.",
        ],
    }


def thread_limited_environment(environment: Mapping[str, str], engine_id: str) -> dict[str, str]:
    """Return a copy with conservative BLAS/OpenMP/tokenizer thread caps."""
    if not isinstance(environment, Mapping):
        raise ValueError("ENVIRONMENT_INVALID")
    if not isinstance(engine_id, str) or engine_id not in ENGINE_POLICIES:
        raise ValueError("UNKNOWN_ENGINE")
    threads = str(ENGINE_POLICIES[engine_id].cpu_threads)
    result = dict(environment)
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS"):
        result[name] = threads
    result["TOKENIZERS_PARALLELISM"] = "false"
    return result


def _lock_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "voiceover-skill" / "locks"
    cache_home = os.environ.get("XDG_CACHE_HOME")
    return (Path(cache_home).expanduser() if cache_home else Path.home() / ".cache") / "voiceover-skill" / "locks"


def _terminate_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
        else:
            import psutil
            root = psutil.Process(process.pid)
            members = [*root.children(recursive=True), root]
            for member in members:
                try:
                    member.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            _, alive = psutil.wait_procs(members, timeout=0.5)
            for member in alive:
                try:
                    member.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def _json_error(code: str, detail: str | None = None, resource: dict[str, Any] | None = None) -> str:
    result: dict[str, Any] = {"ok": False, "error": code}
    if detail:
        result["detail"] = detail
    if resource:
        result["resource"] = resource
    return json.dumps(result, sort_keys=True, separators=(",", ":"))


def run_managed_process(argv: Sequence[str], *, input_text: str, timeout_seconds: float,
                        environment: Mapping[str, str], cwd: str | Path, engine_id: str,
                        model_root: str | Path | None = None, poll_interval_seconds: float = 0.25) -> subprocess.CompletedProcess:
    """Run one TTS worker under a local one-job lock, RAM/disk preflight and RSS/time monitor."""
    if (not isinstance(argv, (list, tuple)) or not argv or any(not isinstance(item, str) or "\x00" in item for item in argv)):
        raise ValueError("COMMAND_INVALID")
    if not isinstance(input_text, str) or len(input_text.encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("INPUT_TOO_LARGE")
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not 0.1 <= timeout_seconds <= 3600):
        raise ValueError("TIMEOUT_INVALID")
    if (isinstance(poll_interval_seconds, bool) or not isinstance(poll_interval_seconds, (int, float))
            or not 0.05 <= poll_interval_seconds <= 2.0):
        raise ValueError("POLL_INTERVAL_INVALID")
    if not isinstance(engine_id, str) or engine_id not in ENGINE_POLICIES:
        raise ValueError("UNKNOWN_ENGINE")
    if not isinstance(environment, Mapping) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in environment.items()):
        raise ValueError("ENVIRONMENT_INVALID")

    initial = resource_preflight(engine_id, model_root=model_root)
    if initial["status"] != "READY_TO_ATTEMPT":
        result = subprocess.CompletedProcess(list(argv), 75, _json_error("RESOURCE_PREFLIGHT_BLOCKED", ",".join(initial["blocking_reasons"]), initial), "")
        result.resource_report = {"preflight": initial, "peak_process_tree_rss_mb": None}
        return result

    lock_path = _lock_dir() / "tts-single-job.lock"
    policy = ENGINE_POLICIES[engine_id]
    try:
        with exclusive_file_lock(lock_path, timeout_seconds=0.0, busy_code="ENGINE_JOB_ALREADY_RUNNING"):
            # Recheck RAM after acquiring the global TTS-job lock.
            preflight = resource_preflight(engine_id, model_root=model_root)
            if preflight["status"] != "READY_TO_ATTEMPT":
                result = subprocess.CompletedProcess(list(argv), 75, _json_error("RESOURCE_PREFLIGHT_BLOCKED", ",".join(preflight["blocking_reasons"]), preflight), "")
                result.resource_report = {"preflight": preflight, "peak_process_tree_rss_mb": None}
                return result
            env = thread_limited_environment(environment, engine_id)
            started = time.monotonic()
            deadline = started + float(timeout_seconds)
            peak_rss = 0
            with tempfile.TemporaryFile() as stdout_file:
                try:
                    process = subprocess.Popen(
                        list(argv), stdin=subprocess.PIPE, stdout=stdout_file, stderr=subprocess.DEVNULL,
                        cwd=str(Path(cwd).resolve()), env=env, shell=False,
                        start_new_session=(os.name != "nt"), close_fds=True,
                    )
                except OSError as exc:
                    result = subprocess.CompletedProcess(list(argv), 127, _json_error("WORKER_LAUNCH_FAILED", type(exc).__name__), "")
                    result.resource_report = {"preflight": preflight, "peak_process_tree_rss_mb": None}
                    return result
                try:
                    assert process.stdin is not None
                    process.stdin.write(input_text.encode("utf-8"))
                    process.stdin.close()
                    while process.poll() is None:
                        current = process_tree_rss_bytes(process.pid)
                        if current is None:
                            _terminate_process_tree(process)
                            result = subprocess.CompletedProcess(list(argv), 75, _json_error("RESOURCE_MONITOR_FAILED"), "")
                            result.resource_report = {"preflight": preflight, "peak_process_tree_rss_mb": _mb(peak_rss)}
                            return result
                        peak_rss = max(peak_rss, current)
                        if current > policy.maximum_process_tree_rss_mb * MIB:
                            _terminate_process_tree(process)
                            observed = {"current_process_tree_rss_mb": _mb(current),
                                        "maximum_process_tree_rss_mb": policy.maximum_process_tree_rss_mb,
                                        "peak_process_tree_rss_mb": _mb(peak_rss)}
                            result = subprocess.CompletedProcess(list(argv), 137, _json_error("RESOURCE_LIMIT_EXCEEDED", "PROCESS_TREE_RSS_LIMIT", observed), "")
                            result.resource_report = {"preflight": preflight, "peak_process_tree_rss_mb": _mb(peak_rss)}
                            return result
                        if time.monotonic() >= deadline:
                            _terminate_process_tree(process)
                            timeout_error = subprocess.TimeoutExpired(list(argv), float(timeout_seconds))
                            timeout_error.resource_report = {
                                "preflight": preflight,
                                "peak_process_tree_rss_mb": _mb(peak_rss),
                                "maximum_process_tree_rss_mb": policy.maximum_process_tree_rss_mb,
                                "cpu_threads": min(policy.cpu_threads, preflight["observed"]["available_cpu_count"]),
                                "timeout_seconds": float(timeout_seconds),
                            }
                            raise timeout_error
                        time.sleep(float(poll_interval_seconds))
                    returncode = process.wait()
                    stdout_file.seek(0)
                    stdout_bytes = stdout_file.read(MAX_CHILD_STDOUT_BYTES + 1)
                    if len(stdout_bytes) > MAX_CHILD_STDOUT_BYTES:
                        result = subprocess.CompletedProcess(list(argv), 3, _json_error("WORKER_OUTPUT_TOO_LARGE"), "")
                    elif returncode < 0:
                        result = subprocess.CompletedProcess(list(argv), 128 + abs(returncode), _json_error("WORKER_SIGNAL_TERMINATED", f"signal={abs(returncode)}"), "")
                    else:
                        result = subprocess.CompletedProcess(list(argv), returncode, stdout_bytes.decode("utf-8", errors="replace"), "")
                    result.resource_report = {
                        "preflight": preflight,
                        "peak_process_tree_rss_mb": _mb(peak_rss),
                        "maximum_process_tree_rss_mb": policy.maximum_process_tree_rss_mb,
                        "cpu_threads": min(policy.cpu_threads, preflight["observed"]["available_cpu_count"]),
                        "timeout_seconds": float(timeout_seconds),
                    }
                    return result
                except BrokenPipeError:
                    _terminate_process_tree(process)
                    result = subprocess.CompletedProcess(list(argv), 3, _json_error("WORKER_INPUT_PIPE_FAILED"), "")
                    result.resource_report = {"preflight": preflight, "peak_process_tree_rss_mb": _mb(peak_rss)}
                    return result
                except subprocess.TimeoutExpired:
                    raise
                finally:
                    if process.poll() is None:
                        _terminate_process_tree(process)
    except FileLockError as exc:
        code = "ENGINE_JOB_ALREADY_RUNNING" if exc.code == "ENGINE_JOB_ALREADY_RUNNING" else "RESOURCE_LOCK_FAILED"
        result = subprocess.CompletedProcess(list(argv), 75, _json_error(code), "")
        result.resource_report = {"preflight": initial, "peak_process_tree_rss_mb": None}
        return result
