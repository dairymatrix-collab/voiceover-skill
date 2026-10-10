from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import jsonschema
import pytest

import tts_artifact_readiness as readiness
from tts_artifact_readiness import ArtifactSpec

ROOT = Path(__file__).resolve().parents[1]
V1_SCHEMA = json.loads((ROOT / "schemas/tts-artifact-readiness-v1.schema.json").read_text())
V2_SCHEMA = json.loads((ROOT / "schemas/tts-artifact-readiness-v2.schema.json").read_text())


def _populate_kokoro(directory: Path):
    (directory / "voices").mkdir(parents=True, exist_ok=True)
    (directory / "config.json").write_bytes(b"config")
    (directory / "kokoro-v1_0.pth").write_bytes(b"checkpoint")
    (directory / "voices" / "af_heart.pt").write_bytes(b"voice")


def _populate_qwen(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "model.safetensors", "tokenizer_config.json", "vocab.json",
                 "merges.txt", "preprocessor_config.json"):
        (directory / name).write_bytes(b"asset")
    speech = directory / "speech_tokenizer"
    speech.mkdir()
    for name in ("config.json", "model.safetensors", "preprocessor_config.json"):
        (speech / name).write_bytes(b"asset")


def _populate_chatterbox_cache(root: Path):
    model = root / "models--ResembleAI--chatterbox"
    blobs = model / "blobs"
    snapshot = model / "snapshots" / "revision-abc123"
    blobs.mkdir(parents=True)
    snapshot.mkdir(parents=True)
    names = ("ve.pt", "s3gen.pt", "grapheme_mtl_merged_expanded_v1.json",
             "t3_mtl23ls_v2.safetensors")
    for index, name in enumerate(names):
        blob = blobs / f"blob-{index}"
        blob.write_bytes(b"model asset")
        (snapshot / name).symlink_to(blob)
    return model, snapshot


@pytest.mark.parametrize("alias,canonical", [
    ("kokoro", "kokoro"), ("Kokoro-TTS", "kokoro"),
    ("chatterbox", "chatterbox"), ("Chatterbox-TTS", "chatterbox"),
    ("qwen3_tts", "qwen3_tts"), ("qwen3-tts", "qwen3_tts"), ("qwen-tts", "qwen3_tts"),
])
def test_documented_engine_aliases_normalize_to_canonical_id(alias, canonical):
    report = readiness.inspect_engine_artifacts_v2(alias)
    assert report["engine"] == canonical


@pytest.mark.parametrize("bad", ["", " no-such-engine ", "qwen-ish", "kokoro\x00"])
def test_unknown_and_invalid_engine_aliases_fail_closed(bad):
    with pytest.raises(ValueError):
        readiness.inspect_engine_artifacts_v2(bad)


def test_v1_contract_remains_schema_valid_with_corrected_adapter_assets(tmp_path):
    _populate_kokoro(tmp_path / "Kokoro-82M")
    report = readiness.inspect_engine_artifacts("kokoro", model_root=tmp_path)
    jsonschema.validate(report, V1_SCHEMA["$defs"]["report"])
    assert report["schema_version"] == 1
    assert "state" not in report["artifacts"][0]
    assert report["artifact_ready"] is True


def test_required_and_optional_artifact_semantics_are_distinct(tmp_path, monkeypatch):
    required = ArtifactSpec("kokoro", "core", ("core.bin",), True, "file")
    optional = ArtifactSpec("kokoro", "aux", ("aux.bin",), False, "file")
    monkeypatch.setitem(readiness.ENGINE_ARTIFACTS, "kokoro", (required, optional))
    report = readiness.inspect_engine_artifacts_v2("kokoro", model_root=tmp_path)
    assert not report["artifact_ready"]
    assert report["missing_required"] == ["core"]
    assert report["missing_optional"] == ["aux"]

    (tmp_path / "core.bin").write_bytes(b"nonempty")
    report = readiness.inspect_engine_artifacts_v2("kokoro", model_root=tmp_path)
    assert report["artifact_ready"]
    assert report["missing_required"] == []
    assert report["missing_optional"] == ["aux"]


def test_previous_onnx_kokoro_layout_is_not_misreported_as_adapter_ready(tmp_path):
    (tmp_path / "kokoro-v1.0.onnx").write_bytes(b"onnx")
    (tmp_path / "voices-v1.0.bin").write_bytes(b"voices")
    report = readiness.inspect_engine_artifacts_v2("kokoro", model_root=tmp_path)
    assert report["artifact_ready"] is False
    assert report["status"] == "ARTIFACTS_MISSING"


