"""Model-independent orchestration for real TTS adapters.

This module does not pretend to implement Qwen3-TTS, Chatterbox, or Kokoro.
A deployment must inject a real adapter that performs inference and returns WAV bytes.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib, json, math, os, re, tempfile, wave
from pathlib import Path
from typing import Protocol, Sequence

class PipelineError(RuntimeError):
    """Stable pipeline error with a machine-readable code."""
    def __init__(self, code: str, detail: str = ""):
        self.code, self.detail = code, detail
        super().__init__(code if not detail else f"{code}:{detail}")

class SynthesisAdapter(Protocol):
    engine_id: str
    supported_languages: set[str]
    def synthesize_wav(self, text: str, *, language: str, voice_id: str,
                       speed: float = 1.0, seed: int | None = None) -> bytes: ...

@dataclass(frozen=True)
class PipelineRequest:
    request_id: str
    text: str
    language: str
    voice_id: str
    output_name: str = "voiceover.wav"
    chunk_chars: int = 1200
    speed: float = 1.0
    seed: int | None = None
    preferred_engine: str | None = None
    voice_profile_id: str | None = None
    voice_mode: str | None = None

@dataclass(frozen=True)
class AudioInfo:
    channels: int
    sample_width: int
    sample_rate: int
    frames: int
    duration_seconds: float

@dataclass(frozen=True)
class PipelineResult:
    request_id: str
    engine_id: str
    output_path: str
    sha256: str
    size_bytes: int
    duration_seconds: float
    chunks: int
    manifest_path: str

def _validate_id(value: str, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise PipelineError("INVALID_" + field.upper())
    return value

def validate_request(request: PipelineRequest) -> PipelineRequest:
    if not isinstance(request, PipelineRequest): raise PipelineError("INVALID_REQUEST_TYPE")
    _validate_id(request.request_id, "request_id")
    if not isinstance(request.text, str) or not request.text.strip() or "\x00" in request.text:
        raise PipelineError("INVALID_TEXT")
    if len(request.text) > 1_000_000: raise PipelineError("TEXT_TOO_LONG")
    if not isinstance(request.language, str) or not re.fullmatch(r"[A-Za-z0-9_-]{2,32}", request.language):
        raise PipelineError("INVALID_LANGUAGE")
    if not isinstance(request.voice_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", request.voice_id):
        raise PipelineError("INVALID_VOICE_ID")
    if isinstance(request.chunk_chars, bool) or not isinstance(request.chunk_chars, int) or not 1 <= request.chunk_chars <= 100_000:
        raise PipelineError("INVALID_CHUNK_LIMIT")
    if isinstance(request.speed, bool) or not isinstance(request.speed, (int, float)) or not math.isfinite(request.speed) or not 0.5 <= request.speed <= 2.0:
        raise PipelineError("INVALID_SPEED")
    if request.seed is not None and (isinstance(request.seed, bool) or not isinstance(request.seed, int) or not 0 <= request.seed <= 2_147_483_647):
        raise PipelineError("INVALID_SEED")
    if request.preferred_engine is not None and (not isinstance(request.preferred_engine, str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", request.preferred_engine)):
        raise PipelineError("INVALID_PREFERRED_ENGINE")
    if request.voice_profile_id is None:
        if request.voice_mode is not None:
            raise PipelineError("VOICE_PROFILE_ID_REQUIRED")
    else:
        _validate_id(request.voice_profile_id, "voice_profile_id")
        if request.preferred_engine is None or not isinstance(request.voice_mode, str):
            raise PipelineError("VOICE_PROFILE_METADATA_INVALID")
        try:
            from voice_controls import validate_voice_mode
            validate_voice_mode(request.preferred_engine, request.voice_mode)
        except ValueError as exc:
            raise PipelineError(str(exc).split(":", 1)[0]) from exc
    if not isinstance(request.output_name, str) or not request.output_name.strip(): raise PipelineError("INVALID_OUTPUT_NAME")
    name = Path(request.output_name)
    if name.is_absolute() or len(name.parts) != 1 or request.output_name in {".", ".."} or any(ord(c) < 32 or c in "/\\:" for c in request.output_name) or request.output_name.endswith((" ", ".")):
        raise PipelineError("INVALID_OUTPUT_NAME")
    return PipelineRequest(request.request_id, request.text.strip(), request.language.lower(), request.voice_id,
                           request.output_name, request.chunk_chars, float(request.speed), request.seed,
                           request.preferred_engine, request.voice_profile_id, request.voice_mode)

def chunk_text(text: str, max_chars: int) -> list[str]:
    if not isinstance(text, str) or not text.strip() or "\x00" in text: raise PipelineError("INVALID_TEXT")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 1 <= max_chars <= 100_000: raise PipelineError("INVALID_CHUNK_LIMIT")
    words, chunks, current = re.findall(r"\S+", text.strip()), [], ""
    for word in words:
        if len(word) > max_chars:
            if current: chunks.append(current); current = ""
            for start in range(0, len(word), max_chars):
                piece = word[start:start + max_chars]
                if len(piece) == max_chars: chunks.append(piece)
                else: current = piece
            continue
        candidate = word if not current else current + " " + word
        if len(candidate) <= max_chars: current = candidate
        else: chunks.append(current); current = word
    if current: chunks.append(current)
    return chunks

def select_adapter(request: PipelineRequest, adapters: Sequence[SynthesisAdapter]) -> SynthesisAdapter:
    seen, ready = set(), []
    for adapter in adapters:
        engine_id, languages = getattr(adapter, "engine_id", None), getattr(adapter, "supported_languages", None)
        if not isinstance(engine_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", engine_id): raise PipelineError("INVALID_ADAPTER_ENGINE_ID")
        if engine_id in seen: raise PipelineError("DUPLICATE_ADAPTER_ENGINE_ID")
        seen.add(engine_id)
        if not isinstance(languages, (set, frozenset, list, tuple)) or any(not isinstance(x, str) or not x.strip() for x in languages): raise PipelineError("INVALID_ADAPTER_LANGUAGES")
        available = getattr(adapter, "available", True)
        if not isinstance(available, bool): raise PipelineError("INVALID_ADAPTER_AVAILABILITY")
        if available and request.language in {x.strip().lower() for x in languages}: ready.append(adapter)
    if request.preferred_engine is not None:
        for adapter in ready:
            if adapter.engine_id == request.preferred_engine: return adapter
        raise PipelineError("PREFERRED_ENGINE_UNAVAILABLE")
    if not ready: raise PipelineError("NO_COMPATIBLE_ENGINE")
    return sorted(ready, key=lambda a: a.engine_id)[0]

def _wav_info(payload: bytes) -> AudioInfo:
    if not isinstance(payload, bytes) or not payload: raise PipelineError("AUDIO_EMPTY")
    import io
    try:
        with wave.open(io.BytesIO(payload), "rb") as stream:
            channels, width, rate, frames = stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getnframes()
            compression, raw = stream.getcomptype(), stream.readframes(frames)
    except (wave.Error, EOFError, OSError) as exc: raise PipelineError("AUDIO_INVALID_WAV") from exc
    if channels < 1 or width not in (1, 2, 3, 4) or rate < 8000 or compression != "NONE": raise PipelineError("AUDIO_INVALID_FORMAT")
    if frames <= 0 or len(raw) != frames * channels * width: raise PipelineError("AUDIO_EMPTY_OR_TRUNCATED")
    return AudioInfo(channels, width, rate, frames, frames / rate)

def _join_wavs(chunks: Sequence[bytes]) -> tuple[bytes, AudioInfo]:
    if not chunks: raise PipelineError("NO_AUDIO_CHUNKS")
    import io
    infos = [_wav_info(x) for x in chunks]; base = infos[0]
    if any((x.channels, x.sample_width, x.sample_rate) != (base.channels, base.sample_width, base.sample_rate) for x in infos[1:]): raise PipelineError("AUDIO_FORMAT_MISMATCH")
    output = io.BytesIO()
    try:
        with wave.open(output, "wb") as writer:
            writer.setnchannels(base.channels); writer.setsampwidth(base.sample_width); writer.setframerate(base.sample_rate)
            for payload in chunks:
                with wave.open(io.BytesIO(payload), "rb") as reader: writer.writeframes(reader.readframes(reader.getnframes()))
    except (wave.Error, EOFError, OSError) as exc: raise PipelineError("AUDIO_ASSEMBLY_FAILED") from exc
    combined = output.getvalue()
    return combined, _wav_info(combined)

def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream: stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try: os.unlink(temporary)
        except FileNotFoundError: pass

def run_pipeline(request: PipelineRequest, adapters: Sequence[SynthesisAdapter], output_dir: str | Path) -> PipelineResult:
    """Run an injected real TTS adapter, assemble WAV chunks, and write an integrity manifest."""
    request = validate_request(request); adapter = select_adapter(request, adapters)
    root = Path(output_dir).resolve(); root.mkdir(parents=True, exist_ok=True)
    chunks, wav_chunks = chunk_text(request.text, request.chunk_chars), []
    for index, text_chunk in enumerate(chunks, 1):
        try: payload = adapter.synthesize_wav(text_chunk, language=request.language, voice_id=request.voice_id, speed=request.speed, seed=request.seed)
        except PipelineError: raise
        except Exception as exc: raise PipelineError("SYNTHESIS_FAILED", f"chunk={index}") from exc
        _wav_info(payload); wav_chunks.append(payload)
    combined, info = _join_wavs(wav_chunks)
    output_path = (root / request.output_name).resolve()
    if output_path.parent != root: raise PipelineError("OUTPUT_PATH_OUTSIDE_ROOT")
    _atomic_write(output_path, combined); digest = hashlib.sha256(combined).hexdigest()
    manifest = {"manifest_version": 1, "request_id": request.request_id, "engine_id": adapter.engine_id,
                "language": request.language, "voice_id": request.voice_id, "chunks": len(chunks),
                "audio": {"file": request.output_name, "format": "wav", "sha256": digest,
                          "size_bytes": len(combined), "sample_rate_hz": info.sample_rate, "channels": info.channels,
                          "sample_width_bytes": info.sample_width, "frames": info.frames,
                          "duration_seconds": round(info.duration_seconds, 9)}}
    if request.voice_profile_id is not None:
        # Never store the voice description, reference path, or private asset bytes in the manifest.
        manifest["voice_profile_id"] = request.voice_profile_id
        manifest["voice_mode"] = request.voice_mode
    manifest_path = root / (request.output_name + ".manifest.json")
    _atomic_write(manifest_path, (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    return PipelineResult(request.request_id, adapter.engine_id, str(output_path), digest, len(combined), info.duration_seconds, len(chunks), str(manifest_path))
