from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from runtime_worker import WorkerBoundaryError, run_worker

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "protocol-v1"
REQUEST = json.loads((FIXTURE_DIR / "valid-request.json").read_text(encoding="utf-8"))
RESULT = json.loads((FIXTURE_DIR / "valid-result.json").read_text(encoding="utf-8"))


def worker_command(body: str):
    return [sys.executable, "-c", body]


def result_emitter(result=None, delay=0):
    payload = json.dumps(result or RESULT, separators=(",", ":"))
    return worker_command(
        "import sys,time; data=sys.stdin.readline(); "
        f"time.sleep({delay!r}); sys.stdout.write({payload!r}+'\\n'); sys.stdout.flush()"
    )


def test_worker_runs_one_request_and_validates_correlated_result():
    outcome = run_worker(result_emitter(), REQUEST, timeout_seconds=2)
    assert outcome.result["request_id"] == REQUEST["request_id"]
    assert outcome.result["job_id"] == REQUEST["job_id"]
    assert outcome.returncode == 0
    assert outcome.elapsed_seconds >= 0


def test_worker_rejects_invalid_request_before_process_launch():
    bad = dict(REQUEST, engine_id="unknown")
    with pytest.raises(WorkerBoundaryError, match="WORKER_INVALID_REQUEST"):
        run_worker([sys.executable, "-c", "raise SystemExit(99)"], bad)


def test_worker_start_failure_is_reported():
    with pytest.raises(WorkerBoundaryError, match="WORKER_START_FAILED"):
        run_worker(["/definitely/not/a/real/executable"], REQUEST)


def test_worker_timeout_kills_silent_child():
    with pytest.raises(WorkerBoundaryError, match="WORKER_TIMEOUT"):
        run_worker(worker_command("import time; time.sleep(10)"), REQUEST, timeout_seconds=0.1)


def test_worker_cancellation_kills_child():
    cancel = threading.Event()
    threading.Timer(0.1, cancel.set).start()
    with pytest.raises(WorkerBoundaryError, match="WORKER_CANCELLED"):
        run_worker(worker_command("import time; time.sleep(10)"), REQUEST, timeout_seconds=3, cancel_event=cancel)


def test_worker_bounds_stdout_and_stderr():
    with pytest.raises(WorkerBoundaryError, match="WORKER_OUTPUT_LIMIT"):
        run_worker(worker_command("import sys; sys.stdout.write('x'*100000); sys.stdout.flush(); import time; time.sleep(1)"), REQUEST, timeout_seconds=2, max_stdout_bytes=100)
    with pytest.raises(WorkerBoundaryError, match="WORKER_OUTPUT_LIMIT"):
        run_worker(worker_command("import sys; sys.stderr.write('x'*100000); sys.stderr.flush(); import time; time.sleep(1)"), REQUEST, timeout_seconds=2, max_stderr_bytes=100)


def test_worker_rejects_nonzero_exit_and_malformed_result():
    with pytest.raises(WorkerBoundaryError, match="WORKER_NONZERO_EXIT"):
        run_worker(worker_command("import sys; sys.exit(7)"), REQUEST, timeout_seconds=2)
    with pytest.raises(WorkerBoundaryError, match="WORKER_INVALID_RESULT"):
        run_worker(worker_command("import sys; sys.stdin.readline(); print('not-json')"), REQUEST, timeout_seconds=2)


def test_worker_rejects_mismatched_correlation_ids():
    mismatched = dict(RESULT, request_id="other_request")
    with pytest.raises(WorkerBoundaryError, match="WORKER_INVALID_RESULT"):
        run_worker(result_emitter(mismatched), REQUEST, timeout_seconds=2)


def test_worker_rejects_invalid_limits_and_working_directory():
    with pytest.raises(WorkerBoundaryError, match="WORKER_INVALID_TIMEOUT"):
        run_worker(result_emitter(), REQUEST, timeout_seconds=0)
    with pytest.raises(WorkerBoundaryError, match="WORKER_INVALID_CWD"):
        run_worker(result_emitter(), REQUEST, cwd="/not/a/real/directory")


def test_worker_accepts_stdout_at_exact_limit_and_rejects_one_byte_below():
    payload = json.dumps(RESULT, separators=(",", ":")).encode("utf-8") + b"\n"
    exact = run_worker(
        worker_command("import sys; sys.stdin.readline(); sys.stdout.buffer.write(" + repr(payload) + "); sys.stdout.flush()"),
        REQUEST,
        timeout_seconds=2,
        max_stdout_bytes=len(payload),
        max_stderr_bytes=0,
    )
    assert exact.result["request_id"] == REQUEST["request_id"]
    with pytest.raises(WorkerBoundaryError, match="WORKER_OUTPUT_LIMIT"):
        run_worker(
            worker_command("import sys; sys.stdin.readline(); sys.stdout.buffer.write(" + repr(payload) + "); sys.stdout.flush(); import time; time.sleep(0.2)"),
            REQUEST,
            timeout_seconds=2,
            max_stdout_bytes=len(payload) - 1,
            max_stderr_bytes=0,
        )


