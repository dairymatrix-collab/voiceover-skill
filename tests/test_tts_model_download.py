from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.download_tts_model as downloader
from tts_model_catalog import ModelSpec, get_model_spec

SCHEMA = json.loads((ROOT / "schemas" / "tts-model-download-report-v1.schema.json").read_text(encoding="utf-8"))


def _ready(_engine, *, model_root=None):
    return {
        "schema_version": 1,
        "engine_id": _engine,
        "status": "READY_TO_ATTEMPT",
        "diagnostic_only": True,
        "installation_performed": False,
        "model_downloaded": False,
        "inference_verified": False,
        "limits": {},
        "observed": {"available_memory_mb": 24000, "free_disk_mb": 50000},
        "blocking_reasons": [],
        "notes": [],
    }


def _simple_spec(*, maximum=100, required=("config.txt",), patterns=("*.txt",)):
    return ModelSpec(
        engine_id="kokoro", variant="preset", model_id="test/model",
        revision="a" * 40, license="test", allow_patterns=patterns,
        required_files=required, required_patterns=(), max_download_bytes=maximum,
    )


def _fake_args(tmp_path, **overrides):
    values = {
        "engine": "qwen3_tts", "variant": "voice_design",
        "cache_dir": str(tmp_path / "hub"), "download": False,
        "python": sys.executable, "timeout_seconds": 10, "report": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_catalog_has_only_fixed_ids_and_pinned_allowlists():
    qwen = get_model_spec("qwen3_tts", "voice_design")
    assert qwen.model_id == "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
    assert qwen.revision == "5ecdb67327fd37bb2e042aab12ff7391903235d3"
    assert "model.safetensors" in qwen.allow_patterns
    assert qwen.max_download_bytes == 4_600_000_000
    assert get_model_spec("chatterbox").revision == "5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18"
    assert get_model_spec("kokoro").uses_main_ref is True
    with pytest.raises(ValueError, match="UNKNOWN_ENGINE"):
        get_model_spec("https://example.invalid/model")
    with pytest.raises(ValueError, match="MODEL_VARIANT_UNSUPPORTED"):
        get_model_spec("qwen3_tts", "arbitrary")


@pytest.mark.parametrize("engine,variant", [("chatterbox", "reference_clone"), ("qwen3_tts", "preset")])
def test_public_downloader_rejects_unverified_targets(tmp_path, engine, variant):
    args = _fake_args(tmp_path, engine=engine, variant=variant)
    with pytest.raises(ValueError, match="MODEL_PATH_NOT_VERIFIED"):
        downloader._run(args)


def test_cache_path_rejects_final_symlink_and_non_directory(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="CACHE_DIR_SYMLINK"):
        downloader.normalize_cache_dir(link)
    file_path = tmp_path / "not-a-dir"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="CACHE_DIR_NOT_DIRECTORY"):
        downloader.normalize_cache_dir(file_path)


def test_snapshot_verification_requires_allowlisted_files_and_revision(tmp_path):
    cache = tmp_path / "hub"
    snapshot = cache / "models--test--model" / "snapshots" / ("a" * 40)
    snapshot.mkdir(parents=True)
    (snapshot / "config.txt").write_text("ready", encoding="utf-8")
    report = downloader.verify_snapshot(snapshot, cache, _simple_spec())
    assert report["file_count"] == 1
    assert report["actual_bytes"] == 5

    (snapshot / "unexpected.bin").write_bytes(b"x")
    with pytest.raises(downloader.DownloadValidationError, match="SNAPSHOT_CONTAINS_UNALLOWLISTED_FILE"):
        downloader.verify_snapshot(snapshot, cache, _simple_spec())


def test_snapshot_verification_rejects_symlink_escape_and_size_overflow(tmp_path):
    cache = tmp_path / "hub"
    snapshot = cache / "models--test--model" / "snapshots" / ("a" * 40)
    snapshot.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (snapshot / "config.txt").symlink_to(outside)
    with pytest.raises(downloader.DownloadValidationError, match="SNAPSHOT_FILE_ESCAPES_CACHE"):
        downloader.verify_snapshot(snapshot, cache, _simple_spec())

    (snapshot / "config.txt").unlink()
    (snapshot / "config.txt").write_bytes(b"x" * 101)
    with pytest.raises(downloader.DownloadValidationError, match="MODEL_SIZE_LIMIT_EXCEEDED"):
        downloader.verify_snapshot(snapshot, cache, _simple_spec(maximum=100))


