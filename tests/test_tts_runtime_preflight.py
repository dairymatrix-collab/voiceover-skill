from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys

import pytest
import tts_runtime_preflight as preflight


def _candidate(path, version=(3, 12, 1), modules=None, status="PASS"):
    return {"executable": str(path), "status": status, "supported_by_project_policy": version[:2] in ((3, 10), (3, 11), (3, 12)),
            "version": list(version), "version_text": ".".join(map(str, version)),
            "modules": modules or {"kokoro": False, "torch": True, "numpy": True, "soundfile": True,
                                   "chatterbox": False, "qwen_tts": False, "transformers": False,
                                   "torchaudio": False, "accelerate": False}}


def test_version_tuple_accepts_valid_int_list():
    assert preflight._version_tuple([3, 12, 1]) == (3, 12, 1)

@pytest.mark.parametrize("value", [[3, True, 1], [3, 12], "3.12.1", [3, -1, 0], [3, 12, 1.0], None])
def test_version_tuple_rejects_invalid(value):
    assert preflight._version_tuple(value) is None

@pytest.mark.parametrize("timeout", [0, -1, 31, True, float("nan"), "5"])
def test_interpreter_timeout_rejected(timeout):
    with pytest.raises(ValueError):
        preflight.discover_interpreters(timeout_seconds=timeout)

@pytest.mark.parametrize("candidate", ["", "  ", "bad\x00path", None, 4])
def test_invalid_extra_candidate_rejected(candidate):
    with pytest.raises(ValueError):
        preflight.discover_interpreters([candidate])


def test_discovery_uses_shell_false_and_isolated_mode(monkeypatch, tmp_path):
    executable = tmp_path / "python3.12"
    executable.write_text("x")
    calls = []
    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, json.dumps({"executable": str(executable), "version": [3, 12, 2],
            "implementation": "CPython", "machine": "x86_64", "bits": "64bit", "modules": {"pip": True}}), "")
    monkeypatch.setattr(preflight.shutil, "which", lambda x: str(executable) if x == "python3.12" else None)
    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    result = preflight.discover_interpreters([str(executable)])
    assert result["status"] == "READY_FOR_ENGINE_PREFLIGHT"
    assert result["selected_python_version"] == "3.12.2"
    assert calls and calls[0][0][1:3] == ["-I", "-c"]
    assert calls[0][1]["shell"] is False


def test_discovery_reports_no_supported_interpreter(monkeypatch, tmp_path):
    executable = tmp_path / "python"
    executable.write_text("x")
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, json.dumps({"executable": str(executable), "version": [3, 13, 5],
            "implementation": "CPython", "machine": "x86_64", "bits": "64bit", "modules": {}}), "")
    monkeypatch.setattr(preflight.shutil, "which", lambda x: str(executable) if x == "python" else None)
    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    result = preflight.discover_interpreters([str(executable)])
    assert result["status"] == "NO_SUPPORTED_INTERPRETER"
    assert result["selected_interpreter"] is None
    assert result["inference_verified"] is False


def test_discovery_classifies_timeout(monkeypatch, tmp_path):
    executable = tmp_path / "python"
    executable.write_text("x")
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr(preflight.shutil, "which", lambda x: str(executable) if x == "python" else None)
    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    result = preflight.discover_interpreters([str(executable)])
    assert all(x["status"] == "PROBE_TIMEOUT" for x in result["interpreters"])


def test_discovery_classifies_nonzero_probe(monkeypatch, tmp_path):
    executable = tmp_path / "python"
    executable.write_text("x")
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, "", "broken")
    monkeypatch.setattr(preflight.shutil, "which", lambda x: str(executable) if x == "python" else None)
    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    result = preflight.discover_interpreters([str(executable)])
    assert result["interpreters"][0]["status"] == "PROBE_FAILED"
    assert "broken" in result["interpreters"][0]["detail"]


@pytest.mark.parametrize("urls", [["http://evil.example"], ["https://example.com"], ["https://pypi.org.evil.test/"]])
def test_network_probe_rejects_unapproved_urls(urls):
    with pytest.raises(ValueError):
        preflight.probe_network(urls)

@pytest.mark.parametrize("timeout", [0, 16, True, "3"])
def test_network_timeout_bounds(timeout):
    with pytest.raises(ValueError):
        preflight.probe_network(timeout_seconds=timeout)


