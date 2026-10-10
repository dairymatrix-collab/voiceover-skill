from __future__ import annotations
import json
from pathlib import Path
import sys
import pytest

import engine_setup
from engine_setup import SetupError, setup_engine, write_report


def test_plan_only_is_default_and_has_no_side_effect(tmp_path):
    root = tmp_path / "venv"
    report = setup_engine("kokoro", root)
    assert report["status"] == "PLAN_ONLY"
    assert report["executed"] is False
    assert report["model_downloaded"] is False
    assert report["inference_verified"] is False
    assert report["packages_to_install"] == list(engine_setup.ENGINE_INSTALL_PACKAGES["kokoro"])
    assert report["commands"][1][4:] == list(engine_setup.ENGINE_INSTALL_PACKAGES["kokoro"])
    assert not root.exists()
    assert report["commands"][0][2] == "venv"


def test_plan_only_all_engines(tmp_path):
    for engine in ("kokoro", "chatterbox", "qwen3_tts"):
        result = setup_engine(engine, tmp_path / engine)
        assert result["engine"] == engine
        assert result["status"] == "PLAN_ONLY"
        assert result["package"]
        assert result["packages_to_install"] == list(engine_setup.ENGINE_INSTALL_PACKAGES[engine])
        assert result["commands"][1][4:] == list(engine_setup.ENGINE_INSTALL_PACKAGES[engine])


def test_cpu_only_plan_pins_official_cpu_wheels_and_does_not_install(tmp_path):
    root = tmp_path / "qwen-cpu"
    result = setup_engine("qwen3_tts", root, cpu_only=True)
    assert result["status"] == "PLAN_ONLY" and result["executed"] is False
    assert result["cpu_only"] is True and not root.exists()
    torch_cmd, engine_cmd = result["commands"][1:]
    assert engine_setup.PYTORCH_CPU_INDEX in torch_cmd
    assert "--extra-index-url" in torch_cmd and engine_setup.PYPI_INDEX in torch_cmd
    assert list(engine_setup.CPU_TORCH_PACKAGES) == torch_cmd[-2:]
    assert "qwen-tts==0.1.1" in engine_cmd
    assert not any(engine_setup._distribution_name(pkg) in {"torch", "torchaudio"}
                   for pkg in engine_cmd[4:])


def test_cpu_only_wheelhouse_plan_never_queries_indexes(tmp_path):
    wheelhouse = tmp_path / "wheels"; wheelhouse.mkdir()
    result = setup_engine("qwen3_tts", tmp_path / "qwen-cpu", cpu_only=True,
                          wheelhouse=wheelhouse, no_index=True)
    torch_cmd = result["commands"][1]
    assert "--no-index" in torch_cmd and "--find-links" in torch_cmd
    assert "--index-url" not in torch_cmd and "--extra-index-url" not in torch_cmd


@pytest.mark.parametrize("engine", ["", "Kokoro", "../kokoro", None, 4])
def test_reject_unknown_engine(engine, tmp_path):
    with pytest.raises(SetupError, match="UNKNOWN_ENGINE"):
        setup_engine(engine, tmp_path / "env")


@pytest.mark.parametrize("timeout", [True, 0, -1, 7201, float("nan"), float("inf"), "5"])
def test_reject_invalid_timeout(timeout, tmp_path):
    with pytest.raises(SetupError, match="INVALID_TIMEOUT"):
        setup_engine("kokoro", tmp_path / "env", timeout_seconds=timeout)


def test_reject_nonempty_environment_path(tmp_path):
    root = tmp_path / "occupied"
    root.mkdir(); (root / "important.txt").write_text("keep")
    with pytest.raises(SetupError, match="ENVIRONMENT_PATH_NOT_EMPTY"):
        setup_engine("kokoro", root, install=True)
    assert (root / "important.txt").read_text() == "keep"


def test_no_index_requires_wheelhouse(tmp_path):
    with pytest.raises(SetupError, match="NO_INDEX_REQUIRES_WHEELHOUSE"):
        setup_engine("kokoro", tmp_path / "env", no_index=True)


def test_missing_wheelhouse_fails_closed(tmp_path):
    with pytest.raises(SetupError, match="WHEELHOUSE_NOT_FOUND"):
        setup_engine("kokoro", tmp_path / "env", wheelhouse=tmp_path / "missing")