def test_worker_handles_large_valid_request_without_deadlocking_writer():
    large_request = dict(REQUEST, text="A" * 100_000)
    outcome = run_worker(
        worker_command(
            "import sys,json; line=sys.stdin.readline(); req=json.loads(line); "
            f"out={json.dumps(RESULT, separators=(',', ':'))!r}; "
            "sys.stdout.write(out+'\\n'); sys.stdout.flush()"
        ),
        large_request,
        timeout_seconds=3,
    )
    assert outcome.result["job_id"] == REQUEST["job_id"]


def test_worker_early_child_exit_does_not_leave_writer_thread_running():
    with pytest.raises(WorkerBoundaryError, match="WORKER_NONZERO_EXIT|WORKER_INVALID_STDOUT_FRAMING"):
        run_worker(worker_command("import sys; sys.exit(9)"), dict(REQUEST, text="B" * 100_000), timeout_seconds=2)
    assert not any(thread.name.startswith("voiceover-worker-") and thread.is_alive() for thread in threading.enumerate())


def test_cancellation_wins_when_observed_before_child_exit():
    cancel = threading.Event()
    timer = threading.Timer(0.08, cancel.set)
    timer.start()
    try:
        with pytest.raises(WorkerBoundaryError, match="WORKER_CANCELLED"):
            run_worker(result_emitter(delay=0.5), REQUEST, timeout_seconds=0.5, cancel_event=cancel)
    finally:
        timer.cancel()


def test_success_wins_if_child_has_exited_before_cancellation_is_observed(monkeypatch):
    import runtime_worker

    real_popen = runtime_worker.subprocess.Popen
    payload = json.dumps(RESULT, separators=(",", ":"))
    command = worker_command("import sys; sys.stdout.write(" + repr(payload + "\n") + "); sys.stdout.flush()")

    def completed_before_return(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        proc.wait(timeout=2)
        return proc

    monkeypatch.setattr(runtime_worker.subprocess, "Popen", completed_before_return)
    cancel = threading.Event()
    cancel.set()
    outcome = run_worker(command, REQUEST, timeout_seconds=2, cancel_event=cancel)
    assert outcome.result["request_id"] == REQUEST["request_id"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group semantics require POSIX CI")
def test_timeout_terminates_descendant_holding_inherited_pipes(tmp_path):
    pid_file = tmp_path / "grandchild.pid"
    child_code = (
        "import subprocess,sys,time,pathlib; "
        f"p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid)); "
        "time.sleep(30)"
    )
    started = time.monotonic()
    with pytest.raises(WorkerBoundaryError, match="WORKER_TIMEOUT"):
        run_worker(worker_command(child_code), REQUEST, timeout_seconds=1.0)
    assert time.monotonic() - started < 4.0
    assert pid_file.exists()
    grandchild_pid = int(pid_file.read_text())
    # A killed grandchild may briefly remain as a zombie until the host init reaps it.
    proc_stat = Path(f"/proc/{grandchild_pid}/stat")
    if proc_stat.exists():
        assert proc_stat.read_text().split()[2] == "Z"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group semantics require POSIX CI")
def test_early_worker_exit_kills_descendant_that_keeps_pipe_open(tmp_path):
    pid_file = tmp_path / "early-grandchild.pid"
    child_code = (
        "import subprocess,sys,pathlib; "
        f"p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid)); "
        "print('worker exiting')"
    )
    with pytest.raises(WorkerBoundaryError, match="WORKER_INVALID_RESULT"):
        run_worker(worker_command(child_code), REQUEST, timeout_seconds=3)
    assert pid_file.exists()
    grandchild_pid = int(pid_file.read_text())
    proc_stat = Path(f"/proc/{grandchild_pid}/stat")
    if proc_stat.exists():
        assert proc_stat.read_text().split()[2] == "Z"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX setsid escape semantics require POSIX CI")
def test_escaped_descendant_is_not_claimed_contained_and_reports_stuck_io(tmp_path):
    """A descendant that calls setsid escapes group cleanup; the test owns cleanup."""
    pid_file = tmp_path / "escaped-grandchild.pid"
    payload = json.dumps(RESULT, separators=(",", ":"))
    escaped_code = (
        "import os,signal,time,pathlib; os.setsid(); "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); "
        "time.sleep(30)"
    )
    parent_code = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{escaped_code!r}]); "
        f"deadline=time.monotonic()+3; "
        f"while_not_ready = None; "
        f"import pathlib; "
        f"\nwhile time.monotonic()<deadline and not pathlib.Path({str(pid_file)!r}).exists(): time.sleep(0.01)\n"
        f"sys.stdout.write({(payload + chr(10))!r}); sys.stdout.flush()"
    )
    escaped_pid = None
    try:
        with pytest.raises(WorkerBoundaryError, match="WORKER_IO_THREAD_STUCK"):
            run_worker(worker_command(parent_code), REQUEST, timeout_seconds=3)
        assert pid_file.exists(), "descendant did not reach the escape checkpoint"
        escaped_pid = int(pid_file.read_text())
        # This surviving process is expected: POSIX process-group termination is not a sandbox.
        os_kill = __import__("os").kill
        os_kill(escaped_pid, 0)
    finally:
        if escaped_pid is None and pid_file.exists():
            escaped_pid = int(pid_file.read_text())
        if escaped_pid is not None:
            try:
                __import__("os").kill(escaped_pid, __import__("signal").SIGKILL)
            except ProcessLookupError:
                pass
