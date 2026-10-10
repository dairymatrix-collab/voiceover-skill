from __future__ import annotations

import struct
import wave
from dataclasses import dataclass

import pytest

from contracts import (
    ContractError, RouteRequest, check_model_cache, chunk_text, redact_secrets,
    resolve_output_path, route_engine, validate_text, validate_voice_id, validate_wav,
)


@dataclass
class FakeAdapter:
    engine_id: str
    supported_languages: set[str]
    available: bool = True

    def synthesize(self, text: str, voice_id: str) -> bytes:
        return b"fake-audio"


def write_wav(path, *, frames=160, rate=16000, channels=1, width=2):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(b"\x00" * frames * channels * width)


def test_text_validation_strips_outer_whitespace():
    assert validate_text("  Hello world  ") == "Hello world"


@pytest.mark.parametrize("value, code", [("  ", "EMPTY_TEXT"), ("x\x00y", "TEXT_CONTAINS_NUL"), (None, "INVALID_TEXT_TYPE")])
def test_invalid_text_has_stable_error(value, code):
    with pytest.raises(ContractError, match=code):
        validate_text(value)


def test_chunking_respects_limit_and_preserves_normalized_text_order():
    source = "One small sentence. Two small sentence! Three."
    chunks = chunk_text(source, 16)
    assert all(0 < len(chunk) <= 16 for chunk in chunks)
    assert " ".join(chunks) == source


def test_chunking_handles_oversized_token_without_dropping_characters():
    source = "abcdefghijk"
    chunks = chunk_text(source, 4)
    assert chunks == ["abcd", "efgh", "ijk"]
    assert "".join(chunks) == source


@pytest.mark.parametrize("limit", [0, -1, 1.5])
def test_chunking_rejects_invalid_limit(limit):
    with pytest.raises(ContractError, match="INVALID_CHUNK_LIMIT"):
        chunk_text("abc", limit)


def test_router_is_deterministic_and_filters_language_and_availability():
    adapters = [FakeAdapter("zeta", {"en"}), FakeAdapter("alpha", {"EN"}), FakeAdapter("offline", {"en"}, False)]
    assert route_engine(RouteRequest("hello", "en"), adapters).engine_id == "alpha"
    assert route_engine(RouteRequest("hello", "en"), list(reversed(adapters))).engine_id == "alpha"


def test_router_respects_explicit_preference_without_silent_fallback():
    adapters = [FakeAdapter("alpha", {"en"}), FakeAdapter("beta", {"en"})]
    assert route_engine(RouteRequest("hello", "en", "beta"), adapters).engine_id == "beta"
    with pytest.raises(ContractError, match="PREFERRED_ENGINE_UNAVAILABLE"):
        route_engine(RouteRequest("hello", "fr", "beta"), adapters)


def test_router_reports_no_compatible_engine():
    with pytest.raises(ContractError, match="NO_COMPATIBLE_ENGINE"):
        route_engine(RouteRequest("hello", "ur"), [FakeAdapter("alpha", {"en"})])


def test_voice_catalogue_validation():
    assert validate_voice_id("en_voice_1", {"en_voice_1"}) == "en_voice_1"
    with pytest.raises(ContractError, match="VOICE_NOT_FOUND"):
        validate_voice_id("unknown", {"en_voice_1"})
    with pytest.raises(ContractError, match="VOICE_ID_REQUIRED"):
        validate_voice_id("", {"en_voice_1"})


def test_valid_wav_metadata(tmp_path):
    path = tmp_path / "valid.wav"
    write_wav(path, frames=320, rate=16000)
    result = validate_wav(path)
    assert result["sample_rate_hz"] == 16000
    assert result["frames"] == 320
    assert result["duration_seconds"] == pytest.approx(0.02)


def test_wav_rejects_missing_corrupt_and_empty_files(tmp_path):
    with pytest.raises(ContractError, match="AUDIO_FILE_MISSING"):
        validate_wav(tmp_path / "missing.wav")
    corrupt = tmp_path / "corrupt.wav"
    corrupt.write_bytes(b"not a wav")
    with pytest.raises(ContractError, match="AUDIO_INVALID_WAV"):
        validate_wav(corrupt)
    empty = tmp_path / "empty.wav"
    write_wav(empty, frames=0)
    with pytest.raises(ContractError, match="AUDIO_EMPTY"):
        validate_wav(empty)


def test_wav_rejects_unreasonable_sample_rate(tmp_path):
    path = tmp_path / "low_rate.wav"
    write_wav(path, rate=4000)
    with pytest.raises(ContractError, match="AUDIO_INVALID_FORMAT"):
        validate_wav(path)


def test_output_path_stays_inside_root_and_rejects_traversal(tmp_path):
    root = tmp_path / "out"
    root.mkdir()
    assert resolve_output_path(root, "result.wav").parent == root.resolve()
    with pytest.raises(ContractError, match="OUTPUT_PATH_OUTSIDE_ROOT"):
        resolve_output_path(root, "../../outside.wav")


def test_secret_redaction_handles_common_token_shapes():
    raw = "token hf_AbCdEf0123456789 Bearer abc.def.ghi api_key=supersecret"
    redacted = redact_secrets(raw)
    assert "AbCdEf0123456789" not in redacted
    assert "abc.def.ghi" not in redacted
    assert "supersecret" not in redacted
    assert "[REDACTED" in redacted


def test_cache_preflight_is_offline_and_has_stable_errors(tmp_path):
    with pytest.raises(ContractError, match="MODEL_NOT_CACHED"):
        check_model_cache(tmp_path / "missing", ["config.json"])
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ContractError, match="MODEL_CACHE_INCOMPLETE:weights.bin"):
        check_model_cache(model_dir, ["config.json", "weights.bin"])
    (model_dir / "weights.bin").write_bytes(b"fixture")
    check_model_cache(model_dir, ["config.json", "weights.bin"])

