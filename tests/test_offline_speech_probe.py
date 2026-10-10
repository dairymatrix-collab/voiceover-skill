from __future__ import annotations
import json
from pathlib import Path
import shutil
import subprocess
import sys
import wave
import io

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "offline_speech_probe.py"
sys.path.insert(0, str(ROOT))
from scripts.offline_speech_probe import generate_probe


def test_input_validation(tmp_path):
    for kwargs, expected in [
        ({"text": "  "}, "INVALID_TEXT"),
        ({"text": "hello\x00world"}, "INVALID_TEXT"),
        ({"text": "hello", "language": "xx"}, "UNSUPPORTED_ESPEAK_LANGUAGE"),
        ({"text": "hello", "speed": True}, "INVALID_SPEED"),
        ({"text": "hello", "speed": 451}, "INVALID_SPEED"),
        ({"text": "hello", "timeout_seconds": 0}, "INVALID_TIMEOUT"),
    ]:
        args = {"output": tmp_path / "out.wav", **kwargs}
        with pytest.raises(ValueError, match=expected):
            generate_probe(**args)


def test_rejects_existing_output_without_overwrite(tmp_path):
    output = tmp_path / "out.wav"
    output.write_bytes(b"keep")
    with pytest.raises(ValueError, match="OUTPUT_ALREADY_EXISTS"):
        generate_probe("hello world", output)
    assert output.read_bytes() == b"keep"


def test_rejects_symlink_output(tmp_path):
    target = tmp_path / "target.wav"
    target.write_bytes(b"keep")
    link = tmp_path / "link.wav"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="OUTPUT_PATH_IS_SYMLINK"):
        generate_probe("hello world", link, overwrite=True)
    assert target.read_bytes() == b"keep"


def test_missing_executable_is_blocked(tmp_path):
    result = generate_probe("hello world", tmp_path / "out.wav", executable=str(tmp_path / "missing"))
    assert result["status"] == "BLOCKED"
    assert result["error"] == "ESPEAK_LAUNCH_FAILED"
    assert result["inference_verified"] is False
    assert result["speech_output_verified"] is False


def test_actual_espeak_generation_when_available(tmp_path):
    if not (shutil.which("espeak-ng") or shutil.which("espeak")):
        pytest.skip("eSpeak executable not installed")
    output = tmp_path / "baseline.wav"
    result = generate_probe("This is a local offline speech generation test.", output)
    assert result["status"] == "PASS", result
    assert result["speech_output_verified"] is True
    assert result["neural_engine"] is False
    assert result["inference_verified"] is False
    assert output.is_file()
    with wave.open(io.BytesIO(output.read_bytes()), "rb") as wav:
        assert wav.getnframes() > 0
        assert wav.getframerate() >= 8000
    assert result["audio_quality"]["all_silent"] is False
    assert result["sha256"]


def test_cli_generates_report_without_transcript(tmp_path):
    if not (shutil.which("espeak-ng") or shutil.which("espeak")):
        pytest.skip("eSpeak executable not installed")
    output, report = tmp_path / "speech.wav", tmp_path / "report.json"
    child = subprocess.run([sys.executable, str(SCRIPT), "--text", "A short test.", "--output", str(output), "--report", str(report)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
    assert child.returncode == 0, child.stdout + child.stderr
    data = json.loads(child.stdout)
    assert data["status"] == "PASS"
    assert json.loads(report.read_text())["sha256"] == data["sha256"]
    assert "A short test" not in report.read_text()


def test_cli_refuses_report_collision_with_audio(tmp_path):
    output = tmp_path / "speech.wav"
    child = subprocess.run([sys.executable, str(SCRIPT), "--text", "A short test.", "--output", str(output), "--report", str(output)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
    assert child.returncode == 2
    assert json.loads(child.stdout)["error"] == "REPORT_PATH_EQUALS_AUDIO_PATH"
    assert not output.exists()


def test_schema_accepts_pass_and_rejects_false_neural_claim():
    from jsonschema import Draft202012Validator
    schema = json.loads((ROOT / "schemas" / "offline-speech-probe-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    good = {"schema_version": 1, "status": "PASS", "engine_id": "espeak_offline",
            "engine_kind": "system_formant_tts", "diagnostic_only": True,
            "neural_engine": False, "inference_verified": False, "speech_output_verified": True,
            "text_characters": 10, "language": "en", "speed_wpm": 165,
            "output_file": "x.wav", "sha256": "a" * 64, "elapsed_ms": 10,
            "audio_quality": {"all_silent": False}, "limitations": []}
    assert validator.is_valid(good)
    bad = dict(good, neural_engine=True)
    assert not validator.is_valid(bad)
    bad = dict(good, inference_verified=True)
    assert not validator.is_valid(bad)