def test_empty_required_file_is_not_artifact_ready(tmp_path):
    model = tmp_path / "Kokoro-82M"
    (model / "voices").mkdir(parents=True)
    (model / "config.json").write_bytes(b"config")
    (model / "kokoro-v1_0.pth").touch()
    (model / "voices" / "af_heart.pt").write_bytes(b"voice")
    report = readiness.inspect_engine_artifacts_v2("kokoro", model_root=tmp_path)
    assert not report["artifact_ready"]
    assert report["status"] == "ARTIFACTS_INCOMPLETE"


def test_empty_model_directory_is_not_artifact_ready(tmp_path):
    (tmp_path / "Qwen3-TTS-12Hz-1.7B-CustomVoice").mkdir()
    report = readiness.inspect_engine_artifacts_v2("qwen3_tts", model_root=tmp_path)
    assert report["artifacts"][0]["state"] == "EMPTY"
    assert not report["artifact_ready"]


def test_nonempty_but_incomplete_qwen_directory_is_not_ready(tmp_path):
    model = tmp_path / "Qwen3-TTS-12Hz-1.7B-CustomVoice"
    model.mkdir()
    (model / "config.json").write_bytes(b"config")
    (model / "random.bin").write_bytes(b"not a checkpoint")
    report = readiness.inspect_engine_artifacts_v2("qwen3_tts", model_root=tmp_path)
    artifact = report["artifacts"][0]
    assert artifact["state"] == "INCOMPLETE"
    assert artifact["satisfied_file_groups"] == [True, False, False, False, False, False, False, False, False]
    assert report["status"] == "ARTIFACTS_INCOMPLETE"
    assert not report["artifact_ready"]


def test_qwen_official_layout_includes_nested_speech_tokenizer(tmp_path):
    model = tmp_path / "Qwen3-TTS-12Hz-1.7B-CustomVoice"
    _populate_qwen(model)
    report = readiness.inspect_engine_artifacts_v2("qwen3-tts", model_root=tmp_path)
    assert report["artifact_ready"] is True
    assert all(report["artifacts"][0]["satisfied_file_groups"])
    assert report["artifacts"][0]["regular_file_count"] == 9


def test_qwen_voice_design_variant_has_its_own_pinned_artifact_layout(tmp_path):
    model = tmp_path / "Qwen3-TTS-12Hz-1.7B-VoiceDesign"
    _populate_qwen(model)
    report = readiness.inspect_engine_artifacts_v2(
        "qwen3_tts", model_root=tmp_path, model_variant="voice_design"
    )
    jsonschema.validate(report, V2_SCHEMA)
    assert report["artifact_ready"] is True
    assert report["artifacts"][0]["artifact_id"] == "qwen_voice_design_model"
    assert report["artifacts"][0]["matched_path"] == str(model.resolve())
    assert all(report["artifacts"][0]["satisfied_file_groups"])


def test_artifact_variant_is_rejected_when_unknown_or_incompatible(tmp_path):
    with pytest.raises(ValueError, match="unsupported qwen3_tts model variant"):
        readiness.inspect_engine_artifacts_v2(
            "qwen3_tts", model_root=tmp_path, model_variant="unlisted-model"
        )
    with pytest.raises(ValueError, match="unsupported kokoro model variant"):
        readiness.inspect_engine_artifacts_v2(
            "kokoro", model_root=tmp_path, model_variant="voice_design"
        )


def test_nested_directory_counting_is_correct_and_deterministic(tmp_path):
    model = tmp_path / "Qwen3-TTS-12Hz-1.7B-CustomVoice"
    _populate_qwen(model)
    (model / "weights").mkdir()
    (model / "weights" / "extra.safetensors").write_bytes(b"extra")
    first = readiness.inspect_engine_artifacts_v2("qwen3_tts", model_root=tmp_path)
    second = readiness.inspect_engine_artifacts_v2("qwen3_tts", model_root=tmp_path)
    assert first == second
    assert first["artifacts"][0]["regular_file_count"] == 10
    assert first["artifact_ready"]


