from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator

import resource_guard as guard
from file_locking import FileLockError, exclusive_file_lock
from resource_guard import ENGINE_POLICIES, resource_preflight, run_managed_process, thread_limited_environment

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "tts-resource-preflight-v1.schema.json").read_text(encoding="utf-8"))


def healthy_probe():
    return {
        "monitor_available": True,
        "available_memory_bytes": 24 * 1024**3,
        "current_process_tree_rss_bytes": 100 * 1024**2,
        "available_cpu_count": 8,
    }


def ready_report(engine_id, **_kwargs):
    policy = ENGINE_POLICIES[engine_id]
    return {
        "schema_version": 1, "engine_id": engine_id, "status": "READY_TO_ATTEMPT",
        "diagnostic_only": True, "installation_performed": False,
        "model_downloaded": False, "inference_verified": False,
        "limits": {
            "minimum_available_memory_mb": policy.minimum_available_memory_mb,
            "maximum_process_tree_rss_mb": policy.maximum_process_tree_rss_mb,
            "minimum_free_disk_mb": policy.minimum_free_disk_mb,
            "cpu_threads": policy.cpu_threads, "max_chunk_chars": policy.max_chunk_chars,
            "smoke_timeout_seconds": policy.smoke_timeout_seconds,
        },
        "observed": {"resource_monitor_available": True, "available_memory_mb": 24000,
                     "current_process_tree_rss_mb": 100, "free_disk_mb": 54000,
                     "available_cpu_count": 8},
        "blocking_reasons": [], "notes": [],
    }


def test_resource_schema_and_engine_policy_values_are_valid():
    Draft202012Validator.check_schema(SCHEMA)
    for engine_id in ENGINE_POLICIES:
        report = ready_report(engine_id)
        Draft202012Validator(SCHEMA).validate(report)
        assert report["inference_verified"] is False
        assert report["model_downloaded"] is False
    assert ENGINE_POLICIES["qwen3_tts"].minimum_available_memory_mb == 14336
    assert ENGINE_POLICIES["qwen3_tts"].maximum_process_tree_rss_mb == 10240
    assert ENGINE_POLICIES["qwen3_tts"].cpu_threads == 2


def test_preflight_blocks_when_memory_or_disk_are_below_engine_budget(monkeypatch, tmp_path):
    monkeypatch.setattr(guard, "probe_system_resources", healthy_probe)
    monkeypatch.setattr(guard, "_disk_free_bytes", lambda _root: 100 * 1024**2)
    report = resource_preflight("qwen3_tts", model_root=tmp_path)
    assert report["status"] == "BLOCKED"
    assert report["blocking_reasons"] == ["FREE_DISK_BELOW_MINIMUM"]
    Draft202012Validator(SCHEMA).validate(report)

    low_memory = healthy_probe()
    low_memory["available_memory_bytes"] = 2 * 1024**3
    monkeypatch.setattr(guard, "probe_system_resources", lambda: low_memory)
    monkeypatch.setattr(guard, "_disk_free_bytes", lambda _root: 20 * 1024**3)
    report = resource_preflight("qwen3_tts", model_root=tmp_path)
    assert report["status"] == "BLOCKED"
    assert report["blocking_reasons"] == ["AVAILABLE_MEMORY_BELOW_MINIMUM"]


def test_missing_resource_monitor_fails_closed_without_claiming_model_status(monkeypatch):
    monkeypatch.setattr(guard, "probe_system_resources", lambda: {
        "monitor_available": False, "available_memory_bytes": None,
        "current_process_tree_rss_bytes": None, "available_cpu_count": 8,
    })
    monkeypatch.setattr(guard, "_disk_free_bytes", lambda _root: 100 * 1024**3)
    report = resource_preflight("kokoro")
    assert report["status"] == "BLOCKED"
    assert "RESOURCE_MONITOR_UNAVAILABLE" in report["blocking_reasons"]
    assert report["inference_verified"] is False
    Draft202012Validator(SCHEMA).validate(report)