def test_plan_mode_is_read_only_and_report_matches_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader, "resource_preflight", _ready)
    monkeypatch.setattr(downloader, "_free_disk_bytes", lambda _path: 80 * 1024**3)
    args = _fake_args(tmp_path)
    report, code = downloader._run(args)
    assert code == 0
    assert report["status"] == "PLAN_ONLY"
    assert report["download_requested"] is False
    assert report["model_downloaded"] is False
    assert not Path(args.cache_dir).exists()
    Draft202012Validator.check_schema(SCHEMA)
    Draft202012Validator(SCHEMA).validate(report)


def test_resource_block_stops_before_worker_or_cache_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader, "resource_preflight", lambda *_args, **_kwargs: {
        "status": "BLOCKED", "blocking_reasons": ["AVAILABLE_MEMORY_BELOW_MINIMUM"]
    })
    monkeypatch.setattr(downloader, "_free_disk_bytes", lambda _path: 80 * 1024**3)
    monkeypatch.setattr(downloader, "run_managed_process", lambda *_args, **_kwargs: pytest.fail("worker launched"))
    args = _fake_args(tmp_path, download=True)
    report, code = downloader._run(args)
    assert code == 3
    assert report["status"] == "BLOCKED_RESOURCE"
    assert report["blocking_reasons"] == ["AVAILABLE_MEMORY_BELOW_MINIMUM"]
    assert not Path(args.cache_dir).exists()


def test_disk_headroom_gate_blocks_even_when_generic_preflight_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader, "resource_preflight", _ready)
    monkeypatch.setattr(downloader, "_free_disk_bytes", lambda _path: 100)
    args = _fake_args(tmp_path)
    report, code = downloader._run(args)
    assert code == 3
    assert report["status"] == "BLOCKED_RESOURCE"
    assert "DOWNLOAD_DISK_HEADROOM_BELOW_MINIMUM" in report["blocking_reasons"]


def test_explicit_download_uses_monitored_worker_and_never_forwards_hf_token(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader, "resource_preflight", _ready)
    monkeypatch.setattr(downloader, "_free_disk_bytes", lambda _path: 80 * 1024**3)
    monkeypatch.setenv("HF_TOKEN", "must-not-be-forwarded")
    captured = {}

    def fake_worker(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        child = subprocess.CompletedProcess(argv, 0, stdout=json.dumps({
            "ok": True, "already_present": False,
            "snapshot_path": str(Path(args.cache_dir) / "models--qwen--voice" / "snapshots" / ("5ecdb67327fd37bb2e042aab12ff7391903235d3")),
            "resolved_revision": "5ecdb67327fd37bb2e042aab12ff7391903235d3",
            "actual_bytes": 100, "file_count": 11, "files": [],
            "hub_integrity": "verified by test",
        }), stderr="")
        child.resource_report = {"peak_process_tree_rss_mb": 512}
        return child

    monkeypatch.setattr(downloader, "run_managed_process", fake_worker)
    args = _fake_args(tmp_path, download=True)
    report, code = downloader._run(args)
    assert code == 0
    assert report["status"] == "DOWNLOADED"
    assert report["model_downloaded"] is True
    assert report["inference_verified"] is False
    assert captured["kwargs"]["engine_id"] == "qwen3_tts"
    assert captured["kwargs"]["timeout_seconds"] == 10.0
    child_env = captured["kwargs"]["environment"]
    assert child_env["HF_HUB_CACHE"] == str(Path(args.cache_dir).resolve())
    assert "HF_TOKEN" not in child_env
    assert captured["argv"][0] == sys.executable


def test_report_keeps_model_and_inference_states_distinct(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader, "resource_preflight", _ready)
    monkeypatch.setattr(downloader, "_free_disk_bytes", lambda _path: 80 * 1024**3)
    report, _ = downloader._run(_fake_args(tmp_path))
    assert report["model_downloaded"] is False
    assert report["inference_verified"] is False
    assert report["installation_performed"] is False
