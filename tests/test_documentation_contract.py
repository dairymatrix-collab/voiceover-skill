"""Regression checks that key README claims stay aligned with shipped artifacts."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ipc_schema_dependency_is_declared_and_documented():
    requirements = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    module = (ROOT / "ipc_contract.py").read_text(encoding="utf-8")
    assert "jsonschema==4.26.0" in requirements
    assert "from jsonschema import Draft202012Validator" in module
    assert "The IPC validator uses `jsonschema==4.26.0`, pinned in `requirements-dev.txt`" in readme


def test_dev_manifest_and_readme_cover_adapter_test_dependencies():
    requirements = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "numpy>=" in requirements and "soundfile>=" in requirements
    assert "`numpy`/`soundfile`" in readme
    assert "one Kokoro English CPU smoke profile" in readme
    assert "one Qwen3-TTS VoiceDesign English CPU profile" in readme


def test_readme_describes_manifest_coverage_without_claiming_self_hashing():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "`FINAL_TEST_EVIDENCE_REPORT.md`" in readme
    assert "does not hash itself or the ZIP container" in readme


def test_readme_calls_evidence_report_chronological():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "chronological task-by-task test evidence" in readme


def test_documentation_does_not_claim_production_supervisor_exists():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "does not implement a production IPC supervisor" in readme
    assert "actual TTS inference" in readme


def test_offline_readiness_guide_matches_adapter_assets_and_separate_gates():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "OFFLINE_INSTALL_AND_READINESS.md").read_text(encoding="utf-8")
    assert "OFFLINE_INSTALL_AND_READINESS.md" in readme
    assert "kokoro-v1_0.pth" in guide and "voices/*.pt" in guide
    assert "speech_tokenizer/model.safetensors" in guide
    assert "Qwen3-TTS-12Hz-1.7B-VoiceDesign" in guide
    assert "not exposed by the Skill setup/download/profile/synthesis CLIs" in guide
    assert "model loading" in guide and "inference_verified" in guide
    assert "inspected model root" in guide and "outside**" in guide
    assert "runtime model-cache setting" in guide and "`--model-root`" in guide
    assert "does not disable downloads" in guide


def test_model_root_cache_precedence_and_kokoro_smoke_are_documented():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "OFFLINE_INSTALL_AND_READINESS.md").read_text(encoding="utf-8")
    cli = (ROOT / "scripts" / "preflight_tts_install.py").read_text(encoding="utf-8")
    assert "effective Hugging Face Hub cache" in readme
    assert "An explicit root is never silently replaced" in readme
    assert "An explicit `--model-root` is strict" in guide
    assert "seven objective checks passed" in guide
    assert "custom voice design" in guide
    assert "effective Hugging Face Hub cache" in cli