def test_thread_caps_return_copy_and_set_all_common_numerical_libraries():
    original = {"OMP_NUM_THREADS": "16", "TOKENIZERS_PARALLELISM": "true", "CUSTOM": "kept"}
    capped = thread_limited_environment(original, "qwen3_tts")
    assert original["OMP_NUM_THREADS"] == "16"
    assert capped["OMP_NUM_THREADS"] == "2"
    assert capped["MKL_NUM_THREADS"] == "2"
    assert capped["OPENBLAS_NUM_THREADS"] == "2"
    assert capped["NUMEXPR_NUM_THREADS"] == "2"
    assert capped["TOKENIZERS_PARALLELISM"] == "false"
    assert capped["CUSTOM"] == "kept"


def test_lock_refuses_concurrent_engine_job(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "resource_preflight", ready_report)
    monkeypatch.setattr(guard, "_lock_dir", lambda: tmp_path / "locks")
    lock = tmp_path / "locks" / "tts-single-job.lock"
    with exclusive_file_lock(lock, timeout_seconds=1):
        result = run_managed_process(
            [sys.executable, "-c", "print('should not run')"], input_text="", timeout_seconds=1,
            environment=os.environ, cwd=tmp_path, engine_id="kokoro",
        )
    data = json.loads(result.stdout)
    assert result.returncode == 75
    assert data["error"] == "ENGINE_JOB_ALREADY_RUNNING"


def test_managed_process_caps_threads_and_returns_small_resource_report(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "resource_preflight", ready_report)
    monkeypatch.setattr(guard, "_lock_dir", lambda: tmp_path / "locks")
    monkeypatch.setattr(guard, "process_tree_rss_bytes", lambda _pid: 256 * 1024**2)
    code = "import json,os,sys; sys.stdin.read(); print(json.dumps({'omp':os.environ['OMP_NUM_THREADS'],'ok':True}))"
    result = run_managed_process(
        [sys.executable, "-c", code], input_text="small request", timeout_seconds=5,
        environment=os.environ, cwd=tmp_path, engine_id="kokoro", poll_interval_seconds=0.05,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"omp": "2", "ok": True}
    assert result.resource_report["peak_process_tree_rss_mb"] == 256
    assert result.resource_report["cpu_threads"] == 2


def test_managed_process_kills_worker_above_rss_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "resource_preflight", ready_report)
    monkeypatch.setattr(guard, "_lock_dir", lambda: tmp_path / "locks")
    monkeypatch.setattr(guard, "process_tree_rss_bytes", lambda _pid: 2 * 1024**2)
    monkeypatch.setitem(guard.ENGINE_POLICIES, "kokoro", replace(ENGINE_POLICIES["kokoro"], maximum_process_tree_rss_mb=1))
    result = run_managed_process(
        [sys.executable, "-c", "import time; time.sleep(5)"], input_text="", timeout_seconds=5,
        environment=os.environ, cwd=tmp_path, engine_id="kokoro", poll_interval_seconds=0.05,
    )
    assert result.returncode == 137
    data = json.loads(result.stdout)
    assert data["error"] == "RESOURCE_LIMIT_EXCEEDED"
    assert data["resource"]["maximum_process_tree_rss_mb"] == 1


def test_managed_process_timeout_terminates_group(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "resource_preflight", ready_report)
    monkeypatch.setattr(guard, "_lock_dir", lambda: tmp_path / "locks")
    monkeypatch.setattr(guard, "process_tree_rss_bytes", lambda _pid: 128 * 1024**2)
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        run_managed_process(
            [sys.executable, "-c", "import time; time.sleep(5)"], input_text="", timeout_seconds=0.1,
            environment=os.environ, cwd=tmp_path, engine_id="kokoro", poll_interval_seconds=0.05,
        )
    assert caught.value.resource_report["timeout_seconds"] == 0.1
    assert caught.value.resource_report["maximum_process_tree_rss_mb"] == ENGINE_POLICIES["kokoro"].maximum_process_tree_rss_mb


def test_lock_rejects_symlink_and_invalid_timeout(tmp_path):
    if not hasattr(os, "symlink"):
        pytest.skip("symlink support unavailable")
    target = tmp_path / "real.lock"
    target.write_text("", encoding="utf-8")
    alias = tmp_path / "alias.lock"
    try:
        alias.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation denied")
    with pytest.raises(FileLockError, match="LOCK_PATH_SYMLINK"):
        with exclusive_file_lock(alias):
            pass
    with pytest.raises(FileLockError, match="LOCK_TIMEOUT_INVALID"):
        with exclusive_file_lock(tmp_path / "bad.lock", timeout_seconds=200):
            pass
