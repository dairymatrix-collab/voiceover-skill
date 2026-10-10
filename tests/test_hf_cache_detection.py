from __future__ import annotations

from pathlib import Path

import tts_artifact_readiness as readiness
import tts_engine_adapters as adapters
import tts_environment as environment
from cache_paths import hf_home_path, hf_hub_cache_path


_CACHE_ENV = ("HF_HUB_CACHE", "HF_HOME", "XDG_CACHE_HOME",
              "VOICEOVER_MODEL_ROOT", "TTS_MODEL_ROOT")


def _clear_cache_environment(monkeypatch):
    for key in _CACHE_ENV:
        monkeypatch.delenv(key, raising=False)


def test_hf_home_prefers_explicit_home_then_xdg_then_user_cache(tmp_path):
    assert hf_home_path(environ={"HF_HOME": str(tmp_path / "hf"),
                                 "XDG_CACHE_HOME": str(tmp_path / "xdg")},
                        home=tmp_path) == tmp_path / "hf"
    assert hf_home_path(environ={"XDG_CACHE_HOME": str(tmp_path / "xdg")},
                        home=tmp_path) == tmp_path / "xdg" / "huggingface"
    assert hf_home_path(environ={}, home=tmp_path) == tmp_path / ".cache" / "huggingface"


def test_explicit_hf_hub_cache_overrides_hf_home(tmp_path):
    chosen = tmp_path / "chosen-hub"
    assert hf_hub_cache_path(environ={"HF_HUB_CACHE": str(chosen),
                                      "HF_HOME": str(tmp_path / "other")},
                            home=tmp_path) == chosen


def test_hf_hub_cache_uses_hf_home_and_xdg_fallbacks(tmp_path):
    assert hf_hub_cache_path(environ={"HF_HOME": str(tmp_path / "hf")},
                             home=tmp_path) == tmp_path / "hf" / "hub"
    assert hf_hub_cache_path(environ={"XDG_CACHE_HOME": str(tmp_path / "xdg")},
                             home=tmp_path) == tmp_path / "xdg" / "huggingface" / "hub"


def test_artifact_root_auto_discovers_effective_hub_cache(tmp_path, monkeypatch):
    _clear_cache_environment(monkeypatch)
    hub = tmp_path / "effective-hub"
    hub.mkdir()
    monkeypatch.setenv("HF_HUB_CACHE", str(hub))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "different-home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "different-xdg"))
    assert readiness.resolve_model_root() == hub.resolve()


def test_artifact_root_uses_xdg_cache_when_no_hf_override(tmp_path, monkeypatch):
    _clear_cache_environment(monkeypatch)
    hub = tmp_path / "xdg" / "huggingface" / "hub"
    hub.mkdir(parents=True)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert readiness.resolve_model_root() == hub.resolve()


def test_explicit_missing_model_root_never_falls_through_to_existing_cache(tmp_path, monkeypatch):
    _clear_cache_environment(monkeypatch)
    explicit = tmp_path / "explicit-but-missing"
    configured = tmp_path / "configured-models"
    hub = tmp_path / "hub-cache"
    configured.mkdir()
    hub.mkdir()
    monkeypatch.setenv("VOICEOVER_MODEL_ROOT", str(configured))
    monkeypatch.setenv("HF_HUB_CACHE", str(hub))
    assert readiness.resolve_model_root(explicit) == explicit.resolve()


def test_custom_model_root_precedes_huggingface_cache(tmp_path, monkeypatch):
    _clear_cache_environment(monkeypatch)
    custom = tmp_path / "custom-models"
    hub = tmp_path / "hub-cache"
    custom.mkdir()
    hub.mkdir()
    monkeypatch.setenv("TTS_MODEL_ROOT", str(custom))
    monkeypatch.setenv("HF_HUB_CACHE", str(hub))
    assert readiness.resolve_model_root() == custom.resolve()


def test_environment_cache_scan_uses_hub_override_and_reports_base_home(tmp_path, monkeypatch):
    _clear_cache_environment(monkeypatch)
    home = tmp_path / "hf-home"
    hub = tmp_path / "separate-hub"
    qwen = hub / "models--Qwen--Qwen3-TTS-12Hz-1.7B-CustomVoice"
    qwen.mkdir(parents=True)
    (qwen / "small-fixture.bin").write_bytes(b"cache-fixture")
    monkeypatch.setenv("HF_HOME", str(home))
    monkeypatch.setenv("HF_HUB_CACHE", str(hub))
    result = environment._model_cache()
    assert result["hf_home"] == str(home)
    assert result["hub_exists"] is True
    assert result["qwen_default_model_directory_exists"] is True
    assert result["hub_bytes_scanned"] == len(b"cache-fixture")


def test_qwen_adapter_probe_uses_xdg_derived_hub_cache(tmp_path, monkeypatch):
    _clear_cache_environment(monkeypatch)
    qwen = (tmp_path / "xdg" / "huggingface" / "hub" /
            "models--Qwen--Qwen3-TTS-12Hz-1.7B-CustomVoice")
    qwen.mkdir(parents=True)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert adapters._model_cache_exists("Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice") is True
