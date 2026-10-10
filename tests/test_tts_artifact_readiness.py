import json
from pathlib import Path
import pytest
from tts_artifact_readiness import inspect_engine_artifacts, inspect_all, resolve_model_root


def _populate_qwen(directory):
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "model.safetensors", "tokenizer_config.json", "vocab.json",
                 "merges.txt", "preprocessor_config.json"):
        (directory / name).write_bytes(b"asset")
    speech = directory / "speech_tokenizer"
    speech.mkdir()
    for name in ("config.json", "model.safetensors", "preprocessor_config.json"):
        (speech / name).write_bytes(b"asset")


def test_unknown_engine():
    with pytest.raises(ValueError):
        inspect_engine_artifacts("nope")


def test_missing_root_is_honest(monkeypatch, tmp_path):
    for key in ("VOICEOVER_MODEL_ROOT", "TTS_MODEL_ROOT", "HF_HUB_CACHE", "HF_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "fresh-home")
    report = inspect_engine_artifacts("kokoro")
    assert report["status"] == "MODEL_ROOT_NOT_CONFIGURED" and not report["artifact_ready"]
    assert report["inference_verified"] is False and report["model_downloaded"] is False


def test_kokoro_artifacts_use_the_adapter_checkpoint_and_voice_layout(tmp_path):
    model = tmp_path / "Kokoro-82M"
    (model / "voices").mkdir(parents=True)
    (model / "config.json").write_bytes(b"{}")
    (model / "kokoro-v1_0.pth").write_bytes(b"model")
    (model / "voices" / "af_heart.pt").write_bytes(b"voice")
    report = inspect_engine_artifacts("kokoro", model_root=tmp_path, hash_files=True)
    assert report["status"] == "ARTIFACTS_READY" and report["artifact_ready"]
    assert all(artifact["present"] for artifact in report["artifacts"])
    assert report["artifacts"][0]["regular_file_count_estimate"] == 3


def test_qwen_directory_requires_model_processor_and_speech_tokenizer_assets(tmp_path):
    directory = tmp_path / "Qwen3-TTS-12Hz-1.7B-CustomVoice"
    _populate_qwen(directory)
    report = inspect_engine_artifacts("qwen3_tts", model_root=tmp_path)
    assert report["artifact_ready"]
    assert report["artifacts"][0]["regular_file_count_estimate"] == 9


def test_symlink_outside_root_is_rejected(tmp_path):
    model = tmp_path / "Kokoro-82M"
    (model / "voices").mkdir(parents=True)
    (model / "config.json").write_bytes(b"{}")
    (model / "voices" / "af_heart.pt").write_bytes(b"voice")
    outside = tmp_path.parent / "outside-model-v1"
    outside.mkdir(exist_ok=True)
    (outside / "kokoro-v1_0.pth").write_bytes(b"x")
    (model / "kokoro-v1_0.pth").symlink_to(outside / "kokoro-v1_0.pth")
    report = inspect_engine_artifacts("kokoro", model_root=tmp_path)
    assert not report["artifact_ready"]
    assert report["status"] == "ARTIFACTS_MISSING"


def test_env_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEOVER_MODEL_ROOT", str(tmp_path))
    assert resolve_model_root() == tmp_path.resolve()


def test_explicit_root_wins(tmp_path, monkeypatch):
    env = tmp_path / "env"
    explicit = tmp_path / "explicit"
    env.mkdir()
    explicit.mkdir()
    monkeypatch.setenv("VOICEOVER_MODEL_ROOT", str(env))
    assert resolve_model_root(explicit) == explicit.resolve()


def test_all_report_schema_and_flags():
    import jsonschema
    schema = json.loads((Path(__file__).parents[1] / "schemas/tts-artifact-readiness-v1.schema.json").read_text())
    jsonschema.validate(inspect_all(), schema)
    assert all(report["inference_verified"] is False for report in inspect_all()["engines"])


def test_cli_exit_is_nonzero_without_artifacts(tmp_path):
    import subprocess
    import sys
    project = Path(__file__).parents[1]
    result = subprocess.run([sys.executable, "scripts/inspect_tts_artifacts.py", "--model-root", str(tmp_path)],
                            cwd=project, capture_output=True, text=True)
    assert result.returncode == 3
    report = json.loads(result.stdout)
    assert report["ready_engine_count"] == 0