def test_network_probe_records_reachable(monkeypatch):
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
    monkeypatch.setattr(preflight.urllib.request, "urlopen", lambda *a, **k: Response())
    result = preflight.probe_network(["https://pypi.org/simple/"], timeout_seconds=1)
    assert result[0]["status"] == "REACHABLE"
    assert result[0]["http_status"] == 200


def test_network_probe_treats_http_error_as_reachable(monkeypatch):
    def fake(*args, **kwargs):
        raise preflight.urllib.error.HTTPError("https://pypi.org/simple/", 403, "blocked", {}, None)
    monkeypatch.setattr(preflight.urllib.request, "urlopen", fake)
    result = preflight.probe_network(["https://pypi.org/simple/"], timeout_seconds=1)
    assert result[0]["status"] == "REACHABLE_HTTP_ERROR"
    assert result[0]["http_status"] == 403


def test_network_probe_redacts_details_to_error_class(monkeypatch):
    def fake(*args, **kwargs):
        raise preflight.urllib.error.URLError("secret-token-value")
    monkeypatch.setattr(preflight.urllib.request, "urlopen", fake)
    result = preflight.probe_network(["https://pypi.org/simple/"], timeout_seconds=1)
    assert result[0]["status"] == "UNREACHABLE"
    assert "secret-token-value" not in json.dumps(result)


def test_wheelhouse_missing(tmp_path):
    result = preflight.audit_wheelhouse(tmp_path / "absent")
    assert result["status"] == "WHEELHOUSE_NOT_FOUND"
    assert result["wheel_count"] == 0


def test_wheelhouse_empty(tmp_path):
    result = preflight.audit_wheelhouse(tmp_path)
    assert result["status"] == "EMPTY_WHEELHOUSE"


def test_wheelhouse_inventory_normalizes_distribution_names(tmp_path):
    (tmp_path / "numpy-2.0.0-cp312-cp312-manylinux.whl").touch()
    (tmp_path / "soundfile-0.12.1-py3-none-any.whl").touch()
    (tmp_path / "notes.txt").touch()
    result = preflight.audit_wheelhouse(tmp_path)
    assert result["status"] == "PASS"
    assert result["wheel_count"] == 2
    assert {p["normalized_name"] for p in result["packages"]} == {"numpy", "soundfile"}
    assert "not validated" in result["warning"]


@pytest.mark.parametrize("max_files", [0, -1, 100001, True, "3"])
def test_wheelhouse_invalid_limit(max_files, tmp_path):
    with pytest.raises(ValueError):
        preflight.audit_wheelhouse(tmp_path, max_files=max_files)


