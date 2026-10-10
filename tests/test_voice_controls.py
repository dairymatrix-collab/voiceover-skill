from __future__ import annotations

import json
import math

import pytest

from voice_controls import capabilities, validate_controls, validate_voice_mode


def test_capabilities_are_json_safe_and_only_advertise_implemented_modes():
    reports = {engine: capabilities(engine) for engine in ("kokoro", "qwen3_tts", "chatterbox")}
    json.dumps(reports, allow_nan=False)
    assert reports["kokoro"]["modes"] == ["preset"]
    assert reports["qwen3_tts"]["modes"] == ["preset", "voice_design"]
    assert reports["chatterbox"]["modes"] == ["preset", "reference_clone"]


def test_kokoro_exposes_only_speed_and_preserves_valid_value():
    assert validate_controls("kokoro", "preset", {"speed": 1.25}) == {"speed": 1.25}
    with pytest.raises(ValueError, match="VOICE_CONTROL_UNSUPPORTED"):
        validate_controls("kokoro", "preset", {"pitch": 1})


@pytest.mark.parametrize("engine,mode,controls", [
    ("qwen3_tts", "voice_design", {"top_k": 40, "top_p": 0.9, "temperature": 0.8,
                                    "repetition_penalty": 1.05, "max_new_tokens": 256}),
    ("chatterbox", "reference_clone", {"exaggeration": 0.7, "cfg_weight": 0.3,
                                         "temperature": 0.8, "repetition_penalty": 1.2,
                                         "min_p": 0.05, "top_p": 1.0}),
])
def test_documented_controls_are_valid(engine, mode, controls):
    assert validate_controls(engine, mode, controls) == controls


def test_qwen_custom_voice_preset_has_its_own_generation_controls():
    assert validate_controls("qwen3_tts", "preset", {"temperature": 1.0}) == {"temperature": 1.0}


@pytest.mark.parametrize("engine,mode", [
    ("qwen3_tts", "reference_clone"),
    ("chatterbox", "voice_design"),
    ("kokoro", "voice_design"),
    ("kokoro", "reference_clone"),
])
def test_unimplemented_voice_modes_fail_closed(engine, mode):
    with pytest.raises(ValueError, match="VOICE_MODE_UNSUPPORTED"):
        validate_voice_mode(engine, mode)


@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf"), float("-inf"), "0.5", None])
def test_numeric_controls_reject_bool_nonfinite_and_wrong_types(value):
    with pytest.raises(ValueError, match="VOICE_CONTROL_INVALID"):
        validate_controls("qwen3_tts", "voice_design", {"temperature": value})


@pytest.mark.parametrize("control,value", [
    ("temperature", 0.049), ("temperature", 2.001),
    ("top_p", 0), ("top_p", 1.001),
    ("repetition_penalty", 0.99), ("repetition_penalty", 2.01),
    ("top_k", 0), ("top_k", 101),
    ("max_new_tokens", 1025),
])
def test_numeric_controls_reject_out_of_range(control, value):
    with pytest.raises(ValueError, match="VOICE_CONTROL_OUT_OF_RANGE"):
        validate_controls("qwen3_tts", "voice_design", {control: value})


def test_integer_controls_reject_float_even_when_integral():
    with pytest.raises(ValueError, match="VOICE_CONTROL_INVALID"):
        validate_controls("qwen3_tts", "voice_design", {"top_k": 32.0})


def test_chatterbox_rejects_speed_and_qwen_rejects_exaggeration():
    with pytest.raises(ValueError, match="VOICE_CONTROL_UNSUPPORTED"):
        validate_controls("chatterbox", "preset", {"speed": 1.2})
    with pytest.raises(ValueError, match="VOICE_CONTROL_UNSUPPORTED"):
        validate_controls("qwen3_tts", "voice_design", {"exaggeration": 0.5})


def test_unknown_engine_and_non_mapping_controls_rejected():
    with pytest.raises(ValueError, match="UNKNOWN_ENGINE"):
        capabilities("unknown")
    with pytest.raises(ValueError, match="VOICE_CONTROLS_INVALID"):
        validate_controls("kokoro", "preset", [1])
