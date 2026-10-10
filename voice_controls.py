"""Strict, source-backed voice modes and controls; no silent option dropping."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ControlSpec:
    kind: str
    minimum: int | float
    maximum: int | float


# Ranges are intentionally conservative. Availability is per engine/mode; the
# common JSON profile schema is broader, but this map is the runtime authority.
CONTROL_SPECS: dict[str, dict[str, dict[str, ControlSpec]]] = {
    "kokoro": {
        "preset": {"speed": ControlSpec("number", 0.5, 2.0)},
    },
    "qwen3_tts": {
        "preset": {
            "top_k": ControlSpec("integer", 1, 100),
            "top_p": ControlSpec("number", 0.01, 1.0),
            "temperature": ControlSpec("number", 0.05, 2.0),
            "repetition_penalty": ControlSpec("number", 1.0, 2.0),
            "max_new_tokens": ControlSpec("integer", 1, 1024),
        },
        "voice_design": {
            "top_k": ControlSpec("integer", 1, 100),
            "top_p": ControlSpec("number", 0.01, 1.0),
            "temperature": ControlSpec("number", 0.05, 2.0),
            "repetition_penalty": ControlSpec("number", 1.0, 2.0),
            "max_new_tokens": ControlSpec("integer", 1, 1024),
        },
    },
    "chatterbox": {
        "preset": {
            "exaggeration": ControlSpec("number", 0.0, 1.0),
            "cfg_weight": ControlSpec("number", 0.0, 1.0),
            "temperature": ControlSpec("number", 0.05, 2.0),
            "repetition_penalty": ControlSpec("number", 1.0, 2.0),
            "min_p": ControlSpec("number", 0.0, 1.0),
            "top_p": ControlSpec("number", 0.01, 1.0),
        },
        "reference_clone": {
            "exaggeration": ControlSpec("number", 0.0, 1.0),
            "cfg_weight": ControlSpec("number", 0.0, 1.0),
            "temperature": ControlSpec("number", 0.05, 2.0),
            "repetition_penalty": ControlSpec("number", 1.0, 2.0),
            "min_p": ControlSpec("number", 0.0, 1.0),
            "top_p": ControlSpec("number", 0.01, 1.0),
        },
    },
}

VOICE_MODES: dict[str, frozenset[str]] = {
    "kokoro": frozenset({"preset"}),
    "qwen3_tts": frozenset({"preset", "voice_design"}),
    "chatterbox": frozenset({"preset", "reference_clone"}),
}

# Only modes that have passed a real WAV smoke are exposed by the installed
# Skill. Other adapter contracts remain research-only and are not routable.
VERIFIED_PROFILE_MODES = frozenset({("kokoro", "preset"), ("qwen3_tts", "voice_design")})


def capabilities(engine_id: str) -> dict[str, Any]:
    """Describe implemented modes and controls without importing model packages."""
    if not isinstance(engine_id, str) or engine_id not in VOICE_MODES:
        raise ValueError("UNKNOWN_ENGINE")
    return {
        "engine_id": engine_id,
        "modes": sorted(VOICE_MODES[engine_id]),
        "controls": {
            mode: {
                name: {"type": spec.kind, "minimum": spec.minimum, "maximum": spec.maximum}
                for name, spec in sorted(CONTROL_SPECS.get(engine_id, {}).get(mode, {}).items())
            }
            for mode in sorted(VOICE_MODES[engine_id])
        },
    }


def validate_controls(engine_id: str, mode: str, controls: Mapping[str, Any] | None) -> dict[str, int | float]:
    """Return normalized controls or raise a stable ValueError code.

    The adapter must pass every returned setting to the model. Unsupported
    settings, booleans-as-numbers, NaN, infinity, and out-of-range values fail.
    """
    if not isinstance(engine_id, str) or engine_id not in VOICE_MODES:
        raise ValueError("UNKNOWN_ENGINE")
    if not isinstance(mode, str) or mode not in VOICE_MODES[engine_id]:
        raise ValueError("VOICE_MODE_UNSUPPORTED")
    if controls is None:
        return {}
    if not isinstance(controls, Mapping):
        raise ValueError("VOICE_CONTROLS_INVALID")
    allowed = CONTROL_SPECS[engine_id][mode]
    result: dict[str, int | float] = {}
    for name, value in controls.items():
        if not isinstance(name, str) or name not in allowed:
            raise ValueError("VOICE_CONTROL_UNSUPPORTED:" + str(name)[:64])
        spec = allowed[name]
        if spec.kind == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("VOICE_CONTROL_INVALID:" + name)
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("VOICE_CONTROL_INVALID:" + name)
            # Avoid a math dependency; comparisons with NaN are false, so
            # explicitly require self-equality before checking the range.
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError("VOICE_CONTROL_INVALID:" + name)
            value = float(value)
        if not spec.minimum <= value <= spec.maximum:
            raise ValueError("VOICE_CONTROL_OUT_OF_RANGE:" + name)
        result[name] = value
    return result


def validate_voice_mode(engine_id: str, mode: str) -> None:
    if not isinstance(engine_id, str) or engine_id not in VOICE_MODES:
        raise ValueError("UNKNOWN_ENGINE")
    if not isinstance(mode, str) or mode not in VOICE_MODES[engine_id]:
        raise ValueError("VOICE_MODE_UNSUPPORTED")