def test_directory_hashes_actual_required_files_with_per_file_size_cap(tmp_path, monkeypatch):
    _populate_kokoro(tmp_path / "Kokoro-82M")
    monkeypatch.setattr(readiness, "MAX_HASH_BYTES", 6)
    report = readiness.inspect_engine_artifacts_v2("kokoro", model_root=tmp_path, hash_files=True)
    artifact = report["artifacts"][0]
    assert report["artifact_ready"]
    assert artifact["required_file_matches"] == ["config.json", "kokoro-v1_0.pth", "voices/af_heart.pt"]
    hashes = {item["relative_path"]: item for item in artifact["required_file_hashes"]}
    assert hashes["config.json"]["sha256"] == hashlib.sha256(b"config").hexdigest()
    assert hashes["config.json"]["bytes_hashed"] == 6
    assert hashes["kokoro-v1_0.pth"]["hash_status"] == "SKIPPED_SIZE_LIMIT"
    assert hashes["kokoro-v1_0.pth"]["bytes_hashed"] == 0
    assert hashes["voices/af_heart.pt"]["hash_status"] == "SHA256_COMPLETE"


def test_directory_required_file_hash_detects_change_during_hash(tmp_path, monkeypatch):
    _populate_kokoro(tmp_path / "Kokoro-82M")
    monkeypatch.setattr(readiness, "_digest_open_file",
                        lambda _fd, _initial: (None, "CHANGED_DURING_SCAN", 0))
    report = readiness.inspect_engine_artifacts_v2("kokoro", model_root=tmp_path, hash_files=True)
    artifact = report["artifacts"][0]
    assert artifact["state"] == "CHANGED_DURING_SCAN"
    assert report["artifact_ready"] is False
    assert all(item["hash_status"] == "CHANGED_DURING_SCAN"
               for item in artifact["required_file_hashes"])


def test_huggingface_cache_internal_symlinked_checkpoints_are_read_safely(tmp_path):
    _populate_chatterbox_cache(tmp_path)
    report = readiness.inspect_engine_artifacts_v2("chatterbox", model_root=tmp_path)
    artifact = report["artifacts"][0]
    assert report["artifact_ready"] is True
    assert artifact["state"] == "PRESENT"
    assert all(artifact["satisfied_file_groups"])
    assert artifact["symlink_entries_seen"] == 4


def test_symlink_target_outside_model_root_is_rejected(tmp_path):
    model = tmp_path / "Kokoro-82M"
    (model / "voices").mkdir(parents=True)
    (model / "config.json").write_bytes(b"config")
    (model / "voices" / "af_heart.pt").write_bytes(b"voice")
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    (outside / "kokoro-v1_0.pth").write_bytes(b"secret")
    (model / "kokoro-v1_0.pth").symlink_to(outside / "kokoro-v1_0.pth")
    report = readiness.inspect_engine_artifacts_v2("kokoro", model_root=tmp_path)
    assert report["artifacts"][0]["state"] == "PATH_UNSAFE"
    assert report["status"] == "ARTIFACT_PATH_UNSAFE"
    assert not report["artifact_ready"]


def test_nested_directory_symlink_escape_is_reported(tmp_path):
    model = tmp_path / "Qwen3-TTS-12Hz-1.7B-CustomVoice"
    _populate_qwen(model)
    outside = tmp_path.parent / (tmp_path.name + "-outside-dir")
    outside.mkdir()
    (outside / "weights.bin").write_bytes(b"secret")
    (model / "external").symlink_to(outside, target_is_directory=True)
    report = readiness.inspect_engine_artifacts_v2("qwen3_tts", model_root=tmp_path)
    assert report["artifacts"][0]["state"] == "PATH_UNSAFE"
    assert report["artifacts"][0]["present"] is False


