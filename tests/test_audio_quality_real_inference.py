from __future__ import annotations
import hashlib
import io
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import wave

import pytest
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from audio_quality import AudioQualityError, inspect_wav
from scripts.real_inference_smoke import evaluate_result


def wav_bytes(samples, *, rate=16000, channels=1, width=2):
    payload = io.BytesIO()
    with wave.open(payload, "wb") as out:
        out.setnchannels(channels); out.setsampwidth(width); out.setframerate(rate)
        if width == 1:
            raw = bytes(max(0, min(255, x + 128)) for x in samples)
        else:
            raw = b"".join(int(x).to_bytes(width, "little", signed=True) for x in samples)
        out.writeframes(raw)
    return payload.getvalue()


def result_for(payload, output_dir, *, duration=None):
    path = output_dir / "voiceover.wav"; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(payload)
    inspected = inspect_wav(payload).to_dict()
    duration = inspected["duration_seconds"] if duration is None else duration
    manifest_path = output_dir / "voiceover.wav.manifest.json"
    manifest = {"manifest_version": 1, "request_id": "test-1", "engine_id": "test_engine",
                "audio": {"file": path.name, "sha256": hashlib.sha256(payload).hexdigest(),
                          "size_bytes": len(payload), "sample_rate_hz": inspected["sample_rate_hz"],
                          "frames": inspected["frames"], "duration_seconds": inspected["duration_seconds"]}}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    data = {"ok": True, "result": {"request_id": "test-1", "engine_id": "test_engine",
            "output_path": str(path), "manifest_path": str(manifest_path),
            "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload),
            "duration_seconds": duration}}
    return evaluate_result(data, 0, output_dir, min_duration=0.01, max_duration=5,
                           max_silence_ratio=0.98, max_clipping_ratio=0.01)


def test_inspect_reports_format_duration_and_hash():
    payload = wav_bytes([1000] * 1600)
    report = inspect_wav(payload)
    assert report.format == "wav-pcm" and report.duration_seconds == 0.1
    assert report.sha256 == hashlib.sha256(payload).hexdigest()
    assert report.size_bytes == len(payload)


def test_inspect_reports_non_silent_audio():
    report = inspect_wav(wav_bytes([5000, -5000] * 1000))
    assert report.all_silent is False and report.peak_normalized > 0
    assert report.rms_normalized > 0


def test_inspect_detects_all_silent_audio():
    report = inspect_wav(wav_bytes([0] * 1600))
    assert report.all_silent and "ALL_SILENT_AUDIO" in report.warnings
    assert report.silent_frame_ratio == 1


def test_inspect_detects_clipping():
    report = inspect_wav(wav_bytes([32767] * 1000))
    assert report.clipping_sample_ratio == 1
    assert "CLIPPING_SAMPLES_DETECTED" in report.warnings


@pytest.mark.parametrize("width, samples", [
    (1, [0, 1, -1, 20, -20]),
    (2, [0, 1, -1, 1000, -1000]),
    (3, [0, 1, -1, 100000, -100000]),
    (4, [0, 1, -1, 1000000, -1000000]),
])
def test_pcm_sample_widths_supported(width, samples):
    report = inspect_wav(wav_bytes(samples, width=width))
    assert report.sample_width_bytes == width


@pytest.mark.parametrize("rate", [8000, 16000, 24000, 44100, 48000, 96000])
def test_common_sample_rates_supported(rate):
    report = inspect_wav(wav_bytes([1000] * rate, rate=rate))
    assert report.sample_rate_hz == rate and report.duration_seconds == 1


@pytest.mark.parametrize("channels", [1, 2])
def test_mono_and_stereo_supported(channels):
    report = inspect_wav(wav_bytes([1000] * 1600 * channels, channels=channels))
    assert report.channels == channels


def test_rejects_empty_payload():
    with pytest.raises(AudioQualityError, match="AUDIO_EMPTY"):
        inspect_wav(b"")


def test_rejects_non_wav_payload():
    with pytest.raises(AudioQualityError, match="INVALID_WAV"):
        inspect_wav(b"not-a-wave-file" * 5)


