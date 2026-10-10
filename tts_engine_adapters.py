"""Optional real adapters for Qwen3-TTS, Chatterbox TTS, and Kokoro.

Imports are lazy: installing the contract harness does not install or download
large model dependencies. `probe_engines()` reports package presence only; it
never claims that model weights are cached or inference works.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import wave
from typing import Any

from cache_paths import hf_hub_cache_path
from voice_controls import VERIFIED_PROFILE_MODES, validate_controls
from voiceover_pipeline import PipelineError


@dataclass(frozen=True)
class EngineProbe:
    engine_id: str
    package_available: bool
    inference_verified: bool
    model_id: str | None
    model_cached: bool | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PACKAGE_MAP = {
    "qwen3_tts": ("qwen_tts", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"),
    "chatterbox": ("chatterbox", None),
    "kokoro": ("kokoro", None),
}

# Qwen3-TTS documents ten languages; do not overstate its language coverage.
LANGUAGE_NAMES = {
    "en": "English", "zh": "Chinese", "ja": "Japanese", "ko": "Korean",
    "de": "German", "fr": "French", "es": "Spanish", "it": "Italian",
    "pt": "Portuguese", "ru": "Russian",
}
KOKORO_LANG_CODES = {"en": "a", "en-us": "a", "en-gb": "b", "es": "e", "fr": "f",
                     "hi": "h", "it": "i", "ja": "j", "pt": "p", "zh": "z"}
CHATTERBOX_LANG_IDS = {"en": "en", "fr": "fr", "de": "de", "es": "es", "it": "it",
                       "pt": "pt", "hi": "hi", "zh": "zh", "ja": "ja", "ko": "ko",
                       "ru": "ru", "ar": "ar", "tr": "tr", "pl": "pl", "nl": "nl",
                       "sv": "sv", "da": "da", "fi": "fi", "el": "el", "he": "he",
                       "ms": "ms", "sw": "sw"}

QWEN_VOICE_DESIGN_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
QWEN_VOICE_DESIGN_REVISION = "5ecdb67327fd37bb2e042aab12ff7391903235d3"
QWEN_CUSTOM_VOICE_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
QWEN_CUSTOM_VOICE_REVISION = "0c0e3051f131929182e2c023b9537f8b1c68adfe"
QWEN_MODEL_ALLOW_PATTERNS = (
    "config.json", "generation_config.json", "model.safetensors",
    "preprocessor_config.json", "tokenizer_config.json", "vocab.json", "merges.txt",
    "speech_tokenizer/config.json", "speech_tokenizer/configuration.json",
    "speech_tokenizer/model.safetensors", "speech_tokenizer/preprocessor_config.json",
)
CHATTERBOX_MODEL_ID = "ResembleAI/chatterbox"
CHATTERBOX_V2_REVISION = "5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18"
CHATTERBOX_V2_ALLOW_PATTERNS = (
    "ve.pt", "t3_mtl23ls_v2.safetensors", "s3gen.pt",
    "grapheme_mtl_merged_expanded_v1.json", "conds.pt", "Cangjie5_TC.json",
)
KOKORO_MODEL_ID = "hexgrad/Kokoro-82M"
KOKORO_MODEL_REVISION = "f3ff3571791e39611d31c381e3a41a3af07b4987"
KOKORO_MODEL_ALLOW_PATTERNS = ("config.json", "kokoro-v1_0.pth", "voices/*.pt")


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def _model_cache_exists(model_id: str | None) -> bool | None:
    if not model_id:
        return None
    # Hugging Face cache naming: models--org--name. This is a conservative
    # presence check only; it does not validate all model files or revisions.
    cache = hf_hub_cache_path()
    safe_name = "models--" + model_id.replace("/", "--")
    return (cache / safe_name).is_dir()


def probe_engines() -> list[EngineProbe]:
    """Return honest local package/cache status; no model is loaded or downloaded."""
    probes = []
    for engine_id, (module, model_id) in PACKAGE_MAP.items():
        installed = _module_available(module)
        cached = _model_cache_exists(model_id) if engine_id == "qwen3_tts" else None
        if not installed:
            reason = f"optional dependency '{module}' is not installed"
        elif cached is False:
            reason = "package is installed; configured/default model cache was not found"
        else:
            reason = "package presence only; actual model loading and inference are not verified"
        probes.append(EngineProbe(engine_id, installed, False, model_id, cached, reason))
    return probes


def _to_wav_bytes(audio: Any, sample_rate: int) -> bytes:
    """Serialize mono/stereo normalized float audio via soundfile when available."""
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        raise PipelineError("AUDIO_SERIALIZER_MISSING", "install numpy and soundfile") from exc
    if hasattr(audio, "detach"):
        audio = audio.detach()
    if hasattr(audio, "cpu"):
        audio = audio.cpu()
    if hasattr(audio, "numpy"):
        audio = audio.numpy()
    array = np.asarray(audio)
    if array.size == 0 or array.ndim not in (1, 2):
        raise PipelineError("ENGINE_RETURNED_INVALID_AUDIO_SHAPE")
    if not isinstance(sample_rate, int) or isinstance(sample_rate, bool) or sample_rate < 8000:
        raise PipelineError("ENGINE_RETURNED_INVALID_SAMPLE_RATE")
    if not np.issubdtype(array.dtype, np.number) or not np.isfinite(array).all():
        raise PipelineError("ENGINE_RETURNED_NONFINITE_AUDIO")
    array = np.clip(array, -1.0, 1.0).astype(np.float32, copy=False)
    output = io.BytesIO()
    try:
        sf.write(output, array, sample_rate, format="WAV", subtype="PCM_16")
    except Exception as exc:
        raise PipelineError("AUDIO_SERIALIZATION_FAILED") from exc
    return output.getvalue()


def _validate_wav(payload: bytes) -> bytes:
    try:
        with wave.open(io.BytesIO(payload), "rb") as wav:
            if wav.getnframes() < 1 or wav.getframerate() < 8000 or wav.getnchannels() not in (1, 2):
                raise PipelineError("ENGINE_RETURNED_INVALID_WAV")
            frames = wav.readframes(wav.getnframes())
            if len(frames) != wav.getnframes() * wav.getnchannels() * wav.getsampwidth():
                raise PipelineError("ENGINE_RETURNED_TRUNCATED_WAV")
    except (wave.Error, EOFError, OSError) as exc:
        raise PipelineError("ENGINE_RETURNED_INVALID_WAV") from exc
    return payload


class Qwen3TTSAdapter:
    engine_id = "qwen3_tts"
    supported_languages = set(LANGUAGE_NAMES)

    def __init__(self, model_id: str = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
                 device_map: str = "auto", model_type: str = "custom_voice", instruct: str = "",
                 generation_options: dict[str, Any] | None = None,
                 revision: str | None = None, local_only: bool = False):
        if model_type not in {"custom_voice", "voice_design", "voice_clone"}:
            raise PipelineError("INVALID_QWEN_MODEL_TYPE")
        if revision is not None and (not isinstance(revision, str) or len(revision) != 40
                                     or any(c not in "0123456789abcdef" for c in revision)):
            raise PipelineError("MODEL_REVISION_INVALID")
        if local_only and not revision:
            raise PipelineError("MODEL_REVISION_REQUIRED")
        control_mode = "voice_design" if model_type == "voice_design" else "preset"
        if model_type == "voice_clone" and generation_options:
            raise PipelineError("VOICE_MODE_UNSUPPORTED")
        try:
            self.generation_options = validate_controls("qwen3_tts", control_mode, generation_options)
        except ValueError as exc:
            raise PipelineError(str(exc).split(":", 1)[0]) from exc
        self.model_id, self.device_map, self.model_type, self.instruct = model_id, device_map, model_type, instruct
        self.revision, self.local_only = revision, local_only
        self._model = None

    @property
    def available(self) -> bool:
        return _module_available("qwen_tts")

    def _load(self):
        if self._model is None:
            try:
                from qwen_tts import Qwen3TTSModel
            except ImportError as exc:
                raise PipelineError("ENGINE_DEPENDENCY_MISSING", "qwen-tts") from exc
            model_source = self.model_id
            if self.local_only:
                try:
                    from huggingface_hub import snapshot_download
                    model_source = snapshot_download(repo_id=self.model_id, revision=self.revision,
                                                     allow_patterns=list(QWEN_MODEL_ALLOW_PATTERNS),
                                                     local_files_only=True)
                except Exception as exc:
                    raise PipelineError("ENGINE_MODEL_ARTIFACT_MISSING", "qwen3_tts") from exc
            try:
                kwargs = {"device_map": self.device_map}
                # The pinned VoiceDesign checkpoint is saved in BF16. Keep it
                # in its native dtype on CPU rather than allowing Transformers
                # to promote 1.7B weights to FP32 and exceed the fixed RSS cap.
                # This is an upstream-supported loader argument; resource_guard
                # remains the final unchanged process-tree limit.
                if self.device_map == "cpu" and self.model_type == "voice_design":
                    kwargs["dtype"] = "bfloat16"
                if self.revision and not self.local_only:
                    kwargs["revision"] = self.revision
                self._model = Qwen3TTSModel.from_pretrained(model_source, **kwargs)
            except Exception as exc:
                raise PipelineError("ENGINE_MODEL_LOAD_FAILED", "qwen3_tts") from exc
        return self._model

    def synthesize_wav(self, text: str, *, language: str, voice_id: str,
                       speed: float = 1.0, seed: int | None = None) -> bytes:
        if speed != 1.0 or seed is not None:
            raise PipelineError("ENGINE_OPTION_UNSUPPORTED", "qwen speed/seed not mapped by this adapter")
        lang = LANGUAGE_NAMES.get(language.lower())
        if not lang:
            raise PipelineError("ENGINE_LANGUAGE_UNSUPPORTED", language)
        if self.model_type == "voice_clone":
            raise PipelineError("ENGINE_MODE_REQUIRES_REFERENCE_AUDIO", "configure a voice-clone prompt adapter")
        model = self._load()
        try:
            if self.model_type == "custom_voice":
                wavs, sr = model.generate_custom_voice(text=text, language=lang, speaker=voice_id,
                                                       instruct=self.instruct or None, **self.generation_options)
            elif self.model_type == "voice_design":
                wavs, sr = model.generate_voice_design(text=text, language=lang,
                                                       instruct=self.instruct or voice_id, **self.generation_options)
            else:
                raise PipelineError("INVALID_QWEN_MODEL_TYPE")
            if not wavs:
                raise PipelineError("ENGINE_RETURNED_NO_AUDIO")
            return _validate_wav(_to_wav_bytes(wavs[0], int(sr)))
        except PipelineError:
            raise
        except Exception as exc:
            raise PipelineError("ENGINE_INFERENCE_FAILED", "qwen3_tts") from exc


class ChatterboxAdapter:
    engine_id = "chatterbox"
    supported_languages = set(CHATTERBOX_LANG_IDS)

    def __init__(self, device: str = "auto", reference_audio: str | None = None,
                 multilingual: bool = True, generation_options: dict[str, Any] | None = None,
                 local_only: bool = False, model_revision: str | None = None):
        if model_revision is not None and (not isinstance(model_revision, str) or len(model_revision) != 40
                                           or any(c not in "0123456789abcdef" for c in model_revision)):
            raise PipelineError("MODEL_REVISION_INVALID")
        if local_only and (not multilingual or not model_revision):
            raise PipelineError("MODEL_REVISION_REQUIRED")
        mode = "reference_clone" if reference_audio is not None else "preset"
        try:
            self.generation_options = validate_controls("chatterbox", mode, generation_options)
        except ValueError as exc:
            raise PipelineError(str(exc).split(":", 1)[0]) from exc
        self.device, self.reference_audio, self.multilingual = device, reference_audio, multilingual
        self.local_only, self.model_revision = local_only, model_revision
        self._model = None

    @property
    def available(self) -> bool:
        return _module_available("chatterbox")

    def _load(self):
        if self._model is None:
            try:
                if self.multilingual:
                    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
                    if self.local_only:
                        from huggingface_hub import snapshot_download
                        model_dir = snapshot_download(repo_id=CHATTERBOX_MODEL_ID, revision=self.model_revision,
                                                      allow_patterns=list(CHATTERBOX_V2_ALLOW_PATTERNS),
                                                      local_files_only=True)
                        self._model = ChatterboxMultilingualTTS.from_local(model_dir, device=self._resolve_device())
                    else:
                        self._model = ChatterboxMultilingualTTS.from_pretrained(device=self._resolve_device())
                else:
                    from chatterbox.tts import ChatterboxTTS
                    self._model = ChatterboxTTS.from_pretrained(device=self._resolve_device())
            except ImportError as exc:
                raise PipelineError("ENGINE_DEPENDENCY_MISSING", "chatterbox-tts") from exc
            except Exception as exc:
                raise PipelineError("ENGINE_MODEL_LOAD_FAILED", "chatterbox") from exc
        return self._model

    def _resolve_device(self) -> str:
        """Resolve `auto` to a device value accepted by Chatterbox loaders."""
        if self.device != "auto":
            return self.device
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
        except (ImportError, AttributeError, RuntimeError):
            pass
        return "cpu"

    def synthesize_wav(self, text: str, *, language: str, voice_id: str,
                       speed: float = 1.0, seed: int | None = None) -> bytes:
        if speed != 1.0:
            raise PipelineError("ENGINE_OPTION_UNSUPPORTED", "Chatterbox speed control is not mapped")
        if seed is not None:
            raise PipelineError("ENGINE_OPTION_UNSUPPORTED", "Chatterbox seed control is not mapped")
        lang = language.lower()
        if self.multilingual and lang not in CHATTERBOX_LANG_IDS:
            raise PipelineError("ENGINE_LANGUAGE_UNSUPPORTED", language)
        if not self.multilingual and lang not in {"en", "en-us", "en-gb"}:
            raise PipelineError("ENGINE_LANGUAGE_UNSUPPORTED", language)
        reference = self.reference_audio
        if voice_id not in {"default", "builtin", "default_voice"}:
            reference = voice_id
        if reference is not None and not Path(reference).is_file():
            raise PipelineError("VOICE_REFERENCE_NOT_FOUND")
        model = self._load()
        try:
            kwargs = {"audio_prompt_path": reference} if reference else {}
            if self.multilingual:
                kwargs["language_id"] = CHATTERBOX_LANG_IDS[lang]
            kwargs.update(self.generation_options)
            audio = model.generate(text, **kwargs)
            # Chatterbox commonly returns channel-first [1, samples] tensors;
            # serialize as mono samples, not as one frame with hundreds of channels.
            if hasattr(audio, "detach"):
                audio = audio.detach()
            if hasattr(audio, "cpu"):
                audio = audio.cpu()
            if hasattr(audio, "numpy"):
                audio = audio.numpy()
            import numpy as np
            audio = np.asarray(audio)
            if audio.ndim == 2 and audio.shape[0] == 1:
                audio = audio[0]
            sr = int(getattr(model, "sr", 24000))
            return _validate_wav(_to_wav_bytes(audio, sr))
        except PipelineError:
            raise
        except Exception as exc:
            raise PipelineError("ENGINE_INFERENCE_FAILED", "chatterbox") from exc


class KokoroAdapter:
    engine_id = "kokoro"
    supported_languages = set(KOKORO_LANG_CODES)

    def __init__(self, repo_id: str | None = None, *, local_only: bool = False):
        self.repo_id = repo_id
        self.local_only = local_only
        self._pipelines: dict[str, Any] = {}

    @property
    def available(self) -> bool:
        return _module_available("kokoro")

    def _load(self, lang_code: str):
        if lang_code not in self._pipelines:
            if self.local_only:
                # Profile runs never fetch missing assets. This process-level
                # setting is applied in the isolated worker before Hub imports.
                os.environ["HF_HUB_OFFLINE"] = "1"
                os.environ["HF_DATASETS_OFFLINE"] = "1"
            try:
                from kokoro import KPipeline
            except ImportError as exc:
                raise PipelineError("ENGINE_DEPENDENCY_MISSING", "kokoro") from exc
            try:
                kwargs = {"lang_code": lang_code}
                if self.repo_id:
                    kwargs["repo_id"] = self.repo_id
                self._pipelines[lang_code] = KPipeline(**kwargs)
            except Exception as exc:
                raise PipelineError("ENGINE_MODEL_LOAD_FAILED", "kokoro") from exc
        return self._pipelines[lang_code]

    def synthesize_wav(self, text: str, *, language: str, voice_id: str,
                       speed: float = 1.0, seed: int | None = None) -> bytes:
        if seed is not None:
            raise PipelineError("ENGINE_OPTION_UNSUPPORTED", "Kokoro seed control is not mapped")
        lang_code = KOKORO_LANG_CODES.get(language.lower())
        if not lang_code:
            raise PipelineError("ENGINE_LANGUAGE_UNSUPPORTED", language)
        pipeline = self._load(lang_code)
        try:
            import numpy as np
            audio_parts = []
            for result in pipeline(text, voice=voice_id, speed=float(speed)):
                audio = getattr(result, "audio", None)
                if audio is None and isinstance(result, (tuple, list)) and len(result) >= 3:
                    audio = result[2]
                if audio is not None:
                    if hasattr(audio, "detach"):
                        audio = audio.detach()
                    if hasattr(audio, "cpu"):
                        audio = audio.cpu()
                    if hasattr(audio, "numpy"):
                        audio = audio.numpy()
                    array = np.asarray(audio)
                    if array.size:
                        audio_parts.append(array.reshape(-1))
            if not audio_parts:
                raise PipelineError("ENGINE_RETURNED_NO_AUDIO")
            return _validate_wav(_to_wav_bytes(np.concatenate(audio_parts), 24000))
        except PipelineError:
            raise
        except Exception as exc:
            raise PipelineError("ENGINE_INFERENCE_FAILED", "kokoro") from exc


def default_adapters() -> list[Any]:
    """Return only the real-smoke-verified profileless preset adapter."""
    return [KokoroAdapter()]


def adapters_for_profile(profile: dict[str, Any], store_dir: str | Path) -> list[Any]:
    """Create exactly one offline/local-only adapter from a validated stored profile."""
    if not isinstance(profile, dict):
        raise PipelineError("PROFILE_OBJECT_REQUIRED")
    engine, mode = profile.get("engine_id"), profile.get("mode")
    if not isinstance(engine, str) or engine not in {"qwen3_tts", "kokoro"}:
        raise PipelineError("PROFILE_ENGINE_UNSUPPORTED")
    if (engine, mode) not in VERIFIED_PROFILE_MODES:
        raise PipelineError("VOICE_MODE_UNSUPPORTED")
    controls = profile.get("controls", {})
    if engine == "qwen3_tts":
        return [Qwen3TTSAdapter(model_id=QWEN_VOICE_DESIGN_MODEL_ID, device_map="cpu",
                                model_type="voice_design", instruct=profile.get("voice_description") or "",
                                generation_options=controls, revision=QWEN_VOICE_DESIGN_REVISION,
                                local_only=True)]
    if engine == "kokoro" and mode == "preset":
        return [KokoroAdapter(repo_id=KOKORO_MODEL_ID, local_only=True)]
    raise PipelineError("VOICE_MODE_UNSUPPORTED")