def test_wheelhouse_plan_is_explicit(tmp_path):
    wheelhouse = tmp_path / "wheels"; wheelhouse.mkdir()
    result = setup_engine("kokoro", tmp_path / "env", wheelhouse=wheelhouse, no_index=True)
    assert result["status"] == "PLAN_ONLY"
    assert result["no_index"] is True
    assert result["wheelhouse"] == str(wheelhouse.resolve())
    assert "--find-links" in result["commands"][1]
    assert result["commands"][1][-1] == "--no-index"
    assert not (tmp_path / "env").exists()


def test_atomic_report_output(tmp_path):
    path = tmp_path / "nested" / "report.json"
    write_report(path, {"status": "PLAN_ONLY", "inference_verified": False})
    assert json.loads(path.read_text()) == {"inference_verified": False, "status": "PLAN_ONLY"}
    assert list(path.parent.glob("*.tmp")) == []


def test_report_rejects_nan(tmp_path):
    with pytest.raises(ValueError):
        write_report(tmp_path / "bad.json", {"value": float("nan")})


def test_python_probe_failure_does_not_create_venv(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_setup, "_run", lambda *a, **k: {"returncode": 1, "stdout_tail": "", "stderr_tail": "missing"})
    with pytest.raises(SetupError, match="PYTHON_PROBE_FAILED"):
        setup_engine("kokoro", tmp_path / "env", python_executable="missing-python", install=True)
    assert not (tmp_path / "env").exists()


def test_install_rejects_python_outside_policy_before_venv(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_setup, "_run", lambda *a, **k: {"returncode": 0, "stdout_tail": "3.13.5\n", "stderr_tail": ""})
    with pytest.raises(SetupError, match="PYTHON_VERSION_UNSUPPORTED_BY_PROJECT_POLICY"):
        setup_engine("kokoro", tmp_path / "env", python_executable=sys.executable, install=True)
    assert not (tmp_path / "env").exists()


def test_install_happy_path_with_mocked_subprocess(tmp_path, monkeypatch):
    calls = []
    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        if "-c" in argv and "sys.version_info" in argv[-1]:
            return {"returncode": 0, "stdout_tail": "3.12.4\n", "stderr_tail": ""}
        return {"returncode": 0, "stdout_tail": "ok", "stderr_tail": ""}
    class FakeBuilder:
        def __init__(self, **kwargs): pass
        def create(self, path): Path(path).mkdir(parents=True)
    monkeypatch.setattr(engine_setup, "_run", fake_run)
    monkeypatch.setattr(engine_setup.venv, "EnvBuilder", FakeBuilder)
    monkeypatch.setattr(engine_setup, "_venv_python", lambda root: Path(root) / "fake-python")
    result = setup_engine("kokoro", tmp_path / "env", python_executable="python3.12", install=True)
    assert result["status"] == "PACKAGE_READY"
    assert result["executed"] is True
    assert result["inference_verified"] is False
    assert [step["id"] for step in result["steps"]] == ["create_venv", "install_engine", "pip_check", "module_probe"]
    assert all(call[0] != "shell" for call in calls)
    install_call = next(call for call in calls if call[1:4] == ["-m", "pip", "install"])
    assert install_call[4:] == list(engine_setup.ENGINE_INSTALL_PACKAGES["kokoro"])
    probe_call = next(call for call in calls if "find_spec" in call[-1])
    assert all(module in probe_call[-1] for module in engine_setup.ENGINE_REQUIRED_MODULES["kokoro"])


def test_cpu_only_install_separates_torch_and_verifies_cuda_absent(tmp_path, monkeypatch):
    calls = []
    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        if "sys.version_info" in argv[-1]:
            return {"returncode": 0, "stdout_tail": "3.12.4\n", "stderr_tail": ""}
        return {"returncode": 0, "stdout_tail": "ok", "stderr_tail": ""}
    class FakeBuilder:
        def __init__(self, **kwargs): pass
        def create(self, path): Path(path).mkdir(parents=True)
    monkeypatch.setattr(engine_setup, "_run", fake_run)
    monkeypatch.setattr(engine_setup.venv, "EnvBuilder", FakeBuilder)
    monkeypatch.setattr(engine_setup, "_venv_python", lambda root: Path(root) / "fake-python")
    result = setup_engine("qwen3_tts", tmp_path / "qwen-cpu", python_executable="python3.12",
                          install=True, cpu_only=True)
    assert result["status"] == "PACKAGE_READY" and result["cpu_only"] is True
    assert [step["id"] for step in result["steps"]] == [
        "create_venv", "install_cpu_torch", "install_engine", "pip_check", "cpu_only_probe", "module_probe"]
    installs = [call for call in calls if call[1:4] == ["-m", "pip", "install"]]
    assert len(installs) == 2
    assert installs[0][-2:] == list(engine_setup.CPU_TORCH_PACKAGES)
    assert "qwen-tts==0.1.1" in installs[1]
    assert "torch==2.6.0+cpu" in result["steps"][0].get("stdout_tail", "") or result["packages_to_install"][0] == "torch==2.6.0+cpu"


