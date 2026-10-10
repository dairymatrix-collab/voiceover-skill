"""Model-free conformance tests for optional real-engine adapter boundaries."""
import io
import json
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import tts_engine_adapters as engines
from voiceover_pipeline import PipelineError
from voice_profile_store import create_profile


def wav_bytes(frames=800, rate=16000, channels=1):
    output = io.BytesIO()
    with wave.open(output, "wb") as w:
        w.setnchannels(channels); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"\0\0" * frames * channels)
    return output.getvalue()


class FakeQwen:
    def __init__(self): self.calls = []
    def generate_custom_voice(self, **kwargs):
        self.calls.append(("custom", kwargs)); return [np.zeros(800, dtype=np.float32)], 16000
    def generate_voice_design(self, **kwargs):
        self.calls.append(("design", kwargs)); return [np.zeros(800, dtype=np.float32)], 16000


class FakeChatterbox:
    sr = 16000
    def __init__(self): self.calls = []
    def generate(self, text, **kwargs):
        self.calls.append((text, kwargs)); return np.zeros((1, 800), dtype=np.float32)


class FakeKokoro:
    def __init__(self): self.calls = []
    def __call__(self, text, **kwargs):
        self.calls.append((text, kwargs))
        yield SimpleNamespace(audio=np.zeros(400, dtype=np.float32))
        yield SimpleNamespace(audio=np.zeros(400, dtype=np.float32))


# D0-131

def test_d0_131_probe_returns_all_three_engines():
    ids = {x.engine_id for x in engines.probe_engines()}
    assert ids == {"qwen3_tts", "chatterbox", "kokoro"}

# D0-132

def test_d0_132_probe_never_claims_inference_verified():
    assert all(x.inference_verified is False for x in engines.probe_engines())

# D0-133

def test_d0_133_probe_reports_boolean_package_state():
    assert all(isinstance(x.package_available, bool) for x in engines.probe_engines())

# D0-134

def test_d0_134_probe_json_is_serializable():
    json.dumps([x.to_dict() for x in engines.probe_engines()])

# D0-135

def test_d0_135_language_map_has_english():
    assert engines.LANGUAGE_NAMES["en"] == "English"

# D0-136

def test_d0_136_qwen_adapter_does_not_load_model_at_init():
    a = engines.Qwen3TTSAdapter()
    assert a._model is None

# D0-137

def test_d0_137_chatterbox_adapter_does_not_load_model_at_init():
    a = engines.ChatterboxAdapter()
    assert a._model is None
    assert a._resolve_device() in {"cpu", "cuda", "mps"}

# D0-138

def test_d0_138_kokoro_adapter_does_not_load_pipeline_at_init():
    assert engines.KokoroAdapter()._pipelines == {}

# D0-139

def test_d0_139_qwen_custom_voice_calls_expected_model_method(monkeypatch):
    a = engines.Qwen3TTSAdapter(instruct="calm")
    model = FakeQwen(); monkeypatch.setattr(a, "_load", lambda: model)
    out = a.synthesize_wav("hello", language="en", voice_id="Ryan")
    assert model.calls[0][0] == "custom" and model.calls[0][1]["speaker"] == "Ryan"
    assert wave.open(io.BytesIO(out)).getnframes() > 0

# D0-140

def test_d0_140_qwen_voice_design_uses_instruction(monkeypatch):
    a = engines.Qwen3TTSAdapter(model_type="voice_design", instruct="warm narrator")
    model = FakeQwen(); monkeypatch.setattr(a, "_load", lambda: model)
    a.synthesize_wav("hello", language="en", voice_id="unused")
    assert model.calls[0][0] == "design"
    assert model.calls[0][1]["instruct"] == "warm narrator"

# D0-141

def test_d0_141_qwen_unknown_language_fails_closed():
    with pytest.raises(PipelineError, match="ENGINE_LANGUAGE_UNSUPPORTED"):
        engines.Qwen3TTSAdapter().synthesize_wav("x", language="xx", voice_id="Ryan")

# D0-142

def test_d0_142_qwen_rejects_unmapped_speed():
    with pytest.raises(PipelineError, match="ENGINE_OPTION_UNSUPPORTED"):
        engines.Qwen3TTSAdapter().synthesize_wav("x", language="en", voice_id="Ryan", speed=1.1)

# D0-143

def test_d0_143_qwen_voice_clone_mode_is_explicitly_blocked():
    a = engines.Qwen3TTSAdapter(model_type="voice_clone")
    with pytest.raises(PipelineError, match="ENGINE_MODE_REQUIRES_REFERENCE_AUDIO"):
        a.synthesize_wav("x", language="en", voice_id="Ryan")
    assert a._model is None

# D0-144

