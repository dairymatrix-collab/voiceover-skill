"""Model-free contract primitives for the voiceover skill's local test harness.

This is validation scaffolding, not production TTS integration code.
Only Python's standard library is required.
"""
from __future__ import annotations

import math
import re
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol


class ContractError(ValueError):
    """A deterministic input/contract validation error."""


class TTSAdapter(Protocol):
    engine_id: str
    supported_languages: set[str]
    available: bool

    def synthesize(self, text: str, voice_id: str) -> bytes: ...


@dataclass(frozen=True)
class RouteRequest:
    text: str
    language: str
    preferred_engine: str | None = None


def validate_text(text: str) -> str:
    if not isinstance(text, str):
        raise ContractError("INVALID_TEXT_TYPE")
    if not text.strip():
        raise ContractError("EMPTY_TEXT")
    if "\x00" in text:
        raise ContractError("TEXT_CONTAINS_NUL")
    return text.strip()


def chunk_text(text: str, max_chars: int) -> list[str]:
    """Split text on whitespace near sentence/word boundaries; preserve text order."""
    text = validate_text(text)
    # bool is a subclass of int in Python, but True/False are not meaningful limits.
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
        raise ContractError("INVALID_CHUNK_LIMIT")
    words = re.findall(r"\S+", text)
    chunks: list[str] = []
    current = ""
    for word in words:
        if len(word) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            # Oversized token is split deterministically; no characters are dropped.
            for i in range(0, len(word), max_chars):
                piece = word[i:i + max_chars]
                if len(piece) == max_chars:
                    chunks.append(piece)
                else:
                    current = piece
            continue
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = word
    if current:
        chunks.append(current)
    return chunks


def route_engine(request: RouteRequest, adapters: Iterable[TTSAdapter]) -> TTSAdapter:
    """Select a ready adapter; an explicit preference never silently falls back."""
    if not isinstance(request, RouteRequest):
        raise ContractError("INVALID_ROUTE_REQUEST")
    text = validate_text(request.text)
    if not isinstance(request.language, str):
        raise ContractError("INVALID_LANGUAGE_TYPE")
    language = request.language.strip().lower()
    if not language:
        raise ContractError("LANGUAGE_REQUIRED")
    adapter_list = list(adapters)
    ids: list[str] = []
    for adapter in adapter_list:
        engine_id = getattr(adapter, "engine_id", None)
        if not isinstance(engine_id, str) or not engine_id.strip() or engine_id != engine_id.strip():
            raise ContractError("INVALID_ENGINE_ID")
        if not hasattr(adapter, "available") or not isinstance(adapter.available, bool):
            raise ContractError("INVALID_ADAPTER_AVAILABILITY")
        languages = getattr(adapter, "supported_languages", None)
        if (not isinstance(languages, (set, frozenset, list, tuple))
                or any(not isinstance(item, str) or not item.strip() for item in languages)):
            raise ContractError("INVALID_ADAPTER_LANGUAGES")
        ids.append(engine_id)
    if len(ids) != len(set(ids)):
        raise ContractError("DUPLICATE_ENGINE_ID")
    ready = [a for a in adapter_list if a.available and language in {x.strip().lower() for x in a.supported_languages}]
    if request.preferred_engine is not None:
        if (not isinstance(request.preferred_engine, str)
                or not request.preferred_engine.strip()
                or request.preferred_engine != request.preferred_engine.strip()):
            raise ContractError("INVALID_PREFERRED_ENGINE")
        for adapter in ready:
            if adapter.engine_id == request.preferred_engine:
                return adapter
        raise ContractError("PREFERRED_ENGINE_UNAVAILABLE")
    if not ready:
        raise ContractError("NO_COMPATIBLE_ENGINE")
    # Stable deterministic order independent of caller's list order.
    return sorted(ready, key=lambda a: a.engine_id)[0]


def validate_voice_id(voice_id: str, catalogue: set[str]) -> str:
    if not isinstance(voice_id, str) or not voice_id.strip():
        raise ContractError("VOICE_ID_REQUIRED")
    if voice_id not in catalogue:
        raise ContractError("VOICE_NOT_FOUND")
    return voice_id


def validate_wav(path: str | Path, *, max_duration_seconds: float = 3600.0) -> dict[str, float | int]:
    """Validate WAV readability, PCM frame metadata, duration and non-empty content."""
    if (isinstance(max_duration_seconds, bool)
            or not isinstance(max_duration_seconds, (int, float))
            or not math.isfinite(max_duration_seconds)
            or max_duration_seconds <= 0):
        raise ContractError("AUDIO_DURATION_LIMIT_INVALID")
    file_path = Path(path)
    if not file_path.is_file():
        raise ContractError("AUDIO_FILE_MISSING")
    try:
        with wave.open(str(file_path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frames = wav.getnframes()
            compression = wav.getcomptype()
            duration = frames / sample_rate if sample_rate else 0
            raw = wav.readframes(frames)
    except (wave.Error, EOFError, OSError) as exc:
        raise ContractError("AUDIO_INVALID_WAV") from exc
    if channels < 1 or sample_width not in (1, 2, 3, 4) or sample_rate < 8000:
        raise ContractError("AUDIO_INVALID_FORMAT")
    if compression != "NONE":
        raise ContractError("AUDIO_UNSUPPORTED_COMPRESSION")
    if frames <= 0 or not raw:
        raise ContractError("AUDIO_EMPTY")
    expected_bytes = frames * channels * sample_width
    if len(raw) != expected_bytes:
        raise ContractError("AUDIO_TRUNCATED")
    if not math.isfinite(duration) or duration > max_duration_seconds:
        raise ContractError("AUDIO_DURATION_INVALID")
    return {"channels": channels, "sample_width_bytes": sample_width,
            "sample_rate_hz": sample_rate, "frames": frames, "duration_seconds": duration}


def resolve_output_path(root: str | Path, requested_name: str) -> Path:
    """Resolve a user output name beneath root, rejecting path traversal."""
    root_path = Path(root).resolve()
    if not isinstance(requested_name, str) or not requested_name or "\x00" in requested_name:
        raise ContractError("INVALID_OUTPUT_NAME")
    candidate = (root_path / requested_name).resolve()
    if candidate != root_path and root_path not in candidate.parents:
        raise ContractError("OUTPUT_PATH_OUTSIDE_ROOT")
    return candidate


def redact_secrets(text: str) -> str:
    """Redact common token patterns before diagnostics are persisted."""
    patterns = [
        (r"(?i)(hf_[A-Za-z0-9]{10,})", "[REDACTED_HF_TOKEN]"),
        (r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[REDACTED]"),
        (r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]"),
    ]
    result = text
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result)
    return result


def check_model_cache(model_dir: str | Path, required_files: Iterable[str]) -> None:
    """Offline preflight: never downloads; reports deterministic cache errors."""
    directory = Path(model_dir).resolve()
    if not directory.is_dir():
        raise ContractError("MODEL_NOT_CACHED")
    names = list(required_files)
    for name in names:
        if not isinstance(name, str) or not name or "\x00" in name:
            raise ContractError("INVALID_CACHE_FILE_NAME")
        candidate = (directory / name).resolve()
        if candidate != directory and directory not in candidate.parents:
            raise ContractError("CACHE_PATH_OUTSIDE_ROOT")
    missing = [name for name in names if not (directory / name).resolve().is_file()]
    if missing:
        raise ContractError("MODEL_CACHE_INCOMPLETE:" + ",".join(sorted(missing)))