def test_wheelhouse_ignores_symlinked_wheel(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("not a wheel")
    (tmp_path / "pretend-1.0-py3-none-any.whl").symlink_to(target)
    assert preflight.audit_wheelhouse(tmp_path)["wheel_count"] == 0


def test_wheelhouse_truncation(tmp_path):
    for n in range(3):
        (tmp_path / f"demo{n}-1.0-py3-none-any.whl").touch()
    result = preflight.audit_wheelhouse(tmp_path, max_files=2)
    assert result["wheel_count"] == 2
    assert result["truncated"] is True


def test_unknown_engine_rejected():
    with pytest.raises(ValueError):
        preflight.collect_preflight("unknown", check_network=False)


def test_collect_preflight_never_claims_install_or_inference(monkeypatch):
    monkeypatch.setattr(preflight, "discover_interpreters", lambda extra_candidates=(): {
        "schema_version": 1, "status": "NO_SUPPORTED_INTERPRETER", "interpreters": [], "selected_interpreter": None,
        "selected_python_version": None})
    result = preflight.collect_preflight("kokoro", check_network=False)
    assert result["status"] == "NO_SUPPORTED_INTERPRETER"
    assert result["diagnostic_only"] is True
    assert result["installation_performed"] is False
    assert result["model_downloaded"] is False
    assert result["inference_verified"] is False


def test_collect_preflight_marks_network_unavailable(monkeypatch):
    monkeypatch.setattr(preflight, "discover_interpreters", lambda extra_candidates=(): {
        "schema_version": 1, "status": "READY_FOR_ENGINE_PREFLIGHT", "interpreters": [_candidate("/py")],
        "selected_interpreter": "/py", "selected_python_version": "3.12.1"})
    monkeypatch.setattr(preflight, "probe_network", lambda: [{"url": "https://pypi.org/simple/", "status": "UNREACHABLE"}])
    result = preflight.collect_preflight("kokoro", check_network=True)
    assert result["status"] == "NETWORK_UNAVAILABLE"
    assert result["network_ready"] is False


def test_collect_preflight_marks_missing_modules(monkeypatch):
    monkeypatch.setattr(preflight, "discover_interpreters", lambda extra_candidates=(): {
        "schema_version": 1, "status": "READY_FOR_ENGINE_PREFLIGHT", "interpreters": [_candidate("/py")],
        "selected_interpreter": "/py", "selected_python_version": "3.12.1"})
    monkeypatch.setattr(preflight, "probe_network", lambda: [])
    result = preflight.collect_preflight("kokoro", check_network=False)
    assert result["status"] == "ENGINE_DEPENDENCIES_MISSING"
    assert "kokoro" in result["missing_engine_modules"]


def test_collect_preflight_recognizes_present_modules(monkeypatch):
    modules = {"kokoro": True, "torch": True, "numpy": True, "soundfile": True,
               "chatterbox": False, "qwen_tts": False, "transformers": False, "torchaudio": False, "accelerate": False}
    monkeypatch.setattr(preflight, "discover_interpreters", lambda extra_candidates=(): {
        "schema_version": 1, "status": "READY_FOR_ENGINE_PREFLIGHT", "interpreters": [_candidate("/py", modules=modules)],
        "selected_interpreter": "/py", "selected_python_version": "3.12.1"})
    monkeypatch.setattr(preflight, "probe_network", lambda: [])
    result = preflight.collect_preflight("kokoro", check_network=False)
    assert result["status"] == "ENGINE_PREREQUISITES_PRESENT"
    assert result["missing_engine_modules"] == []


def test_preflight_cli_emits_json_and_report(tmp_path):
    report = tmp_path / "report.json"
    command = [sys.executable, "scripts/preflight_tts_install.py", "--engine", "kokoro", "--skip-network", "--report", str(report)]
    completed = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    assert completed.returncode in (2, 3)
    parsed = json.loads(completed.stdout)
    assert parsed["diagnostic_only"] is True
    assert parsed["inference_verified"] is False
    assert json.loads(report.read_text())["status"] == parsed["status"]


def test_preflight_cli_requires_engine():
    completed = subprocess.run([sys.executable, "scripts/preflight_tts_install.py"],
                               cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10)
    assert completed.returncode == 2
    assert "--engine" in completed.stderr


def test_collect_preflight_marks_unverified_wheelhouse_when_network_down(monkeypatch, tmp_path):
    (tmp_path / "kokoro-0.9.4-py3-none-any.whl").touch()
    modules = {"kokoro": False, "torch": True, "numpy": True, "soundfile": True,
               "chatterbox": False, "qwen_tts": False, "transformers": False, "torchaudio": False, "accelerate": False}
    monkeypatch.setattr(preflight, "discover_interpreters", lambda extra_candidates=(): {
        "schema_version": 1, "status": "READY_FOR_ENGINE_PREFLIGHT", "interpreters": [_candidate("/py", modules=modules)],
        "selected_interpreter": "/py", "selected_python_version": "3.12.1"})
    monkeypatch.setattr(preflight, "probe_network", lambda: [{"url": "https://pypi.org/simple/", "status": "UNREACHABLE"}])
    result = preflight.collect_preflight("kokoro", wheelhouse=tmp_path, check_network=True)
    assert result["status"] == "WHEELHOUSE_PRESENT_UNVERIFIED"
    assert result["network_ready"] is False
    assert result["wheelhouse"]["wheel_count"] == 1
    assert result["inference_verified"] is False


def test_runtime_preflight_schema_accepts_actual_report():
    import jsonschema
    schema = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "tts-runtime-preflight-v1.schema.json").read_text())
    report = preflight.collect_preflight("kokoro", check_network=False)
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(report, schema)


def test_runtime_preflight_schema_rejects_inference_claim():
    import jsonschema
    schema = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "tts-runtime-preflight-v1.schema.json").read_text())
    report = preflight.collect_preflight("kokoro", check_network=False)
    report["inference_verified"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(report, schema)