def test_d0_144_chatterbox_multilingual_passes_language_id(monkeypatch):
    a = engines.ChatterboxAdapter(multilingual=True)
    model = FakeChatterbox(); monkeypatch.setattr(a, "_load", lambda: model)
    a.synthesize_wav("hello", language="fr", voice_id="default")
    assert model.calls[0][1]["language_id"] == "fr"

# D0-145

def test_d0_145_chatterbox_nonmultilingual_rejects_french():
    a = engines.ChatterboxAdapter(multilingual=False)
    with pytest.raises(PipelineError, match="ENGINE_LANGUAGE_UNSUPPORTED"):
        a.synthesize_wav("bonjour", language="fr", voice_id="default")

# D0-146

def test_d0_146_chatterbox_default_voice_does_not_need_reference(monkeypatch):
    a = engines.ChatterboxAdapter()
    model = FakeChatterbox(); monkeypatch.setattr(a, "_load", lambda: model)
    a.synthesize_wav("hello", language="en", voice_id="default")
    assert "audio_prompt_path" not in model.calls[0][1]

# D0-147

def test_d0_147_chatterbox_missing_reference_fails_before_inference(tmp_path):
    a = engines.ChatterboxAdapter()
    with pytest.raises(PipelineError, match="VOICE_REFERENCE_NOT_FOUND"):
        a.synthesize_wav("hello", language="en", voice_id=str(tmp_path / "missing.wav"))

# D0-148

def test_d0_148_chatterbox_rejects_unmapped_speed():
    with pytest.raises(PipelineError, match="ENGINE_OPTION_UNSUPPORTED"):
        engines.ChatterboxAdapter().synthesize_wav("x", language="en", voice_id="default", speed=1.2)

# D0-149

def test_d0_149_kokoro_maps_american_english(monkeypatch):
    a = engines.KokoroAdapter(); fake = FakeKokoro()
    monkeypatch.setattr(a, "_load", lambda code: (assert_lang(code, "a", fake)))
    a.synthesize_wav("hello", language="en", voice_id="af_heart")
    assert fake.calls[0][1]["voice"] == "af_heart"

def assert_lang(actual, expected, fake):
    assert actual == expected
    return fake

# D0-150

def test_d0_150_kokoro_maps_british_english():
    assert engines.KOKORO_LANG_CODES["en-gb"] == "b"

# D0-151

def test_d0_151_kokoro_joins_multiple_audio_segments(monkeypatch):
    a = engines.KokoroAdapter(); fake = FakeKokoro(); monkeypatch.setattr(a, "_load", lambda code: fake)
    out = a.synthesize_wav("hello there", language="en", voice_id="af_heart")
    with wave.open(io.BytesIO(out)) as w:
        assert w.getnframes() == 800 and w.getframerate() == 24000

# D0-152

def test_d0_152_kokoro_rejects_unsupported_language():
    with pytest.raises(PipelineError, match="ENGINE_LANGUAGE_UNSUPPORTED"):
        engines.KokoroAdapter().synthesize_wav("x", language="ru", voice_id="af_heart")

# D0-153

def test_d0_153_audio_serializer_rejects_empty_audio():
    with pytest.raises(PipelineError, match="ENGINE_RETURNED_INVALID_AUDIO_SHAPE"):
        engines._to_wav_bytes(np.array([], dtype=np.float32), 24000)

# D0-154

def test_d0_154_audio_serializer_rejects_nan():
    with pytest.raises(PipelineError, match="ENGINE_RETURNED_NONFINITE_AUDIO"):
        engines._to_wav_bytes(np.array([np.nan], dtype=np.float32), 24000)

# D0-155

def test_d0_155_audio_serializer_rejects_low_sample_rate():
    with pytest.raises(PipelineError, match="ENGINE_RETURNED_INVALID_SAMPLE_RATE"):
        engines._to_wav_bytes(np.zeros(10), 1000)

# D0-156

def test_d0_156_audio_serializer_clips_float_audio():
    out = engines._to_wav_bytes(np.array([-2.0, 0.0, 2.0], dtype=np.float32), 24000)
    with wave.open(io.BytesIO(out)) as w:
        assert w.getnframes() == 3

# D0-157

def test_d0_157_wav_validator_rejects_non_wav():
    with pytest.raises(PipelineError, match="ENGINE_RETURNED_INVALID_WAV"):
        engines._validate_wav(b"not wav")

# D0-158

def test_d0_158_wav_validator_accepts_valid_wav():
    assert engines._validate_wav(wav_bytes()) == wav_bytes()

# D0-159

def test_d0_159_default_adapters_are_stable_and_lazy():
    adapters = engines.default_adapters()
    assert [a.engine_id for a in adapters] == ["kokoro"]
    assert all(getattr(a, "_model", None) is None for a in adapters if hasattr(a, "_model"))

# D0-160

def test_d0_160_probe_reason_does_not_claim_successful_inference():
    assert all("not verified" in p.reason or "not installed" in p.reason or "cache was not found" in p.reason
               for p in engines.probe_engines())


