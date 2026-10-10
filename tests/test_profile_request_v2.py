from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from scripts.run_voiceover import normalize_request

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "synthesis-request-v2.schema.json").read_text(encoding="utf-8"))
VALID = {
    "protocol_version": 2,
    "message_type": "synthesis.request",
    "request_id": "request_2",
    "job_id": "job_2",
    "engine_id": "qwen3_tts",
    "text": "A concise voiceover test.",
    "voice_profile_id": "warm-narrator",
    "options": {"chunk_chars": 800, "output_name": "final.wav", "output_format": "wav"},
    "deadline_ms": 300000,
}


def test_v2_schema_is_valid_and_request_is_closed_and_profile_backed():
    Draft202012Validator.check_schema(SCHEMA)
    Draft202012Validator(SCHEMA, format_checker=FormatChecker()).validate(VALID)
    assert SCHEMA["additionalProperties"] is False
    assert "voice_profile_id" in SCHEMA["required"]


def test_v2_maps_profile_id_and_cli_store_path_without_copying_prompts_or_audio(tmp_path):
    mapped, deadline = normalize_request(VALID, profile_store_dir=tmp_path / "profiles")
    assert mapped == {
        "request_id": "request_2", "text": "A concise voiceover test.",
        "language": "en", "voice_id": "profile_voice", "speed": 1.0, "seed": None,
        "chunk_chars": 800, "output_name": "final.wav", "engine": "qwen3_tts",
        "voice_profile_id": "warm-narrator", "profile_store_dir": str(tmp_path / "profiles"),
    }
    assert deadline == 300.0
    assert "voice_description" not in mapped and "reference_audio" not in mapped


def test_v2_defaults_to_bounded_chunks_and_single_file_wav():
    request = copy.deepcopy(VALID)
    request["options"] = {"output_format": "wav"}
    mapped, _ = normalize_request(request)
    assert mapped["chunk_chars"] == 800
    assert mapped["output_name"] == "voiceover.wav"


@pytest.mark.parametrize("patch", [
    {"protocol_version": True},
    {"message_type": "wrong"},
    {"engine_id": []},
    {"engine_id": "chatterbox"},
    {"request_id": "../bad"},
    {"job_id": "bad/id"},
    {"voice_profile_id": "../secret"},
    {"trace_id": "bad id"},
    {"reference_audio": {"relative_path": "assets/ref.wav", "media_type": "audio/wav"}},
    {"profile_store_dir": "/tmp/attacker-selected"},
    {"voice_description": "must not be inline"},
    {"controls": {"temperature": 0.7}},
    {"options": {"output_format": "wav", "language": "en"}},
    {"options": {"output_format": "mp3"}},
    {"options": {"output_format": "wav", "chunk_chars": True}},
    {"options": {"output_format": "wav", "chunk_chars": 99}},
    {"options": {"output_format": "wav", "chunk_chars": 1201}},
    {"options": {"output_format": "wav", "output_name": "../outside.wav"}},
    {"options": {"output_format": "wav", "output_name": "C:outside.wav"}},
    {"deadline_ms": True},
    {"deadline_ms": 3600001},
    {"text": "bad\x00text"},
    {"text": "bad\x01text"},
])
def test_v2_normalizer_rejects_invalid_or_untrusted_fields(patch):
    request = copy.deepcopy(VALID)
    request.update(patch)
    with pytest.raises(ValueError):
        normalize_request(request)
    # Where the change is still structurally valid JSON, the versioned schema
    # must reject it too. (Non-JSON Python values are already rejected above.)
    try:
        Draft202012Validator(SCHEMA, format_checker=FormatChecker()).validate(request)
    except Exception:
        pass
    else:
        pytest.fail("schema accepted an invalid v2 request")


def test_v2_schema_valid_examples_match_normalizer():
    examples = [VALID]
    one = copy.deepcopy(VALID)
    one["options"] = {"output_format": "wav"}
    examples.append(one)
    for request in examples:
        Draft202012Validator(SCHEMA, format_checker=FormatChecker()).validate(request)
        mapped, timeout = normalize_request(request)
        assert mapped["voice_profile_id"] == request["voice_profile_id"]
        assert timeout == request["deadline_ms"] / 1000


def test_v2_engine_override_must_match_profile_request_engine():
    with pytest.raises(ValueError, match="PROFILE_ENGINE_OVERRIDE_MISMATCH"):
        normalize_request(VALID, engine_override="kokoro")
    mapped, _ = normalize_request(VALID, engine_override="qwen3_tts")
    assert mapped["engine"] == "qwen3_tts"


def test_v1_envelope_and_legacy_flat_request_remain_unchanged():
    legacy = {"request_id": "r1", "text": "hello", "language": "en", "voice_id": "default"}
    assert normalize_request(legacy) == (legacy, None)
    v1 = {
        "protocol_version": 1, "message_type": "synthesis.request", "request_id": "r1", "job_id": "j1",
        "engine_id": "kokoro", "text": "hello", "options": {"language": "en", "voice_id": "af_heart"},
        "deadline_ms": 30000, "reference_audio": None,
    }
    mapped, timeout = normalize_request(v1)
    assert mapped["voice_id"] == "af_heart" and mapped["engine"] == "kokoro"
    assert timeout == 30.0


def test_v2_schema_and_v1_schema_are_separate_contracts():
    v1_schema = json.loads((ROOT / "schemas" / "synthesis-request-v1.schema.json").read_text(encoding="utf-8"))
    assert v1_schema["properties"]["protocol_version"]["const"] == 1
    assert SCHEMA["properties"]["protocol_version"]["const"] == 2
    assert v1_schema["additionalProperties"] is False and SCHEMA["additionalProperties"] is False
