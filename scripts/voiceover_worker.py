#!/usr/bin/env python3
"""Private worker: reads one JSON request on stdin and writes one JSON result."""
from __future__ import annotations
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from voiceover_pipeline import PipelineError, PipelineRequest, run_pipeline
from tts_engine_adapters import adapters_for_profile, default_adapters
from voice_profile_store import ProfileStoreError, default_store_dir, load_profile


def _resolve_profile(raw: dict) -> tuple[dict | None, Path | None]:
    """Resolve profile data locally; public requests never carry voice prompts or paths."""
    profile_id = raw.pop("voice_profile_id", None)
    store_value = raw.pop("profile_store_dir", None)
    if profile_id is None:
        if store_value is not None:
            raise PipelineError("PROFILE_STORE_WITHOUT_PROFILE")
        return None, None
    if not isinstance(profile_id, str):
        raise PipelineError("INVALID_VOICE_PROFILE_ID")
    if store_value is None:
        store = default_store_dir()
    elif isinstance(store_value, str) and store_value.strip():
        store = Path(store_value).expanduser()
    else:
        raise PipelineError("PROFILE_STORE_PATH_INVALID")
    try:
        profile = load_profile(store, profile_id)
    except ProfileStoreError as exc:
        raise PipelineError(exc.code) from exc
    requested_engine = raw.get("engine")
    if requested_engine not in (None, profile["engine_id"]):
        raise PipelineError("PROFILE_ENGINE_OVERRIDE_MISMATCH")
    raw["engine"] = profile["engine_id"]
    raw["language"] = profile["language"]
    if profile["mode"] == "voice_design":
        raw["voice_id"] = "profile_voice"
    elif profile["mode"] == "reference_clone":
        # ChatterboxAdapter reads the private reference path from the profile store.
        raw["voice_id"] = "default"
    else:
        raw["voice_id"] = profile["voice_id"]
    raw["speed"] = profile["controls"].get("speed", 1.0) if profile["engine_id"] == "kokoro" else 1.0
    raw["seed"] = None
    raw["voice_profile_id"] = profile_id
    raw["voice_mode"] = profile["mode"]
    return profile, store


def main() -> int:
    try:
        raw = json.load(sys.stdin)
        if not isinstance(raw, dict):
            raise PipelineError("INVALID_REQUEST_JSON")
        output_dir = raw.pop("output_dir", None)
        if not isinstance(output_dir, str) or not output_dir:
            raise PipelineError("INVALID_OUTPUT_DIR")
        profile, profile_store = _resolve_profile(raw)
        engine = raw.pop("engine", None)
        if engine is not None:
            raw["preferred_engine"] = engine
        request = PipelineRequest(**raw)
        # Third-party TTS packages may print progress/log chatter to stdout.
        # Keep the worker IPC channel reserved for exactly one JSON response.
        with redirect_stdout(sys.stderr):
            adapters = adapters_for_profile(profile, profile_store) if profile is not None else default_adapters()
            result = run_pipeline(request, adapters, output_dir)
        print(json.dumps({"ok": True, "result": result.__dict__}, sort_keys=True))
        return 0
    except PipelineError as exc:
        print(json.dumps({"ok": False, "error": exc.code, "detail": exc.detail}, sort_keys=True))
        return 2
    except (TypeError, ValueError, json.JSONDecodeError):
        print(json.dumps({"ok": False, "error": "INVALID_REQUEST_JSON"}, sort_keys=True))
        return 2
    except Exception:
        # Do not emit exception strings/tracebacks which can leak paths or secrets.
        print(json.dumps({"ok": False, "error": "WORKER_INTERNAL_ERROR"}, sort_keys=True))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