def test_rejects_payload_over_size_limit():
    payload = wav_bytes([1000] * 100)
    with pytest.raises(AudioQualityError, match="AUDIO_TOO_LARGE"):
        inspect_wav(payload, max_bytes=50)


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), float("inf")])
def test_rejects_invalid_silence_threshold(threshold):
    with pytest.raises(AudioQualityError, match="INVALID_SILENCE_THRESHOLD"):
        inspect_wav(wav_bytes([1] * 100), silence_threshold=threshold)


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), float("inf")])
def test_rejects_invalid_clipping_threshold(threshold):
    with pytest.raises(AudioQualityError, match="INVALID_CLIPPING_THRESHOLD"):
        inspect_wav(wav_bytes([1] * 100), clipping_threshold=threshold)


def test_rejects_bad_max_bytes():
    with pytest.raises(AudioQualityError, match="INVALID_MAX_BYTES"):
        inspect_wav(wav_bytes([1] * 100), max_bytes=1)


def test_quality_report_json_serializable():
    report = inspect_wav(wav_bytes([1000] * 100)).to_dict()
    encoded = json.dumps(report, allow_nan=False, sort_keys=True)
    assert json.loads(encoded)["schema_version"] == 1


def test_real_smoke_pass_requires_integrity_and_valid_audio(tmp_path):
    report = result_for(wav_bytes([1000] * 1600), tmp_path)
    assert report["status"] == "PASS" and report["inference_verified"] is True


def test_real_smoke_fails_on_hash_mismatch(tmp_path):
    payload = wav_bytes([1000] * 1600)
    path = tmp_path / "voiceover.wav"; path.write_bytes(payload)
    data = {"ok": True, "result": {"request_id": "test-1", "engine_id": "test_engine",
            "output_path": str(path), "manifest_path": str(tmp_path / "missing.manifest.json"), "sha256": "0" * 64, "size_bytes": len(payload)}}
    report = evaluate_result(data, 0, tmp_path, min_duration=.01, max_duration=5,
                             max_silence_ratio=.98, max_clipping_ratio=.01)
    assert report["status"] == "FAIL" and not report["inference_verified"]


def test_real_smoke_blocks_missing_engine(tmp_path):
    report = evaluate_result({"ok": False, "error": "NO_COMPATIBLE_ENGINE"}, 2, tmp_path,
                             min_duration=.01, max_duration=5, max_silence_ratio=.98,
                             max_clipping_ratio=.01)
    assert report["status"] == "BLOCKED" and not report["inference_verified"]


def test_real_smoke_fails_on_missing_artifact(tmp_path):
    report = evaluate_result({"ok": True, "result": {"output_path": str(tmp_path / "missing.wav")}}, 0, tmp_path,
                             min_duration=.01, max_duration=5, max_silence_ratio=.98,
                             max_clipping_ratio=.01)
    assert report["error"] == "AUDIO_ARTIFACT_MISSING_OR_UNSAFE"


def test_real_smoke_fails_if_artifact_outside_output_dir(tmp_path):
    elsewhere = tmp_path / "outside.wav"; elsewhere.write_bytes(wav_bytes([1000] * 1000))
    out = tmp_path / "out"; out.mkdir()
    data = {"ok": True, "result": {"output_path": str(elsewhere)}}
    report = evaluate_result(data, 0, out, min_duration=.01, max_duration=5,
                             max_silence_ratio=.98, max_clipping_ratio=.01)
    assert report["status"] == "FAIL"


def test_real_smoke_rejects_all_silence(tmp_path):
    report = result_for(wav_bytes([0] * 1600), tmp_path)
    assert report["status"] == "FAIL" and not report["inference_verified"]


def test_audio_inspector_cli_outputs_json(tmp_path):
    path = tmp_path / "sample.wav"; path.write_bytes(wav_bytes([1000] * 1600))
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/inspect_voiceover_audio.py"), str(path)],
                          capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0 and json.loads(proc.stdout)["ok"] is True


def test_audio_inspector_cli_handles_missing_file(tmp_path):
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/inspect_voiceover_audio.py"), str(tmp_path / "x.wav")],
                          capture_output=True, text=True, timeout=15)
    assert proc.returncode == 2 and json.loads(proc.stdout)["error"] == "AUDIO_FILE_UNREADABLE"


def test_real_inference_cli_help():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/real_inference_smoke.py"), "--help"],
                          capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0 and "--max-silence-ratio" in proc.stdout


