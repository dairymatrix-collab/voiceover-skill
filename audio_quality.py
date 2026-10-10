"""Dependency-free PCM WAV inspection for generated voiceover artifacts.

This module reports measurable signal properties only; it does not assess speech
intelligibility, pronunciation, language correctness, or subjective audio quality.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import io
import math
import wave
from typing import Any, Iterator


class AudioQualityError(ValueError):
    """Raised when an audio artifact is invalid or exceeds safe inspection limits."""


@dataclass(frozen=True)
class AudioQualityReport:
    schema_version: int
    format: str
    channels: int
    sample_width_bytes: int
    sample_rate_hz: int
    frames: int
    duration_seconds: float
    size_bytes: int
    sha256: str
    peak_normalized: float
    rms_normalized: float
    clipping_sample_ratio: float
    silent_frame_ratio: float
    all_silent: bool
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["warnings"] = list(self.warnings)
        return result


def _iter_pcm(payload: bytes, sample_width: int) -> Iterator[int]:
    """Decode PCM lazily so inspection memory stays bounded by input bytes."""
    if sample_width == 1:
        for byte in payload:
            yield byte - 128
        return
    if sample_width == 2:
        if len(payload) % 2:
            raise AudioQualityError("TRUNCATED_PCM_DATA")
        for i in range(0, len(payload), 2):
            yield int.from_bytes(payload[i:i + 2], "little", signed=True)
        return
    if sample_width == 3:
        if len(payload) % 3:
            raise AudioQualityError("TRUNCATED_PCM_DATA")
        for i in range(0, len(payload), 3):
            value = int.from_bytes(payload[i:i + 3], "little", signed=False)
            yield value - (1 << 24) if value & 0x800000 else value
        return
    if sample_width == 4:
        if len(payload) % 4:
            raise AudioQualityError("TRUNCATED_PCM_DATA")
        for i in range(0, len(payload), 4):
            yield int.from_bytes(payload[i:i + 4], "little", signed=True)
        return
    raise AudioQualityError("UNSUPPORTED_PCM_SAMPLE_WIDTH")


def inspect_wav(payload: bytes, *, max_bytes: int = 200_000_000,
                silence_threshold: float = 0.001,
                clipping_threshold: float = 0.999) -> AudioQualityReport:
    """Inspect uncompressed PCM WAV bytes with bounded memory use.

    `silent_frame_ratio` counts frames whose every channel is at or below the
    normalized absolute silence threshold. Clipping ratio counts individual
    samples whose normalized absolute amplitude meets the clipping threshold.
    """
    if not isinstance(payload, bytes) or not payload:
        raise AudioQualityError("AUDIO_EMPTY")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 44:
        raise AudioQualityError("INVALID_MAX_BYTES")
    if len(payload) > max_bytes:
        raise AudioQualityError("AUDIO_TOO_LARGE")
    for value, name in ((silence_threshold, "silence_threshold"),
                         (clipping_threshold, "clipping_threshold")):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise AudioQualityError("INVALID_" + name.upper())
    try:
        with wave.open(io.BytesIO(payload), "rb") as wav:
            channels = wav.getnchannels()
            width = wav.getsampwidth()
            rate = wav.getframerate()
            frames = wav.getnframes()
            compression = wav.getcomptype()
            expected = frames * channels * width
            if channels not in (1, 2):
                raise AudioQualityError("UNSUPPORTED_CHANNEL_COUNT")
            if width not in (1, 2, 3, 4):
                raise AudioQualityError("UNSUPPORTED_PCM_SAMPLE_WIDTH")
            if rate < 8000 or rate > 384000:
                raise AudioQualityError("INVALID_SAMPLE_RATE")
            if frames <= 0 or compression != "NONE":
                raise AudioQualityError("INVALID_WAV_FORMAT")
            if expected > max_bytes or expected > 2**31 - 1:
                raise AudioQualityError("AUDIO_TOO_LARGE")
            raw = wav.readframes(frames)
            if len(raw) != expected:
                raise AudioQualityError("AUDIO_TRUNCATED")
    except AudioQualityError:
        raise
    except (wave.Error, EOFError, OSError) as exc:
        raise AudioQualityError("INVALID_WAV") from exc

    max_amplitude = float((1 << (8 * width - 1)) - 1)
    sample_count = frames * channels
    peak = 0.0
    square_sum = 0.0
    clipped = 0
    silent_frames = 0
    frame_values: list[float] = []
    seen = 0
    for value in _iter_pcm(raw, width):
        amplitude = min(1.0, abs(value) / max_amplitude)
        seen += 1
        peak = max(peak, amplitude)
        square_sum += amplitude ** 2
        if amplitude >= clipping_threshold:
            clipped += 1
        frame_values.append(amplitude)
        if len(frame_values) == channels:
            if all(item <= silence_threshold for item in frame_values):
                silent_frames += 1
            frame_values.clear()
    if seen != sample_count or frame_values:
        raise AudioQualityError("AUDIO_TRUNCATED")
    rms = math.sqrt(square_sum / seen) if seen else 0.0
    clipping_ratio = clipped / seen if seen else 0.0
    silent_ratio = silent_frames / frames
    warnings = []
    if peak == 0.0:
        warnings.append("ALL_SILENT_AUDIO")
    elif silent_ratio >= 0.98:
        warnings.append("NEARLY_ALL_AUDIO_SILENT")
    if clipping_ratio > 0.001:
        warnings.append("CLIPPING_SAMPLES_DETECTED")
    if rms < 0.005 and peak > 0:
        warnings.append("VERY_LOW_RMS_LEVEL")
    duration = frames / rate
    return AudioQualityReport(
        schema_version=1, format="wav-pcm", channels=channels,
        sample_width_bytes=width, sample_rate_hz=rate, frames=frames,
        duration_seconds=round(duration, 9), size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(), peak_normalized=round(peak, 9),
        rms_normalized=round(rms, 9), clipping_sample_ratio=round(clipping_ratio, 9),
        silent_frame_ratio=round(silent_ratio, 9), all_silent=(peak == 0.0),
        warnings=tuple(warnings),
    )