def test_install_failure_stops_before_pip_check(tmp_path, monkeypatch):
    def fake_run(argv, **kwargs):
        if "sys.version_info" in argv[-1]:
            return {"returncode": 0, "stdout_tail": "3.11.9\n", "stderr_tail": ""}
        return {"returncode": 1, "stdout_tail": "", "stderr_tail": "network unavailable"}
    class FakeBuilder:
        def __init__(self, **kwargs): pass
        def create(self, path): Path(path).mkdir(parents=True)
    monkeypatch.setattr(engine_setup, "_run", fake_run)
    monkeypatch.setattr(engine_setup.venv, "EnvBuilder", FakeBuilder)
    result = setup_engine("kokoro", tmp_path / "env", python_executable="python3.11", install=True)
    assert result["status"] == "INSTALL_FAILED"
    assert [step["id"] for step in result["steps"]] == ["create_venv", "install_engine"]
    assert result["inference_verified"] is False


def test_pip_conflict_stops_before_import_probe(tmp_path, monkeypatch):
    def fake_run(argv, **kwargs):
        if "sys.version_info" in argv[-1]: return {"returncode": 0, "stdout_tail": "3.11.9\n", "stderr_tail": ""}
        if argv[-2:] == ["pip", "check"] or (len(argv) >= 3 and argv[-2] == "pip" and argv[-1] == "check"): return {"returncode": 1, "stdout_tail": "", "stderr_tail": "conflict"}
        return {"returncode": 0, "stdout_tail": "ok", "stderr_tail": ""}
    class FakeBuilder:
        def __init__(self, **kwargs): pass
        def create(self, path): Path(path).mkdir(parents=True)
    monkeypatch.setattr(engine_setup, "_run", fake_run)
    monkeypatch.setattr(engine_setup.venv, "EnvBuilder", FakeBuilder)
    result = setup_engine("kokoro", tmp_path / "env", python_executable="python3.11", install=True)
    assert result["status"] == "DEPENDENCY_CONFLICT"
    assert len(result["steps"]) == 3


def test_import_probe_failure_reported(tmp_path, monkeypatch):
    def fake_run(argv, **kwargs):
        if "sys.version_info" in argv[-1]: return {"returncode": 0, "stdout_tail": "3.11.9\n", "stderr_tail": ""}
        if "find_spec" in argv[-1]: return {"returncode": 1, "stdout_tail": "", "stderr_tail": ""}
        return {"returncode": 0, "stdout_tail": "ok", "stderr_tail": ""}
    class FakeBuilder:
        def __init__(self, **kwargs): pass
        def create(self, path): Path(path).mkdir(parents=True)
    monkeypatch.setattr(engine_setup, "_run", fake_run)
    monkeypatch.setattr(engine_setup.venv, "EnvBuilder", FakeBuilder)
    result = setup_engine("kokoro", tmp_path / "env", python_executable="python3.11", install=True)
    assert result["status"] == "PACKAGE_IMPORT_MISSING"
    assert result["inference_verified"] is False


def test_logs_are_bounded_and_redacted(monkeypatch):
    class Result:
        returncode = 0
        stdout = "api_key=abc123 " + "x" * 200000
        stderr = "password:sekrit"
    monkeypatch.setattr(engine_setup.subprocess, "run", lambda *a, **k: Result())
    result = engine_setup._run(["trusted"], timeout=1)
    assert len(result["stdout_tail"]) <= engine_setup.MAX_LOG_BYTES
    assert "[REDACTED]" in result["stderr_tail"]
    assert "sekrit" not in result["stderr_tail"]


