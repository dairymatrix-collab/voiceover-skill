"""Regression tests for public synthesis envelopes and the internal worker contract."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.run_voiceover import normalize_request

ROOT = Path(__file__).resolve().parents[1]


def envelope(**changes):
    data = {
        "protocol_version": 1, "message_type": "synthesis.request",
        "request_id": "req_smoke_01", "job_id": "job_smoke_01",
        "engine_id": "kokoro", "text": "A short real inference test.",
        "options": {"language": "en", "voice_id": "af_heart", "speed": 1.0, "output_format": "wav"},
        "deadline_ms": 120000, "reference_audio": None,
    }
    data.update(changes)
    return data


def test_public_envelope_maps_into_pipeline_request_fields():
    mapped, deadline = normalize_request(envelope())
    assert mapped == {"request_id": "req_smoke_01", "text": "A short real inference test.",
                      "language": "en", "voice_id": "af_heart", "speed": 1.0,
                      "seed": None, "engine": "kokoro"}
    assert deadline == 120.0


def test_cli_engine_override_wins_over_envelope_engine():
    mapped, _ = normalize_request(envelope(engine_id="qwen3_tts"), "kokoro")
    assert mapped["engine"] == "kokoro"


@pytest.mark.parametrize("engine_id", ["qwen3_tts", "chatterbox"])
def test_v1_rejects_unverified_engines(engine_id):
    with pytest.raises(ValueError, match="ENGINE_PATH_NOT_VERIFIED"):
        normalize_request(envelope(engine_id=engine_id))


def test_legacy_flat_request_remains_supported():
    raw = {"request_id": "r1", "text": "hello", "language": "en", "voice_id": "default"}
    mapped, deadline = normalize_request(raw)
    assert mapped == raw and deadline is None


def test_deadline_is_converted_from_milliseconds():
    _, deadline = normalize_request(envelope(deadline_ms=2500))
    assert deadline == 2.5


@pytest.mark.parametrize("changes", [
    {"protocol_version": 2}, {"message_type": "wrong"}, {"engine_id": "unknown"},
    {"deadline_ms": True}, {"deadline_ms": 0}, {"request_id": "bad id"},
    {"job_id": "bad/id"}, {"reference_audio": {"relative_path": "voice.wav", "media_type": "audio/wav"}},
    {"options": {"language": "en", "voice_id": "v", "output_format": "mp3"}},
    {"options": {"language": "en", "voice_id": "v", "extra": 1}},
    {"options": {"language": "en"}}, {"unexpected": "field"},
])
def test_invalid_envelope_fails_closed(changes):
    with pytest.raises(ValueError):
        normalize_request(envelope(**changes))


def test_envelope_seed_is_preserved():
    mapped, _ = normalize_request(envelope(options={"language": "en", "voice_id": "af_heart", "seed": 8}))
    assert mapped["seed"] == 8


def test_real_runner_reports_missing_engine_not_invalid_envelope(tmp_path):
    request = tmp_path / "request.json"
    request.write_text(json.dumps(envelope()), encoding="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/run_voiceover.py"),
                             "--request", str(request), "--output-dir", str(tmp_path / "out"),
                             "--engine", "kokoro", "--timeout-seconds", "10"],
                            capture_output=True, text=True, timeout=20)
    data = json.loads(result.stdout)
    assert result.returncode == 2
    assert data["error"] in {"PREFERRED_ENGINE_UNAVAILABLE", "NO_COMPATIBLE_ENGINE"}
    assert data["error"] != "INVALID_REQUEST_JSON"
    assert not (tmp_path / "out" / "voiceover.wav").exists()
