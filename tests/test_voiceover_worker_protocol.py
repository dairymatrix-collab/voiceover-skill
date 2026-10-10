from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import scripts.voiceover_worker as worker
from voice_profile_store import create_profile


def test_worker_redirects_adapter_stdout_and_emits_one_json_line(monkeypatch, tmp_path):
    request = {
        "request_id": "stdout-protocol-smoke",
        "text": "synthetic test",
        "language": "en-us",
        "voice_id": "af_heart",
        "output_name": "voiceover.wav",
        "chunk_chars": 1200,
        "speed": 1.0,
        "engine": "kokoro",
        "output_dir": str(tmp_path),
    }
    monkeypatch.setattr(worker.sys, "stdin", io.StringIO(json.dumps(request)))
    stdout, stderr = io.StringIO(), io.StringIO()
    monkeypatch.setattr(worker.sys, "stdout", stdout)
    monkeypatch.setattr(worker.sys, "stderr", stderr)

    def noisy_adapters():
        print("adapter initialization progress")
        return [object()]

    def noisy_pipeline(_request, _adapters, _output_dir):
        print("model inference progress")
        return SimpleNamespace(
            request_id="stdout-protocol-smoke",
            engine_id="kokoro",
            output_path=str(tmp_path / "voiceover.wav"),
            sha256="0" * 64,
            size_bytes=100,
            duration_seconds=0.25,
            chunks=1,
            manifest_path=str(tmp_path / "voiceover.wav.manifest.json"),
        )

    monkeypatch.setattr(worker, "default_adapters", noisy_adapters)
    monkeypatch.setattr(worker, "run_pipeline", noisy_pipeline)

    assert worker.main() == 0
    lines = stdout.getvalue().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["ok"] is True
    assert "adapter initialization progress" in stderr.getvalue()
    assert "model inference progress" in stderr.getvalue()


def test_worker_resolves_v2_profile_and_routes_controls_without_exposing_private_data(monkeypatch, tmp_path):
    store = tmp_path / "profile-store"
    profile = create_profile(store, profile_id="news_reader", name="News Reader", engine_id="kokoro",
        mode="preset", language="en", voice_id="af_heart", controls={"speed": 1.15})
    request = {
        "request_id": "request-1", "text": "A short test.", "chunk_chars": 1200,
        "output_name": "voiceover.wav", "engine": "kokoro", "voice_profile_id": "news_reader",
        "profile_store_dir": str(store), "output_dir": str(tmp_path / "output"),
    }
    monkeypatch.setattr(worker.sys, "stdin", io.StringIO(json.dumps(request)))
    stdout, stderr = io.StringIO(), io.StringIO()
    monkeypatch.setattr(worker.sys, "stdout", stdout)
    monkeypatch.setattr(worker.sys, "stderr", stderr)
    adapter = object()
    routed = {}
    def build_adapters(actual_profile, actual_store):
        routed["profile"] = actual_profile
        routed["store"] = actual_store
        return [adapter]
    def fake_pipeline(actual_request, actual_adapters, output_dir):
        routed["request"] = actual_request
        routed["adapters"] = actual_adapters
        return SimpleNamespace(request_id=actual_request.request_id, engine_id="kokoro",
            output_path=str(Path(output_dir) / "voiceover.wav"), sha256="0" * 64, size_bytes=100,
            duration_seconds=0.25, chunks=1, manifest_path=str(Path(output_dir) / "voiceover.wav.manifest.json"))
    monkeypatch.setattr(worker, "adapters_for_profile", build_adapters)
    monkeypatch.setattr(worker, "run_pipeline", fake_pipeline)

    assert worker.main() == 0
    normalized = routed["request"]
    assert normalized.voice_id == "af_heart" and normalized.language == "en"
    assert normalized.speed == 1.15 and normalized.preferred_engine == "kokoro"
    assert normalized.voice_profile_id == "news_reader" and normalized.voice_mode == "preset"
    assert routed["profile"]["profile_id"] == profile["profile_id"] and routed["adapters"] == [adapter]
    response = json.loads(stdout.getvalue())
    assert response["ok"] is True
    assert "voice_description" not in stdout.getvalue() and str(store) not in stdout.getvalue()


def test_worker_missing_profile_returns_stable_path_safe_error(monkeypatch, tmp_path):
    request = {"request_id": "request-2", "text": "test", "engine": "kokoro",
        "voice_profile_id": "missing", "profile_store_dir": str(tmp_path / "private-store"),
        "output_dir": str(tmp_path / "output")}
    monkeypatch.setattr(worker.sys, "stdin", io.StringIO(json.dumps(request)))
    stdout = io.StringIO(); monkeypatch.setattr(worker.sys, "stdout", stdout)
    assert worker.main() == 2
    response = json.loads(stdout.getvalue())
    assert response["error"] == "PROFILE_NOT_FOUND_OR_UNSAFE"
    assert str(tmp_path) not in stdout.getvalue()
