"""Model-free tests for read-only engine environment diagnostics."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import tts_environment as env

ROOT = Path(__file__).resolve().parents[1]


def test_d0_221_diagnostics_are_marked_non_inference():
    report = env.collect_environment()
    assert report["diagnostic_only"] is True
    assert report["inference_verified"] is False


def test_d0_222_three_engines_have_specs():
    assert set(env.ENGINE_SPECS) == {"kokoro", "chatterbox", "qwen3_tts"}


def test_d0_223_required_distributions_are_nonempty():
    assert all(spec["required_distributions"] for spec in env.ENGINE_SPECS.values())


def test_d0_224_report_is_json_serializable():
    json.dumps(env.collect_environment(), allow_nan=False)


def test_d0_225_engine_report_includes_missing_list():
    for engine in env.ENGINE_SPECS:
        assert isinstance(env.collect_environment()["engines"][engine]["missing_distributions"], list)


def test_d0_226_python_recommendation_is_caveated():
    assert "verify" in env.ENGINE_SPECS["kokoro"]["recommended_python"].lower()


def test_d0_227_install_plan_never_claims_execution():
    assert env.build_install_plan("kokoro")["executed"] is False


def test_d0_228_install_plan_has_venv_and_pip_steps():
    commands = env.build_install_plan("kokoro")["commands"]
    assert any("venv" in c for c in commands[0])
    assert any("pip" in c for c in commands[-1])


def test_d0_229_unknown_engine_fails_closed():
    with pytest.raises(ValueError):
        env.build_install_plan("not-an-engine")


def test_d0_230_cache_report_has_bounded_scan_fields():
    cache = env.collect_environment()["model_cache"]
    assert "files_scanned" in cache and "scan_truncated" in cache


def test_d0_231_binary_report_has_known_tools():
    assert set(env.collect_environment()["binaries"]) == {"ffmpeg", "espeak-ng", "espeak"}


def test_d0_232_torch_probe_is_structured():
    report = env.collect_environment()
    assert "available" in report["torch"] and "device" in report["torch"]


def test_d0_233_disk_probe_creates_path_and_reports_free_bytes(tmp_path):
    report = env.collect_environment(tmp_path / "output")
    assert report["disk"]["free_bytes"] >= 0
    assert (tmp_path / "output").is_dir()


def test_d0_234_disk_probe_failure_is_reported_not_raised(monkeypatch, tmp_path):
    def broken(path):
        raise OSError("no")
    monkeypatch.setattr(env.shutil, "disk_usage", broken)
    report = env.collect_environment(tmp_path / "output")
    assert any(c["id"] == "output_disk" and c["status"] == "FAIL" for c in report["checks"])


def test_d0_235_module_probe_handles_import_errors(monkeypatch):
    monkeypatch.setattr(env.importlib.util, "find_spec", lambda _name: (_ for _ in ()).throw(ImportError()))
    assert env._safe_module_available("anything") is False


def test_d0_236_cache_size_scan_skips_symlink_files(tmp_path, monkeypatch):
    hub = tmp_path / "hub"
    hub.mkdir()
    target = tmp_path / "outside"
    target.write_bytes(b"sensitive")
    (hub / "linked").symlink_to(target)
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    result = env._model_cache()
    assert result["hub_bytes_scanned"] == 0


def test_d0_237_report_includes_architecture_and_executable():
    python = env.collect_environment()["python"]
    assert python["architecture"] and python["executable"]


def test_d0_238_engine_commands_target_distribution_names():
    command = env.build_install_plan("qwen3_tts")["commands"][-1]
    assert "qwen-tts==0.1.1" in command


def test_install_commands_include_every_declared_runtime_distribution():
    for spec in env.ENGINE_SPECS.values():
        assert spec["install_command"][4:] == list(spec["install_packages"])


def test_d0_239_diagnostic_script_runs_json(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "scripts/diagnose_tts_environment.py"), "--pretty"],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["inference_verified"] is False


def test_d0_240_cli_selected_engine_adds_plan():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/diagnose_tts_environment.py"), "--engine", "kokoro"],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["install_plan"]["executed"] is False


def test_d0_241_strict_cli_returns_two_when_engine_missing():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/diagnose_tts_environment.py"),
                             "--engine", "qwen3_tts", "--strict-engine-ready"],
                            capture_output=True, text=True, timeout=20)
    # This test is portable: it only asserts the contract if a required package is absent.
    data = json.loads(result.stdout)
    if data["engines"]["qwen3_tts"]["missing_distributions"]:
        assert result.returncode == 2
    else:
        assert result.returncode == 0


def test_d0_242_write_json_is_atomic_and_valid(tmp_path):
    target = tmp_path / "nested" / "report.json"
    result = subprocess.run([sys.executable, str(ROOT / "scripts/diagnose_tts_environment.py"),
                             "--write-json", str(target)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0
    assert json.loads(target.read_text())["diagnostic_only"] is True
    assert not list(target.parent.glob(".report.json.*.tmp"))


def test_d0_243_json_disallows_nonfinite_values():
    json.dumps(env.collect_environment(), allow_nan=False)


def test_d0_244_qwen_cache_is_conservative_directory_presence_only():
    result = env.collect_environment()["model_cache"]
    assert isinstance(result["qwen_default_model_directory_exists"], bool)


def test_d0_245_setup_plan_warns_about_upstream_compatibility():
    assert "upstream" in env.build_install_plan("chatterbox")["warning"].lower()


def test_d0_246_no_engine_is_marked_inference_verified_by_diagnostics():
    report = env.collect_environment()
    assert all(not data.get("inference_verified", False) for data in report["engines"].values())


def test_d0_247_python_memory_estimate_is_null_or_positive():
    value = env.collect_environment()["memory_bytes_estimate"]
    assert value is None or value > 0


def test_d0_248_output_directory_permission_error_is_structured(monkeypatch, tmp_path):
    def fail(*_args, **_kwargs):
        raise PermissionError("blocked")
    monkeypatch.setattr(env.Path, "mkdir", fail)
    report = env.collect_environment(tmp_path / "no-write")
    assert any(c["id"] == "output_disk" and c["status"] == "FAIL" for c in report["checks"])


def test_d0_249_plan_command_is_list_not_shell_string():
    assert isinstance(env.build_install_plan("kokoro")["commands"][-1], list)


def test_d0_250_cli_reports_no_install_side_effect_claim():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/diagnose_tts_environment.py"), "--engine", "kokoro"],
                            capture_output=True, text=True, timeout=20)
    assert json.loads(result.stdout)["install_plan"]["executed"] is False


def test_schema_validates_diagnostic_report():
    import jsonschema
    schema = json.loads((ROOT / "schemas/tts-environment-diagnostic-v1.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(env.collect_environment(), schema)


def test_schema_validates_selected_engine_report():
    import jsonschema
    schema = json.loads((ROOT / "schemas/tts-environment-diagnostic-v1.schema.json").read_text())
    report = env.collect_environment()
    report["selected_engine"] = "kokoro"
    report["install_plan"] = env.build_install_plan("kokoro")
    report["selected_engine_ready"] = not report["engines"]["kokoro"]["missing_distributions"]
    jsonschema.validate(report, schema)
