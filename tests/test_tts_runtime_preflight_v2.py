from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import jsonschema
import pytest

import tts_runtime_preflight as preflight

ROOT = Path(__file__).resolve().parents[1]
V2_SCHEMA = json.loads((ROOT / "schemas/tts-runtime-preflight-v2.schema.json").read_text())
ARTIFACT_SCHEMA = json.loads((ROOT / "schemas/tts-artifact-readiness-v2.schema.json").read_text())


def _candidate(path, modules=None):
    modules = modules or {"kokoro": True, "torch": True, "numpy": True, "soundfile": True,
                          "chatterbox": True, "qwen_tts": True, "transformers": True,
                          "torchaudio": True, "accelerate": True, "librosa": True,
                          "onnxruntime": True, "einops": True, "safetensors": True}
    return {"executable": str(path), "status": "PASS", "supported_by_project_policy": True,
            "version": [3, 12, 3], "version_text": "3.12.3", "modules": modules}


def _ready_interpreters(monkeypatch):
    candidate = _candidate("/test/python")
    interpreter_report = {
        "schema_version": 1, "diagnostic_only": True, "installation_performed": False,
        "model_downloaded": False, "inference_verified": False, "candidate_count": 1,
        "selected_interpreter": candidate["executable"], "selected_python_version": candidate["version_text"],
        "supported_policy": {"minimum": "3.10", "maximum": "3.12"},
        "interpreters": [candidate], "status": "READY_FOR_ENGINE_PREFLIGHT",
    }
    monkeypatch.setattr(preflight, "discover_interpreters", lambda extra_candidates=(): {
        **interpreter_report})
    monkeypatch.setattr(preflight, "probe_network", lambda: [])


def test_default_runtime_preflight_keeps_v1_shape_and_alias_is_normalized(monkeypatch):
    _ready_interpreters(monkeypatch)
    report = preflight.collect_preflight("Kokoro-TTS", check_network=False)
    assert report["schema_version"] == 1
    assert report["engine"] == "kokoro"
    assert "artifact_readiness" not in report
    assert report["inference_verified"] is False


def test_artifact_integration_is_opt_in_and_does_not_overwrite_prerequisite_status(tmp_path, monkeypatch):
    _ready_interpreters(monkeypatch)
    report = preflight.collect_preflight("qwen-tts", check_network=False, include_artifacts=True,
                                         model_root=tmp_path)
    assert report["schema_version"] == 2
    assert report["engine"] == "qwen3_tts"
    assert report["status"] == "ENGINE_PREREQUISITES_PRESENT"
    assert report["artifact_readiness"]["status"] == "MODEL_ROOT_NOT_CONFIGURED" or report["artifact_readiness"]["status"] == "ARTIFACTS_MISSING"
    assert report["artifact_readiness"]["artifact_ready"] is False
    assert report["inference_verified"] is False


def test_runtime_and_nested_artifact_reports_conform_to_both_v2_schemas(tmp_path, monkeypatch):
    _ready_interpreters(monkeypatch)
    model = tmp_path / "Kokoro-82M"
    (model / "voices").mkdir(parents=True)
    (model / "config.json").write_bytes(b"config")
    (model / "kokoro-v1_0.pth").write_bytes(b"model")
    (model / "voices" / "af_heart.pt").write_bytes(b"voice")
    report = preflight.collect_preflight("kokoro", check_network=False, include_artifacts=True,
                                         model_root=tmp_path, hash_artifacts=True)
    jsonschema.Draft202012Validator.check_schema(V2_SCHEMA)
    jsonschema.Draft202012Validator.check_schema(ARTIFACT_SCHEMA)
    jsonschema.validate(report, V2_SCHEMA)
    jsonschema.validate(report["artifact_readiness"], ARTIFACT_SCHEMA)
    assert report["artifact_readiness"]["artifact_ready"] is True
    assert report["artifact_readiness"]["inference_verified"] is False


def test_voice_design_variant_is_reflected_in_schema_valid_artifact_report(tmp_path, monkeypatch):
    _ready_interpreters(monkeypatch)
    model = tmp_path / "Qwen3-TTS-12Hz-1.7B-VoiceDesign"
    model.mkdir()
    for name in ("config.json", "model.safetensors", "tokenizer_config.json", "vocab.json",
                 "merges.txt", "preprocessor_config.json"):
        (model / name).write_bytes(b"asset")
    tokenizer = model / "speech_tokenizer"
    tokenizer.mkdir()
    for name in ("config.json", "model.safetensors", "preprocessor_config.json"):
        (tokenizer / name).write_bytes(b"asset")

    report = preflight.collect_preflight("qwen3_tts", check_network=False,
                                         include_artifacts=True, model_root=tmp_path,
                                         model_variant="voice_design")
    jsonschema.validate(report, V2_SCHEMA)
    jsonschema.validate(report["artifact_readiness"], ARTIFACT_SCHEMA)
    assert report["artifact_readiness"]["artifact_ready"] is True
    assert report["artifact_readiness"]["artifacts"][0]["artifact_id"] == "qwen_voice_design_model"
    assert report["artifact_readiness"]["inference_verified"] is False


def test_artifact_preflight_options_must_be_booleans():
    with pytest.raises(ValueError):
        preflight.collect_preflight("kokoro", check_network=False, include_artifacts=1)
    with pytest.raises(ValueError):
        preflight.collect_preflight("kokoro", check_network=False, hash_artifacts="yes")
    with pytest.raises(ValueError, match="model_variant requires include_artifacts"):
        preflight.collect_preflight("qwen3_tts", check_network=False,
                                    model_variant="voice_design")


def test_cli_include_artifacts_emits_v2_and_uses_exit_four_for_artifact_block(tmp_path):
    result = subprocess.run(
        [sys.executable, "scripts/preflight_tts_install.py", "--engine", "kokoro-tts", "--skip-network",
         "--include-artifacts", "--model-root", str(tmp_path), "--pretty"],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    report = json.loads(result.stdout)
    assert report["schema_version"] == 2
    assert report["engine"] == "kokoro"
    assert report["artifact_readiness"]["inference_verified"] is False
    assert result.returncode in (2, 3, 4)
    if result.returncode == 4:
        assert report["status"] == "ENGINE_PREREQUISITES_PRESENT"
        assert report["artifact_readiness"]["artifact_ready"] is False


def test_cli_refuses_report_path_inside_model_root(tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    result = subprocess.run(
        [sys.executable, "scripts/preflight_tts_install.py", "--engine", "kokoro", "--skip-network",
         "--include-artifacts", "--model-root", str(root), "--report", str(root / "report.json")],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2
    assert "REPORT_DESTINATION_INSIDE_MODEL_ROOT" in result.stderr
    assert not (root / "report.json").exists()


def test_cli_returns_four_when_engine_prerequisites_pass_but_artifacts_do_not(monkeypatch):
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import preflight_tts_install as cli

    monkeypatch.setattr(sys, "argv", ["preflight_tts_install.py", "--engine", "kokoro",
                                       "--skip-network", "--include-artifacts"])
    monkeypatch.setattr(cli, "collect_preflight", lambda *args, **kwargs: {
        "schema_version": 2, "engine": "kokoro", "status": "ENGINE_PREREQUISITES_PRESENT",
        "artifact_readiness": {"artifact_ready": False}, "diagnostic_only": True,
        "installation_performed": False, "model_downloaded": False, "inference_verified": False,
        "interpreter_report": {}, "selected_engine_interpreter": "/test/python", "required_distributions": [],
        "missing_engine_modules": [], "network": [], "network_ready": None, "wheelhouse": None, "notes": []})
    assert cli.main() == 4