def test_real_smoke_rejects_too_short_audio(tmp_path):
    report = evaluate_result({"ok": True, "result": {"output_path": str((tmp_path / "voiceover.wav"))}}, 0, tmp_path,
                             min_duration=1, max_duration=5, max_silence_ratio=.98, max_clipping_ratio=.01)
    assert report["status"] == "FAIL"


def test_real_smoke_rejects_too_long_audio(tmp_path):
    payload = wav_bytes([1000] * 1600)
    path = tmp_path / "voiceover.wav"; path.write_bytes(payload)
    info = inspect_wav(payload).to_dict()
    manifest_path = tmp_path / "voiceover.wav.manifest.json"
    manifest_path.write_text(json.dumps({"manifest_version": 1, "request_id": "test-1", "engine_id": "test_engine", "audio": {"file": path.name, "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload), "sample_rate_hz": info["sample_rate_hz"], "frames": info["frames"], "duration_seconds": info["duration_seconds"]}}), encoding="utf-8")
    data = {"ok": True, "result": {"output_path": str(path), "manifest_path": str(manifest_path), "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload), "request_id": "test-1", "engine_id": "test_engine", "duration_seconds": info["duration_seconds"]}}
    report = evaluate_result(data, 0, tmp_path, min_duration=.01, max_duration=.05,
                             max_silence_ratio=.98, max_clipping_ratio=.01)
    assert report["status"] == "FAIL"


def test_real_smoke_respects_silence_ratio_threshold(tmp_path):
    payload = wav_bytes([0] * 1599 + [1000])
    path = tmp_path / "voiceover.wav"; path.write_bytes(payload)
    info = inspect_wav(payload).to_dict()
    manifest_path = tmp_path / "voiceover.wav.manifest.json"
    manifest_path.write_text(json.dumps({"manifest_version": 1, "request_id": "test-1", "engine_id": "test_engine", "audio": {"file": path.name, "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload), "sample_rate_hz": info["sample_rate_hz"], "frames": info["frames"], "duration_seconds": info["duration_seconds"]}}), encoding="utf-8")
    data = {"ok": True, "result": {"output_path": str(path), "manifest_path": str(manifest_path), "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload), "request_id": "test-1", "engine_id": "test_engine", "duration_seconds": info["duration_seconds"]}}
    report = evaluate_result(data, 0, tmp_path, min_duration=.01, max_duration=5,
                             max_silence_ratio=.5, max_clipping_ratio=.01)
    assert report["status"] == "FAIL"


def test_real_smoke_respects_clipping_threshold(tmp_path):
    payload = wav_bytes([32767] * 1600)
    path = tmp_path / "voiceover.wav"; path.write_bytes(payload)
    info = inspect_wav(payload).to_dict()
    manifest_path = tmp_path / "voiceover.wav.manifest.json"
    manifest_path.write_text(json.dumps({"manifest_version": 1, "request_id": "test-1", "engine_id": "test_engine", "audio": {"file": path.name, "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload), "sample_rate_hz": info["sample_rate_hz"], "frames": info["frames"], "duration_seconds": info["duration_seconds"]}}), encoding="utf-8")
    data = {"ok": True, "result": {"output_path": str(path), "manifest_path": str(manifest_path), "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload), "request_id": "test-1", "engine_id": "test_engine", "duration_seconds": info["duration_seconds"]}}
    report = evaluate_result(data, 0, tmp_path, min_duration=.01, max_duration=5,
                             max_silence_ratio=.98, max_clipping_ratio=.001)
    assert report["status"] == "FAIL"


def test_real_smoke_rejects_invalid_worker_envelope(tmp_path):
    report = evaluate_result(["not", "object"], 0, tmp_path, min_duration=.01, max_duration=5,
                             max_silence_ratio=.98, max_clipping_ratio=.01)
    assert report["error"] == "WORKER_PROTOCOL_ERROR"


def test_audio_report_collision_is_not_written_over_audio(tmp_path):
    from scripts.real_inference_smoke import _emit
    payload = wav_bytes([1000] * 1600)
    audio_path = tmp_path / "voiceover.wav"; audio_path.write_bytes(payload)
    before = audio_path.read_bytes()
    report = {"schema_version": 1, "status": "PASS", "inference_verified": True,
              "audio": {"file": "voiceover.wav"}}
    emitted = _emit(report, audio_path, False, protected_output_dir=tmp_path)
    assert emitted["status"] == "FAIL"
    assert audio_path.read_bytes() == before


def test_quality_report_matches_json_schema():
    import jsonschema
    schema = json.loads((ROOT / "schemas/voiceover-audio-quality-v1.schema.json").read_text())
    jsonschema.validate(inspect_wav(wav_bytes([1000] * 100)).to_dict(), schema)


def test_smoke_failure_report_matches_json_schema(tmp_path):
    import jsonschema
    schema = json.loads((ROOT / "schemas/real-inference-smoke-report-v1.schema.json").read_text())
    report = evaluate_result({"ok": False, "error": "NO_COMPATIBLE_ENGINE"}, 2, tmp_path,
                             min_duration=.01, max_duration=5, max_silence_ratio=.98,
                             max_clipping_ratio=.01)
    jsonschema.validate(report, schema)


def test_smoke_success_report_matches_json_schema(tmp_path):
    import jsonschema
    schema = json.loads((ROOT / "schemas/real-inference-smoke-report-v1.schema.json").read_text())
    report = result_for(wav_bytes([1000] * 1600), tmp_path)
    jsonschema.validate(report, schema)


def test_audio_quality_values_are_bounded():
    report = inspect_wav(wav_bytes([-32768, 32767] * 20)).to_dict()
    for key in ("peak_normalized", "rms_normalized", "clipping_sample_ratio", "silent_frame_ratio"):
        assert 0 <= report[key] <= 1


def test_atomic_report_writer_creates_parent_and_valid_json(tmp_path):
    from scripts.real_inference_smoke import _atomic_json
    path = tmp_path / "nested" / "report.json"
    _atomic_json(path, {"schema_version": 1, "status": "BLOCKED", "inference_verified": False, "checks": []})
    assert json.loads(path.read_text())["status"] == "BLOCKED"


def test_atomic_report_writer_leaves_no_temp_files(tmp_path):
    from scripts.real_inference_smoke import _atomic_json
    _atomic_json(tmp_path / "report.json", {"status": "BLOCKED"})
    assert list(tmp_path.iterdir()) == [tmp_path / "report.json"]


def test_report_audio_collision_returns_failure(tmp_path, capsys):
    from scripts.real_inference_smoke import _emit
    path = tmp_path / "voiceover.wav"; path.write_bytes(wav_bytes([1000] * 1600))
    result = _emit({"schema_version": 1, "status": "PASS", "inference_verified": True,
                    "audio": {"file": path.name}}, path, False, protected_output_dir=tmp_path)
    assert result["status"] == "FAIL" and result["error"] == "REPORT_PATH_COLLIDES_WITH_AUDIO"
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


def test_real_inference_cli_reports_blocked_when_no_engine_is_available(tmp_path):
    import importlib.util
    if any(importlib.util.find_spec(name) is not None for name in ("qwen_tts", "chatterbox", "kokoro")):
        pytest.skip("at least one optional engine package is installed")
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"request_id": "smoke001", "text": "Short smoke test.",
                                   "language": "en", "voice_id": "af_heart"}), encoding="utf-8")
    out = tmp_path / "out"
    report_path = tmp_path / "report.json"
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/real_inference_smoke.py"),
                           "--request", str(request), "--output-dir", str(out),
                           "--timeout-seconds", "10", "--report", str(report_path)],
                          capture_output=True, text=True, timeout=20)
    report = json.loads(proc.stdout)
    assert proc.returncode == 3 and report["status"] == "BLOCKED"
    assert report["inference_verified"] is False
    assert not (out / "voiceover.wav").exists()
    assert json.loads(report_path.read_text())["status"] == "BLOCKED"


def test_real_inference_smoke_forwards_profile_store_for_v2_request(tmp_path, monkeypatch, capsys):
    from scripts import real_inference_smoke as smoke

    request = tmp_path / "request.json"
    request.write_text(json.dumps({"protocol_version": 2, "message_type": "synthesis.request"}),
                       encoding="utf-8")
    profile_store = tmp_path / "profiles"
    captured = {}

    def fake_run(command, **_kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 3, '{"ok":false,"error":"NO_COMPATIBLE_ENGINE"}', "")

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", [str(ROOT / "scripts/real_inference_smoke.py"),
                                      "--request", str(request), "--output-dir", str(tmp_path / "out"),
                                      "--profile-store", str(profile_store)])

    assert smoke.main() == 3
    command = captured["command"]
    assert command[command.index("--profile-store") + 1] == str(profile_store.resolve())
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"
