from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import voiceover_preflight as preflight
from voiceover_preflight import Check, run_preflight


def _fake_probes(monkeypatch, available=False):
    class Probe:
        def __init__(self, engine_id):
            self.engine_id = engine_id
            self.package_available = available
            self.inference_verified = False
            self.model_id = None
            self.model_cached = None
            self.reason = "test fixture only"
        def to_dict(self):
            return self.__dict__.copy()
    monkeypatch.setattr(preflight, "probe_engines",
                        lambda: [Probe("qwen3_tts"), Probe("chatterbox"), Probe("kokoro")])


def test_preflight_schema_and_engine_count(tmp_path, monkeypatch):
    _fake_probes(monkeypatch)
    report = run_preflight(tmp_path)
    data = report.to_dict()
    assert data["schema_version"] == 1
    assert len(data["engines"]) == 3
    assert all("inference_verified" in item for item in data["engines"])


def test_preflight_never_claims_inference(monkeypatch, tmp_path):
    _fake_probes(monkeypatch, available=True)
    report = run_preflight(tmp_path)
    assert all(item["inference_verified"] is False for item in report.engines)


def test_preflight_missing_all_packages_is_blocked(monkeypatch, tmp_path):
    _fake_probes(monkeypatch, available=False)
    assert run_preflight(tmp_path).overall_status == "BLOCKED_DEPENDENCIES"


def test_preflight_installed_package_only_ready_to_attempt(monkeypatch, tmp_path):
    _fake_probes(monkeypatch, available=True)
    assert run_preflight(tmp_path).overall_status == "READY_TO_ATTEMPT"


def test_preflight_unknown_engine_fails(monkeypatch, tmp_path):
    _fake_probes(monkeypatch)
    report = run_preflight(tmp_path, requested_engine="not_real")
    assert report.overall_status == "FAIL"
    assert next(c for c in report.checks if c.id == "requested_engine").status == "FAIL"


@pytest.mark.parametrize("engine", ["qwen3_tts", "chatterbox", "kokoro"])
def test_preflight_requested_missing_engine_fails(monkeypatch, tmp_path, engine):
    _fake_probes(monkeypatch, available=False)
    report = run_preflight(tmp_path, requested_engine=engine)
    assert report.overall_status == "FAIL"


def test_preflight_requested_installed_engine_passes(monkeypatch, tmp_path):
    _fake_probes(monkeypatch, available=True)
    report = run_preflight(tmp_path, requested_engine="kokoro")
    assert next(c for c in report.checks if c.id == "requested_engine").status == "PASS"


def test_preflight_write_check_creates_parent(tmp_path, monkeypatch):
    _fake_probes(monkeypatch)
    target = tmp_path / "nested" / "output"
    report = run_preflight(target)
    assert target.is_dir()
    assert next(c for c in report.checks if c.id == "output_write").status == "PASS"


def test_preflight_report_is_json_serializable(monkeypatch, tmp_path):
    _fake_probes(monkeypatch)
    json.dumps(run_preflight(tmp_path).to_dict(), allow_nan=False)


def test_preflight_does_not_download_models(monkeypatch, tmp_path):
    _fake_probes(monkeypatch)
    report = run_preflight(tmp_path)
    assert not any("download" in c.detail.lower() and c.status == "PASS" for c in report.checks)


def test_preflight_reports_runtime_version(monkeypatch, tmp_path):
    _fake_probes(monkeypatch)
    assert run_preflight(tmp_path).python_version.startswith("3.")


def test_preflight_reports_platform(monkeypatch, tmp_path):
    _fake_probes(monkeypatch)
    assert run_preflight(tmp_path).platform


def test_preflight_has_stable_check_ids(monkeypatch, tmp_path):
    _fake_probes(monkeypatch)
    ids = [c.id for c in run_preflight(tmp_path).checks]
    assert ids[:3] == ["output_write", "python", "json_runtime"]


def test_cli_preflight_json_contract(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "scripts/preflight_voiceover.py"),
                             "--output-dir", str(tmp_path / "out")],
                            text=True, capture_output=True, timeout=20)
    data = json.loads(result.stdout)
    assert data["schema_version"] == 1
    assert len(data["engines"]) == 3
    assert data["overall_status"] in {"BLOCKED_DEPENDENCIES", "READY_TO_ATTEMPT", "FAIL"}


def test_runner_help_is_available():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/run_voiceover.py"), "--help"],
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0
    assert "--timeout-seconds" in result.stdout


@pytest.mark.parametrize("timeout", ["0", "0.09", "86401", "nan", "inf"])
def test_runner_rejects_bad_timeout(tmp_path, timeout):
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/run_voiceover.py"),
                             "--request", str(request), "--output-dir", str(tmp_path / "out"),
                             "--timeout-seconds", timeout], text=True, capture_output=True, timeout=20)
    assert result.returncode == 2


def test_runner_invalid_request_file_is_structured(tmp_path):
    request = tmp_path / "bad.json"
    request.write_text("{broken", encoding="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/run_voiceover.py"),
                             "--request", str(request), "--output-dir", str(tmp_path / "out")],
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 2
    assert json.loads(result.stdout)["error"] == "REQUEST_FILE_INVALID"


def test_runner_rejects_non_object_request(tmp_path):
    request = tmp_path / "array.json"
    request.write_text("[]", encoding="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/run_voiceover.py"),
                             "--request", str(request), "--output-dir", str(tmp_path / "out")],
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 2
    assert json.loads(result.stdout)["error"] == "REQUEST_MUST_BE_OBJECT"