def test_setup_commands_never_use_shell(monkeypatch):
    class Result:
        returncode = 0; stdout = "ok"; stderr = ""
    captured = {}
    def fake_run(*args, **kwargs):
        captured.update(kwargs); return Result()
    monkeypatch.setattr(engine_setup.subprocess, "run", fake_run)
    engine_setup._run(["python", "-V"], timeout=2)
    assert captured["shell"] is False
    assert captured["stdin"] is engine_setup.subprocess.DEVNULL


def test_invalid_boolean_flags_rejected(tmp_path):
    with pytest.raises(SetupError, match="INVALID_BOOLEAN_OPTION"):
        setup_engine("kokoro", tmp_path / "env", install=1)


def test_python_executable_nul_rejected_before_probe(tmp_path, monkeypatch):
    called = False
    def fake_run(*a, **k):
        nonlocal called; called = True
        return {"returncode": 0, "stdout_tail": "3.11.0", "stderr_tail": ""}
    monkeypatch.setattr(engine_setup, "_run", fake_run)
    with pytest.raises(SetupError, match="INVALID_PYTHON_EXECUTABLE"):
        setup_engine("kokoro", tmp_path / "env", python_executable="python\x00bad", install=True)
    assert called is False


def test_cli_plan_mode_and_atomic_report(tmp_path):
    import subprocess
    report_path = tmp_path / "report.json"
    env_path = tmp_path / "env"
    command = [sys.executable, "scripts/setup_tts_engine.py", "--engine", "kokoro",
               "--environment", str(env_path), "--report", str(report_path), "--pretty"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "PLAN_ONLY"
    assert payload["executed"] is False
    assert json.loads(report_path.read_text()) == payload
    assert not env_path.exists()


def test_cli_never_installs_without_flag(tmp_path):
    import subprocess
    env_path = tmp_path / "env"
    result = subprocess.run([sys.executable, "scripts/setup_tts_engine.py", "--engine", "kokoro",
                            "--environment", str(env_path)], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "PLAN_ONLY"
    assert not env_path.exists()


def test_cli_no_index_without_wheelhouse_is_blocked(tmp_path):
    import subprocess
    result = subprocess.run([sys.executable, "scripts/setup_tts_engine.py", "--engine", "kokoro",
                             "--environment", str(tmp_path / "env"), "--no-index"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "BLOCKED"
    assert payload["error"] == "NO_INDEX_REQUIRES_WHEELHOUSE"


def test_cli_report_schema_for_plan_and_blocked(tmp_path):
    import subprocess
    from jsonschema import Draft202012Validator
    schema = json.loads(Path("schemas/tts-engine-setup-report-v1.schema.json").read_text())
    for extra in ([], ["--no-index"]):
        command = [sys.executable, "scripts/setup_tts_engine.py", "--engine", "kokoro",
                   "--environment", str(tmp_path / ("env" + str(len(extra)))), *extra]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        payload = json.loads(result.stdout)
        assert Draft202012Validator(schema).is_valid(payload), payload


def test_setup_cli_hides_unverified_chatterbox_engine(tmp_path):
    import subprocess
    result = subprocess.run([sys.executable, "scripts/setup_tts_engine.py", "--engine", "chatterbox",
                             "--environment", str(tmp_path / "env")], capture_output=True, text=True)
    assert result.returncode == 2
    assert "invalid choice" in result.stderr
    assert not (tmp_path / "env").exists()


def test_symlink_environment_root_rejected(tmp_path):
    real = tmp_path / "real"; real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable on this platform")
    with pytest.raises(SetupError, match="SYMLINK_ENVIRONMENT_PATH"):
        setup_engine("kokoro", link)


def test_existing_empty_directory_can_be_used(tmp_path):
    root = tmp_path / "empty"; root.mkdir()
    report = setup_engine("kokoro", root)
    assert report["status"] == "PLAN_ONLY"
    assert list(root.iterdir()) == []


def test_report_schema_rejects_false_inference_claim(tmp_path):
    from jsonschema import Draft202012Validator
    schema = json.loads(Path("schemas/tts-engine-setup-report-v1.schema.json").read_text())
    report = setup_engine("kokoro", tmp_path / "env")
    report["inference_verified"] = True
    assert not Draft202012Validator(schema).is_valid(report)