def test_unreadable_file_is_not_reported_as_ready(tmp_path, monkeypatch):
    model = tmp_path / "Kokoro-82M"
    _populate_kokoro(model)
    original_open = readiness.os.open

    def reject_checkpoint(path, *args, **kwargs):
        if os.fspath(path) == "kokoro-v1_0.pth":
            raise PermissionError(errno.EACCES, "denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(readiness.os, "open", reject_checkpoint)
    report = readiness.inspect_engine_artifacts_v2("kokoro", model_root=tmp_path)
    assert report["artifacts"][0]["state"] == "UNREADABLE"
    assert report["status"] == "ARTIFACTS_UNREADABLE"
    assert report["artifact_ready"] is False


def test_directory_scan_permission_error_is_explicit(tmp_path, monkeypatch):
    model = tmp_path / "Kokoro-82M"
    _populate_kokoro(model)
    monkeypatch.setattr(readiness.os, "scandir", lambda fd: (_ for _ in ()).throw(PermissionError(errno.EACCES, "denied")))
    report = readiness.inspect_engine_artifacts_v2("kokoro", model_root=tmp_path)
    assert report["artifacts"][0]["state"] == "UNREADABLE"
    assert report["status"] == "ARTIFACTS_UNREADABLE"


def test_directory_entry_limit_is_bounded(tmp_path, monkeypatch):
    model = tmp_path / "Qwen3-TTS-12Hz-1.7B-CustomVoice"
    _populate_qwen(model)
    monkeypatch.setattr(readiness, "MAX_SCAN_ENTRIES", 1)
    report = readiness.inspect_engine_artifacts_v2("qwen3_tts", model_root=tmp_path)
    assert report["artifacts"][0]["state"] == "SCAN_LIMIT_EXCEEDED"
    assert report["status"] == "ARTIFACT_SCAN_INCOMPLETE"


def test_directory_depth_limit_is_bounded_by_relative_depth(tmp_path, monkeypatch):
    model = tmp_path / "Kokoro-82M"
    _populate_kokoro(model)
    (model / "one" / "two").mkdir(parents=True)
    (model / "one" / "two" / "extra.bin").write_bytes(b"deep")
    monkeypatch.setattr(readiness, "MAX_SCAN_DEPTH", 1)
    report = readiness.inspect_engine_artifacts_v2("kokoro", model_root=tmp_path)
    assert report["artifacts"][0]["state"] == "SCAN_LIMIT_EXCEEDED"
    assert not report["artifact_ready"]


def test_hash_is_full_file_digest_and_large_files_are_not_prefix_hashed(tmp_path, monkeypatch):
    spec = ArtifactSpec("kokoro", "checkpoint", ("checkpoint.bin",), True, "file")
    monkeypatch.setitem(readiness.ENGINE_ARTIFACTS, "kokoro", (spec,))
    payload = b"small-complete-file"
    (tmp_path / "checkpoint.bin").write_bytes(payload)
    report = readiness.inspect_engine_artifacts_v2("kokoro", model_root=tmp_path, hash_files=True)
    record = report["artifacts"][0]
    assert record["sha256"] == hashlib.sha256(payload).hexdigest()
    assert record["hash_status"] == "SHA256_COMPLETE"
    assert record["bytes_hashed"] == len(payload)

    monkeypatch.setattr(readiness, "MAX_HASH_BYTES", 4)
    large = readiness.inspect_engine_artifacts_v2("kokoro", model_root=tmp_path, hash_files=True)["artifacts"][0]
    assert large["present"] is True
    assert large["hash_status"] == "SKIPPED_SIZE_LIMIT"
    assert "sha256" not in large
    assert large["bytes_hashed"] == 0


def test_hash_detects_file_change_during_read(tmp_path, monkeypatch):
    path = tmp_path / "changing.bin"
    path.write_bytes(b"a" * (readiness._READ_BYTES * 2))
    with path.open("rb", buffering=0) as stream:
        fd = stream.fileno()
        initial = os.fstat(fd)
        real_read = readiness.os.read
        calls = 0

        def read_then_mutate(file_fd, size):
            nonlocal calls
            block = real_read(file_fd, size)
            calls += 1
            if calls == 1:
                with path.open("r+b", buffering=0) as writer:
                    os.pwrite(writer.fileno(), b"b", 0)
                    os.fsync(writer.fileno())
            return block

        monkeypatch.setattr(readiness.os, "read", read_then_mutate)
        digest, state, _ = readiness._digest_open_file(fd, initial)
    assert digest is None
    assert state == "CHANGED_DURING_SCAN"


def test_portable_fallback_scanner_handles_official_qwen_layout(tmp_path, monkeypatch):
    model = tmp_path / "Qwen3-TTS-12Hz-1.7B-CustomVoice"
    _populate_qwen(model)
    monkeypatch.setattr(readiness.os, "supports_fd", set())
    report = readiness.inspect_engine_artifacts_v2("qwen3_tts", model_root=tmp_path)
    assert report["artifact_ready"]
    assert all(report["artifacts"][0]["satisfied_file_groups"])


def test_invalid_model_root_types_and_nul_are_rejected():
    for root in (None, 3, Path("/tmp") if os.name == "nt" else "bad\x00root"):
        if root is None:
            continue
        with pytest.raises(ValueError):
            readiness.resolve_model_root(root)


def test_atomic_report_write_is_valid_and_cleans_staging(tmp_path):
    target = tmp_path / "nested" / "report.json"
    report = {"safe": True, "text": "no transcript included"}
    readiness.write_report_atomic(target, report)
    assert json.loads(target.read_text()) == report
    assert not list(target.parent.glob(".report.json.*.tmp"))
    readiness.write_report_atomic(target, {"updated": 2})
    assert json.loads(target.read_text()) == {"updated": 2}


def test_atomic_report_rejects_model_root_collisions_and_symlinks(tmp_path):
    model_root = tmp_path / "models"
    model_root.mkdir()
    with pytest.raises(ValueError, match="INSIDE_MODEL_ROOT"):
        readiness.write_report_atomic(model_root / "report.json", {"x": 1}, protected_root=model_root)
    with pytest.raises(ValueError, match="INSIDE_MODEL_ROOT"):
        readiness.write_report_atomic(model_root, {"x": 1}, protected_root=model_root)
    outside = tmp_path / "outside.json"
    outside.write_text("preserve")
    link = tmp_path / "report-link.json"
    link.symlink_to(outside)
    with pytest.raises(ValueError, match="SYMLINK"):
        readiness.write_report_atomic(link, {"x": 1}, protected_root=model_root)
    assert outside.read_text() == "preserve"


def test_atomic_report_rejects_directory_and_nul_destination(tmp_path):
    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(ValueError, match="IS_DIRECTORY"):
        readiness.write_report_atomic(directory, {}, protected_root=tmp_path / "models")
    with pytest.raises(ValueError):
        readiness.write_report_atomic(str(tmp_path) + "\x00/report", {})


def test_artifact_v2_single_all_and_unconfigured_reports_conform_to_schema(tmp_path, monkeypatch):
    model = tmp_path / "Kokoro-82M"
    _populate_kokoro(model)
    single = readiness.inspect_engine_artifacts_v2("kokoro", model_root=tmp_path, hash_files=True)
    aggregate = readiness.inspect_all_v2(tmp_path)
    for key in ("VOICEOVER_MODEL_ROOT", "TTS_MODEL_ROOT", "HF_HUB_CACHE", "HF_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(readiness.Path, "home", lambda: tmp_path / "fresh-home")
    unconfigured = readiness.inspect_all_v2()
    jsonschema.Draft202012Validator.check_schema(V2_SCHEMA)
    jsonschema.validate(single, V2_SCHEMA)
    jsonschema.validate(aggregate, V2_SCHEMA)
    jsonschema.validate(unconfigured, V2_SCHEMA)
    assert single["inference_verified"] is False
    assert aggregate["ready_engine_count"] == 1
    assert unconfigured["ready_engine_count"] == 0


def test_cli_alias_v2_report_and_exit_codes(tmp_path):
    _populate_kokoro(tmp_path / "Kokoro-82M")
    report_path = tmp_path.parent / (tmp_path.name + "-report.json")
    result = subprocess.run(
        [sys.executable, "scripts/inspect_tts_artifacts.py", "--engine", "kokoro-tts",
         "--schema-version", "2", "--model-root", str(tmp_path), "--report", str(report_path)],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    stdout = json.loads(result.stdout)
    assert stdout["schema_version"] == 2 and stdout["artifact_ready"] is True
    assert json.loads(report_path.read_text()) == stdout

    conflict = subprocess.run(
        [sys.executable, "scripts/inspect_tts_artifacts.py", "--engine", "kokoro", "--schema-version", "2",
         "--model-root", str(tmp_path), "--report", str(tmp_path / "report.json")],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    assert conflict.returncode == 2
    assert "REPORT_DESTINATION_INSIDE_MODEL_ROOT" in conflict.stderr


def test_v1_cli_remains_default_and_honest_exit_semantics(tmp_path):
    result = subprocess.run(
        [sys.executable, "scripts/inspect_tts_artifacts.py", "--engine", "qwen3_tts", "--model-root", str(tmp_path)],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 3
    report = json.loads(result.stdout)
    assert report["schema_version"] == 1
    assert report["inference_verified"] is False
