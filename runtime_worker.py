"""Model-free subprocess boundary for one JSONL synthesis request.

This is a reference supervisor, not an OS sandbox. The caller must pass a trusted
executable/argv and a dedicated working directory. POSIX workers are isolated into a
new session and their process group is terminated on failure; Windows tree cleanup uses
taskkill when available and requires platform-specific verification. OS resource/network
isolation remain deployment responsibilities.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time
from typing import Sequence

from ipc_contract import (
    IPCContractError, MAX_LINE_BYTES, canonical_jsonl_message,
    parse_and_validate_result,
)


@dataclass(frozen=True)
class WorkerOutcome:
    result: dict
    returncode: int
    stderr: str
    elapsed_seconds: float


class WorkerBoundaryError(RuntimeError):
    """Stable machine-readable worker-boundary failure."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}" + (f":{detail}" if detail else ""))
        self.code = code
        self.detail = detail


def _read_bounded(stream, limit: int, output: bytearray, overflow: threading.Event) -> None:
    try:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                return
            if len(output) + len(chunk) > limit:
                remaining = max(0, limit - len(output))
                output.extend(chunk[:remaining])
                overflow.set()
                return
            output.extend(chunk)
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _write_request(stream, payload: bytes, errors: queue.Queue) -> None:
    try:
        stream.write(payload)
        stream.flush()
    except (BrokenPipeError, OSError) as exc:
        errors.put(exc)
    finally:
        try:
            stream.close()
        except OSError:
            pass



def _terminate_process_tree(proc: subprocess.Popen, *, grace_seconds: float = 0.08) -> None:
    """Best-effort terminate a worker and descendants that share its process group.

    POSIX uses a new session/process group. Windows uses taskkill /T /F when available;
    if tree termination cannot be requested, the direct child is still killed.
    This is lifecycle cleanup, not a security boundary against descendants that escape
    the process group/session.
    """
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except OSError:
            try:
                proc.kill()
            except OSError:
                pass
            return
        # Give cooperative descendants a short grace period, then ensure the group is gone.
        time.sleep(max(0.0, grace_seconds))
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            try:
                proc.kill()
            except OSError:
                pass
        return

    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=2.0, check=False, shell=False,
            )
            if completed.returncode == 0:
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def run_worker(
    command: Sequence[str],
    request: dict,
    *,
    timeout_seconds: float = 30.0,
    cancel_event: threading.Event | None = None,
    cwd: str | Path | None = None,
    max_stdout_bytes: int = MAX_LINE_BYTES,
    max_stderr_bytes: int = 64 * 1024,
) -> WorkerOutcome:
    """Run one trusted argv command and validate its single terminal result.

    No shell is used. stdout and stderr are drained concurrently and bounded;
    cancellation/timeout/output overflow terminate the worker process group on POSIX.
    Windows uses taskkill tree cleanup as a best-effort path; that path requires Windows CI.
    """
    if not isinstance(command, (list, tuple)) or not command or any(
        not isinstance(arg, str) or not arg or "\x00" in arg for arg in command
    ):
        raise WorkerBoundaryError("WORKER_INVALID_COMMAND")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise WorkerBoundaryError("WORKER_INVALID_TIMEOUT")
    if isinstance(max_stdout_bytes, bool) or not isinstance(max_stdout_bytes, int) or max_stdout_bytes < 1:
        raise WorkerBoundaryError("WORKER_INVALID_OUTPUT_LIMIT")
    if isinstance(max_stderr_bytes, bool) or not isinstance(max_stderr_bytes, int) or max_stderr_bytes < 0:
        raise WorkerBoundaryError("WORKER_INVALID_OUTPUT_LIMIT")
    try:
        payload = canonical_jsonl_message(request)
    except IPCContractError as exc:
        raise WorkerBoundaryError("WORKER_INVALID_REQUEST", exc.code) from exc
    if cwd is not None and not Path(cwd).is_dir():
        raise WorkerBoundaryError("WORKER_INVALID_CWD")

    started = time.monotonic()
    safe_env = {"PATH": os.defpath, "PYTHONIOENCODING": "utf-8"}
    if os.name == "nt" and os.environ.get("SYSTEMROOT"):
        safe_env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    try:
        proc = subprocess.Popen(
            list(command), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(cwd) if cwd is not None else None, env=safe_env, shell=False,
            close_fds=True, bufsize=0,
            start_new_session=(os.name == "posix"),
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0),
        )
    except (OSError, ValueError) as exc:
        raise WorkerBoundaryError("WORKER_START_FAILED", type(exc).__name__) from exc

    stdout = bytearray()
    stderr = bytearray()
    overflow = threading.Event()
    writer_errors: queue.Queue = queue.Queue()
    threads = [
        threading.Thread(target=_read_bounded, args=(proc.stdout, max_stdout_bytes, stdout, overflow), daemon=True, name="voiceover-worker-stdout"),
        threading.Thread(target=_read_bounded, args=(proc.stderr, max_stderr_bytes, stderr, overflow), daemon=True, name="voiceover-worker-stderr"),
        threading.Thread(target=_write_request, args=(proc.stdin, payload, writer_errors), daemon=True, name="voiceover-worker-stdin"),
    ]
    for thread in threads:
        thread.start()

    failure: str | None = None
    deadline = started + float(timeout_seconds)
    while proc.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            failure = "WORKER_CANCELLED"
            break
        if overflow.is_set():
            failure = "WORKER_OUTPUT_LIMIT"
            break
        if time.monotonic() >= deadline:
            failure = "WORKER_TIMEOUT"
            break
        time.sleep(0.005)

    if failure is not None:
        _terminate_process_tree(proc)
    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(proc)
        proc.wait(timeout=2.0)

    # A worker may exit while a descendant keeps inherited pipes open. Detect that case,
    # terminate the remaining group, and then give the bounded reader threads time to close.
    for thread in threads:
        thread.join(timeout=0.25)
    if any(thread.is_alive() for thread in threads):
        _terminate_process_tree(proc)
        for thread in threads:
            thread.join(timeout=1.0)
    if any(thread.is_alive() for thread in threads):
        raise WorkerBoundaryError("WORKER_IO_THREAD_STUCK")
    if failure:
        raise WorkerBoundaryError(failure)
    if overflow.is_set():
        raise WorkerBoundaryError("WORKER_OUTPUT_LIMIT")
    if proc.returncode != 0:
        raise WorkerBoundaryError("WORKER_NONZERO_EXIT", str(proc.returncode))
    if not stdout.endswith(b"\n") or stdout.count(b"\n") != 1:
        raise WorkerBoundaryError("WORKER_INVALID_STDOUT_FRAMING")
    try:
        result = parse_and_validate_result(
            bytes(stdout), expected_request_id=request["request_id"], expected_job_id=request["job_id"]
        )
    except (IPCContractError, KeyError) as exc:
        code = exc.code if isinstance(exc, IPCContractError) else "WORKER_INVALID_REQUEST"
        raise WorkerBoundaryError("WORKER_INVALID_RESULT", code) from exc
    return WorkerOutcome(
        result=result, returncode=proc.returncode,
        stderr=bytes(stderr).decode("utf-8", errors="replace"),
        elapsed_seconds=time.monotonic() - started,
    )