def test_qwen_voice_design_passes_only_validated_generation_options(monkeypatch):
    adapter = engines.Qwen3TTSAdapter(model_type="voice_design", instruct="warm narrator",
                                      generation_options={"temperature": 0.7, "top_k": 24})
    model = FakeQwen(); monkeypatch.setattr(adapter, "_load", lambda: model)
    adapter.synthesize_wav("hello", language="en", voice_id="profile_voice")
    assert model.calls[0][1]["temperature"] == 0.7
    assert model.calls[0][1]["top_k"] == 24


def test_qwen_profile_loader_uses_pinned_local_snapshot_without_network(monkeypatch):
    calls = {}
    class Loader:
        @classmethod
        def from_pretrained(cls, source, **kwargs):
            calls["model"] = (source, kwargs)
            return object()
    def snapshot_download(**kwargs):
        calls["snapshot"] = kwargs
        return "/cache/pinned-qwen-snapshot"
    monkeypatch.setitem(sys.modules, "qwen_tts", SimpleNamespace(Qwen3TTSModel=Loader))
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot_download))
    adapter = engines.Qwen3TTSAdapter(model_id=engines.QWEN_VOICE_DESIGN_MODEL_ID,
        device_map="cpu", model_type="voice_design", instruct="bright voice",
        revision=engines.QWEN_VOICE_DESIGN_REVISION, local_only=True)
    adapter._load()
    assert calls["snapshot"]["revision"] == engines.QWEN_VOICE_DESIGN_REVISION
    assert calls["snapshot"]["local_files_only"] is True
    assert tuple(calls["snapshot"]["allow_patterns"]) == engines.QWEN_MODEL_ALLOW_PATTERNS
    assert calls["model"] == ("/cache/pinned-qwen-snapshot", {"device_map": "cpu", "dtype": "bfloat16"})


def test_chatterbox_profile_control_values_reach_pinned_api(monkeypatch, tmp_path):
    reference = tmp_path / "reference.wav"; reference.write_bytes(wav_bytes())
    adapter = engines.ChatterboxAdapter(reference_audio=str(reference),
        generation_options={"temperature": 0.7, "exaggeration": 0.65})
    model = FakeChatterbox(); monkeypatch.setattr(adapter, "_load", lambda: model)
    adapter.synthesize_wav("hello", language="en", voice_id="default")
    _, kwargs = model.calls[0]
    assert kwargs["audio_prompt_path"] == str(reference)
    assert kwargs["temperature"] == 0.7 and kwargs["exaggeration"] == 0.65


def test_profile_factory_selects_pinned_cpu_voice_design_adapter():
    profile = {"profile_id": "warm_narrator", "engine_id": "qwen3_tts", "mode": "voice_design",
               "voice_description": "Warm, clear adult narrator", "controls": {"temperature": 0.8}}
    adapter = engines.adapters_for_profile(profile, "/unused")[0]
    assert adapter.model_id == engines.QWEN_VOICE_DESIGN_MODEL_ID
    assert adapter.revision == engines.QWEN_VOICE_DESIGN_REVISION
    assert adapter.device_map == "cpu" and adapter.local_only is True
    assert adapter.generation_options == {"temperature": 0.8}


def test_profile_factory_rejects_unverified_reference_clone_profile(tmp_path):
    source = tmp_path / "source.wav"; source.write_bytes(wav_bytes())
    profile = create_profile(tmp_path / "store", profile_id="reference_voice", name="Reference",
        engine_id="chatterbox", mode="reference_clone", language="en", reference_audio=source)
    with pytest.raises(PipelineError, match="PROFILE_ENGINE_UNSUPPORTED"):
        engines.adapters_for_profile(profile, tmp_path / "store")


def test_profile_factory_rejects_unverified_qwen_preset():
    profile = {"profile_id": "speaker", "engine_id": "qwen3_tts", "mode": "preset",
               "voice_id": "Ryan", "controls": {}}
    with pytest.raises(PipelineError, match="VOICE_MODE_UNSUPPORTED"):
        engines.adapters_for_profile(profile, "/unused")


def test_kokoro_profile_factory_enforces_hub_offline_mode(monkeypatch):
    captured = {}
    class Pipeline:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs
            captured["offline"] = (engines.os.environ.get("HF_HUB_OFFLINE"),
                                   engines.os.environ.get("HF_DATASETS_OFFLINE"))
    monkeypatch.setitem(sys.modules, "kokoro", SimpleNamespace(KPipeline=Pipeline))
    profile = {"profile_id": "narrator", "engine_id": "kokoro", "mode": "preset"}
    adapter = engines.adapters_for_profile(profile, "/unused")[0]
    assert adapter.local_only is True
    adapter._load("a")
    assert captured["kwargs"]["repo_id"] == engines.KOKORO_MODEL_ID
    assert captured["offline"] == ("1", "1")