# D0-21 negative-case expansion: boundary values and malformed contracts.

@pytest.mark.parametrize("limit", [True, False, None, "4"])
def test_chunking_rejects_non_integer_limits(limit):
    with pytest.raises(ContractError, match="INVALID_CHUNK_LIMIT"):
        chunk_text("abc", limit)


def test_chunking_preserves_unicode_and_handles_whitespace_only_edges():
    source = "  café 世界 🌍  hello  "
    chunks = chunk_text(source, 7)
    assert all(0 < len(chunk) <= 7 for chunk in chunks)
    assert " ".join(chunks) == " ".join(source.split())


def test_router_rejects_malformed_request_and_language_type():
    with pytest.raises(ContractError, match="INVALID_ROUTE_REQUEST"):
        route_engine(None, [FakeAdapter("alpha", {"en"})])
    with pytest.raises(ContractError, match="INVALID_LANGUAGE_TYPE"):
        route_engine(RouteRequest("hello", None), [FakeAdapter("alpha", {"en"})])
    with pytest.raises(ContractError, match="LANGUAGE_REQUIRED"):
        route_engine(RouteRequest("hello", "  "), [FakeAdapter("alpha", {"en"})])


def test_router_rejects_duplicate_or_blank_engine_ids():
    with pytest.raises(ContractError, match="DUPLICATE_ENGINE_ID"):
        route_engine(RouteRequest("hello", "en"), [
            FakeAdapter("alpha", {"en"}), FakeAdapter("alpha", {"en"})
        ])
    with pytest.raises(ContractError, match="INVALID_ENGINE_ID"):
        route_engine(RouteRequest("hello", "en"), [FakeAdapter(" ", {"en"})])


def test_router_does_not_select_unavailable_adapter():
    with pytest.raises(ContractError, match="NO_COMPATIBLE_ENGINE"):
        route_engine(RouteRequest("hello", "en"), [FakeAdapter("alpha", {"en"}, False)])


def test_wav_rejects_truncated_payload(tmp_path):
    path = tmp_path / "truncated.wav"
    write_wav(path, frames=320, rate=16000)
    path.write_bytes(path.read_bytes()[:-8])
    with pytest.raises(ContractError, match="AUDIO_TRUNCATED"):
        validate_wav(path)


@pytest.mark.parametrize("limit", [0, -1, float("nan"), float("inf"), True, "10"])
def test_wav_rejects_invalid_duration_limits(tmp_path, limit):
    path = tmp_path / "valid.wav"
    write_wav(path)
    with pytest.raises(ContractError, match="AUDIO_DURATION_LIMIT_INVALID"):
        validate_wav(path, max_duration_seconds=limit)


def test_wav_rejects_audio_longer_than_configured_limit(tmp_path):
    path = tmp_path / "valid.wav"
    write_wav(path, frames=16000, rate=16000)
    with pytest.raises(ContractError, match="AUDIO_DURATION_INVALID"):
        validate_wav(path, max_duration_seconds=0.5)


def test_output_path_rejects_non_string_and_nul_names(tmp_path):
    root = tmp_path / "out"
    root.mkdir()
    for name in (None, 7, "bad\x00name"):
        with pytest.raises(ContractError, match="INVALID_OUTPUT_NAME"):
            resolve_output_path(root, name)


def test_cache_preflight_rejects_traversal_and_invalid_names(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"fixture")
    with pytest.raises(ContractError, match="CACHE_PATH_OUTSIDE_ROOT"):
        check_model_cache(model_dir, ["../outside.bin"])
    for name in ("", "bad\x00name", None):
        with pytest.raises(ContractError, match="INVALID_CACHE_FILE_NAME"):
            check_model_cache(model_dir, [name])


def test_cache_preflight_rejects_symlink_escape_when_supported(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"fixture")
    link = model_dir / "weights.bin"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")
    with pytest.raises(ContractError, match="CACHE_PATH_OUTSIDE_ROOT"):
        check_model_cache(model_dir, ["weights.bin"])

# D0-23 API/fixture audit: reject malformed adapter contracts deterministically.
@pytest.mark.parametrize("adapter, code", [
    (object(), "INVALID_ENGINE_ID"),
    (FakeAdapter(" alpha ", {"en"}), "INVALID_ENGINE_ID"),
    (type("BadAvailability", (), {"engine_id": "alpha", "available": "yes", "supported_languages": {"en"}})(), "INVALID_ADAPTER_AVAILABILITY"),
    (type("BadLanguages", (), {"engine_id": "alpha", "available": True, "supported_languages": None})(), "INVALID_ADAPTER_LANGUAGES"),
    (type("BadLanguageItem", (), {"engine_id": "alpha", "available": True, "supported_languages": {"en", None}})(), "INVALID_ADAPTER_LANGUAGES"),
])
def test_router_rejects_malformed_adapter_contracts(adapter, code):
    with pytest.raises(ContractError, match=code):
        route_engine(RouteRequest("hello", "en"), [adapter])


@pytest.mark.parametrize("preferred", ["", " ", " alpha ", 7])
def test_router_rejects_malformed_explicit_preference(preferred):
    with pytest.raises(ContractError, match="INVALID_PREFERRED_ENGINE"):
        route_engine(RouteRequest("hello", "en", preferred), [FakeAdapter("alpha", {"en"})])


def test_router_normalizes_supported_language_entries():
    adapter = FakeAdapter("alpha", {" EN "})
    assert route_engine(RouteRequest("hello", "en"), [adapter]) is adapter