@pytest.mark.parametrize("reserved", ["output_dir", "engine"])
def test_runner_rejects_reserved_request_fields(tmp_path, reserved):
    request = tmp_path / "reserved.json"
    request.write_text(json.dumps({"request_id": "r1", reserved: "override"}), encoding="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/run_voiceover.py"),
                             "--request", str(request), "--output-dir", str(tmp_path / "out")],
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 2
    assert json.loads(result.stdout)["error"] == "RESERVED_REQUEST_FIELD"


def test_worker_invalid_json_is_structured():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/voiceover_worker.py")],
                            input="{broken", text=True, capture_output=True, timeout=20)
    assert result.returncode == 2
    assert json.loads(result.stdout)["error"] == "INVALID_REQUEST_JSON"


def test_worker_does_not_emit_traceback_on_bad_input():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/voiceover_worker.py")],
                            input="null", text=True, capture_output=True, timeout=20)
    assert result.returncode == 2
    assert "Traceback" not in result.stdout
    assert json.loads(result.stdout)["error"] == "INVALID_REQUEST_JSON"


def test_worker_requires_output_directory():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/voiceover_worker.py")],
                            input=json.dumps({"request_id": "r1", "text": "hi", "language": "en",
                                              "voice_id": "default"}), text=True, capture_output=True, timeout=20)
    assert result.returncode == 2
    assert json.loads(result.stdout)["error"] == "INVALID_OUTPUT_DIR"


def test_real_run_fails_cleanly_when_engines_missing(tmp_path):
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"request_id": "r1", "text": "hello world",
                                   "language": "en", "voice_id": "default"}), encoding="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/run_voiceover.py"),
                             "--request", str(request), "--output-dir", str(tmp_path / "out"),
                             "--timeout-seconds", "15"], text=True, capture_output=True, timeout=25)
    data = json.loads(result.stdout)
    if data.get("error") == "PREFERRED_ENGINE_UNAVAILABLE" or data.get("error") == "NO_COMPATIBLE_ENGINE":
        assert result.returncode == 2
        assert not (tmp_path / "out" / "voiceover.wav").exists()
    else:
        # On systems with a TTS engine installed, inference may run; this test does not
        # claim real inference merely because the adapter package is present.
        assert result.returncode in {0, 2, 3}


@pytest.mark.parametrize("engine", ["qwen3_tts", "chatterbox", "kokoro"])
def test_probe_cli_lists_each_engine(engine):
    result = subprocess.run([sys.executable, str(ROOT / "scripts/probe_tts_engines.py")],
                            text=True, capture_output=True, timeout=20)
    data = json.loads(result.stdout)
    assert engine in {item["engine_id"] for item in data["engines"]}
    assert data["inference_verified"] is False


def test_probe_require_any_package_exit_contract():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/probe_tts_engines.py"),
                             "--require-any-package"], text=True, capture_output=True, timeout=20)
    data = json.loads(result.stdout)
    if not any(item["package_available"] for item in data["engines"]):
        assert result.returncode == 1
    else:
        assert result.returncode == 0


def test_output_request_path_not_used_as_subprocess_command(tmp_path):
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"request_id": "r1; echo BAD", "text": "hi",
                                   "language": "en", "voice_id": "default"}), encoding="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/run_voiceover.py"),
                             "--request", str(request), "--output-dir", str(tmp_path / "out"),
                             "--timeout-seconds", "15"], text=True, capture_output=True, timeout=25)
    assert "BAD" not in result.stdout
    assert not (tmp_path / "BAD").exists()


def test_failed_preflight_does_not_create_audio_artifact(monkeypatch, tmp_path):
    _fake_probes(monkeypatch, available=False)
    run_preflight(tmp_path)
    assert not (tmp_path / "voiceover.wav").exists()


def test_runner_timeout_is_reported_without_traceback(tmp_path, monkeypatch, capsys):
    import scripts.run_voiceover as runner
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"request_id": "r1", "text": "hello",
                                   "language": "en", "voice_id": "default"}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["run_voiceover.py", "--request", str(request),
                                      "--output-dir", str(tmp_path / "out"),
                                      "--timeout-seconds", "0.5"])
    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="worker", timeout=0.5)
    monkeypatch.setattr(runner, "execute_worker", timed_out)
    assert runner.main() == 124
    data = json.loads(capsys.readouterr().out)
    assert data["error"] == "INFERENCE_TIMEOUT"
    assert data["timeout_seconds"] == 0.5


def test_runner_invalid_worker_stdout_is_protocol_error(tmp_path, monkeypatch, capsys):
    import scripts.run_voiceover as runner
    from types import SimpleNamespace
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"request_id": "r1", "text": "hello",
                                   "language": "en", "voice_id": "default"}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["run_voiceover.py", "--request", str(request),
                                      "--output-dir", str(tmp_path / "out")])
    monkeypatch.setattr(runner, "execute_worker",
                        lambda *args, **kwargs: SimpleNamespace(stdout="not-json", returncode=3))
    assert runner.main() == 3
    assert json.loads(capsys.readouterr().out)["error"] == "WORKER_PROTOCOL_ERROR"


def test_runner_valid_worker_stdout_is_forwarded(tmp_path, monkeypatch, capsys):
    import scripts.run_voiceover as runner
    from types import SimpleNamespace
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"request_id": "r1", "text": "hello",
                                   "language": "en", "voice_id": "default"}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["run_voiceover.py", "--request", str(request),
                                      "--output-dir", str(tmp_path / "out")])
    monkeypatch.setattr(runner, "execute_worker",
                        lambda *args, **kwargs: SimpleNamespace(stdout='{"ok":false,"error":"X"}', returncode=2))
    assert runner.main() == 2
    assert json.loads(capsys.readouterr().out)["error"] == "X"
