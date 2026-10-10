"""Explicit, isolated optional TTS engine setup. Never run unless the caller opts in."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import venv
from typing import Any, Sequence

from tts_environment import ENGINE_SPECS

ENGINE_PACKAGES = {key: spec["distribution"] for key, spec in ENGINE_SPECS.items()}
ENGINE_INSTALL_PACKAGES = {key: tuple(spec["install_packages"]) for key, spec in ENGINE_SPECS.items()}
ENGINE_REQUIRED_MODULES = {key: tuple(spec["required_modules"]) for key, spec in ENGINE_SPECS.items()}
PYTORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"
PYPI_INDEX = "https://pypi.org/simple"
CPU_TORCH_PACKAGES = ("torch==2.6.0+cpu", "torchaudio==2.6.0+cpu")
_TORCH_DISTRIBUTIONS = {"torch", "torchaudio"}
MAX_LOG_BYTES = 128_000
DEFAULT_TIMEOUT_SECONDS = 1800


class SetupError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _safe_engine(engine: str) -> str:
    if not isinstance(engine, str) or engine not in ENGINE_PACKAGES:
        raise SetupError("UNKNOWN_ENGINE")
    return engine


def _safe_timeout(timeout: float) -> float:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 1 or timeout > 7200:
        raise SetupError("INVALID_TIMEOUT")
    return float(timeout)


def _venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _distribution_name(requirement: str) -> str:
    return re.split(r"[<>=!~\[]", requirement, maxsplit=1)[0].strip().lower().replace("_", "-")


def _cpu_package_list(engine: str) -> tuple[str, ...]:
    remaining = tuple(pkg for pkg in ENGINE_INSTALL_PACKAGES[engine]
                      if _distribution_name(pkg) not in _TORCH_DISTRIBUTIONS)
    return (*CPU_TORCH_PACKAGES, *remaining)


def _cpu_torch_command(python: str, wheelhouse: Path | None, no_index: bool) -> list[str]:
    command = [python, "-m", "pip", "install"]
    if no_index:
        assert wheelhouse is not None
        command.extend(["--find-links", str(wheelhouse), "--no-index"])
    else:
        command.extend(["--index-url", PYTORCH_CPU_INDEX, "--extra-index-url", PYPI_INDEX])
    command.extend(CPU_TORCH_PACKAGES)
    return command


def _validate_root(path: str | Path) -> Path:
    try:
        root = Path(path).expanduser().absolute()
    except (TypeError, ValueError, OSError) as exc:
        raise SetupError("INVALID_ENVIRONMENT_PATH") from exc
    if root.is_symlink():
        raise SetupError("SYMLINK_ENVIRONMENT_PATH")
    root = root.resolve(strict=False)
    if str(root) in {"", ".", os.path.abspath(os.sep)} or root == Path.home().resolve():
        raise SetupError("UNSAFE_ENVIRONMENT_PATH")
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise SetupError("ENVIRONMENT_PATH_NOT_EMPTY")
    return root


def _run(argv: Sequence[str], *, timeout: float, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Run trusted setup argv without shell; bound and sanitize captured logs."""
    try:
        result = subprocess.run(list(argv), shell=False, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=timeout, check=False, env=env, text=True,
                                errors="replace")
    except subprocess.TimeoutExpired as exc:
        raise SetupError("COMMAND_TIMEOUT", Path(argv[0]).name) from exc
    except OSError as exc:
        raise SetupError("COMMAND_LAUNCH_FAILED", type(exc).__name__) from exc
    stdout = result.stdout[-MAX_LOG_BYTES:] if result.stdout else ""
    stderr = result.stderr[-MAX_LOG_BYTES:] if result.stderr else ""
    # Never include credential-like values in returned logs.
    redactor = re.compile(r"(?i)(token|password|secret|api[_-]?key)(\s*[=:]\s*)[^\s,;]+")
    stdout, stderr = redactor.sub(r"\1\2[REDACTED]", stdout), redactor.sub(r"\1\2[REDACTED]", stderr)
    return {"returncode": result.returncode, "stdout_tail": stdout, "stderr_tail": stderr}


def setup_engine(engine: str, environment: str | Path, *, python_executable: str = sys.executable,
                 install: bool = False, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
                 wheelhouse: str | Path | None = None, no_index: bool = False,
                 cpu_only: bool = False) -> dict[str, Any]:
    """Plan setup by default. With install=True, create a new venv and install all declared runtime packages.

    This deliberately does not download model weights or run synthesis. For offline setup,
    provide --wheelhouse and --no-index; pip will be constrained to that local wheelhouse.
    """
    engine = _safe_engine(engine)
    timeout = _safe_timeout(timeout_seconds)
    if not isinstance(install, bool) or not isinstance(no_index, bool) or not isinstance(cpu_only, bool):
        raise SetupError("INVALID_BOOLEAN_OPTION")
    root = _validate_root(environment)
    wheel_path: Path | None = None
    if wheelhouse is not None:
        wheel_path = Path(wheelhouse).expanduser().resolve()
        if not wheel_path.is_dir():
            raise SetupError("WHEELHOUSE_NOT_FOUND")
    if no_index and wheel_path is None:
        raise SetupError("NO_INDEX_REQUIRES_WHEELHOUSE")
    packages = _cpu_package_list(engine) if cpu_only else ENGINE_INSTALL_PACKAGES[engine]
    base = {"schema_version": 1, "engine": engine, "environment": str(root),
            "install_requested": install, "executed": False, "model_downloaded": False,
            "inference_verified": False, "package": ENGINE_PACKAGES[engine],
            "packages_to_install": list(packages), "cpu_only": cpu_only,
            "python_executable": str(python_executable), "wheelhouse": str(wheel_path) if wheel_path else None,
            "no_index": no_index, "steps": []}
    if not install:
        base["status"] = "PLAN_ONLY"
        if cpu_only:
            cpu_command = _cpu_torch_command(str(_venv_python(root)), wheel_path, no_index)
            engine_packages = tuple(pkg for pkg in packages if _distribution_name(pkg) not in _TORCH_DISTRIBUTIONS)
            engine_command = [str(_venv_python(root)), "-m", "pip", "install", *engine_packages]
            if wheel_path is not None:
                engine_command.extend(["--find-links", str(wheel_path)])
            if no_index:
                engine_command.append("--no-index")
            base["commands"] = [[python_executable, "-m", "venv", str(root)], cpu_command, engine_command]
        else:
            install_command = [str(_venv_python(root)), "-m", "pip", "install", *packages]
            if wheel_path is not None:
                install_command.extend(["--find-links", str(wheel_path)])
            if no_index:
                install_command.append("--no-index")
            base["commands"] = [[python_executable, "-m", "venv", str(root)], install_command]
        base["notes"] = ["No commands were executed.", "Review upstream platform/Python/wheel compatibility first.",
                         "Model weights are not downloaded by setup; profile-backed inference is local-only.",
                         *( ["CPU-only mode pins PyTorch and torchaudio to 2.6.0+cpu from the official CPU wheel index."] if cpu_only else [])]
        return base
    if not isinstance(python_executable, str) or not python_executable.strip() or "\x00" in python_executable:
        raise SetupError("INVALID_PYTHON_EXECUTABLE")
    # Probe selected interpreter before creating files.
    probe = _run([python_executable, "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"], timeout=min(timeout, 30))
    if probe["returncode"] != 0:
        raise SetupError("PYTHON_PROBE_FAILED", probe["stderr_tail"][-500:])
    pyver = tuple(int(part) for part in probe["stdout_tail"].strip().splitlines()[-1].split(".") if part.isdigit())
    if len(pyver) != 3 or not ((3, 10, 0) <= pyver <= (3, 12, 99)):
        raise SetupError("PYTHON_VERSION_UNSUPPORTED_BY_PROJECT_POLICY", probe["stdout_tail"].strip()[-80:])
    base["python_version"] = ".".join(map(str, pyver))
    root.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    try:
        venv.EnvBuilder(with_pip=True, clear=False, symlinks=(os.name != "nt")).create(root)
        base["steps"].append({"id": "create_venv", "status": "PASS"})
        py = str(_venv_python(root))
        # Use a sanitized environment and avoid leaking unrelated API credentials into pip.
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(Path.home()),
               "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1",
               "PIP_NO_CACHE_DIR": "1", "PYTHONNOUSERSITE": "1", "VIRTUAL_ENV": str(root)}
        if os.name == "nt" and os.environ.get("SYSTEMROOT"):
            env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
        engine_packages = tuple(pkg for pkg in packages if _distribution_name(pkg) not in _TORCH_DISTRIBUTIONS) if cpu_only else packages
        if cpu_only:
            torch_result = _run(_cpu_torch_command(py, wheel_path, no_index),
                                timeout=max(1, timeout - (time.monotonic() - start)), env=env)
            base["steps"].append({"id": "install_cpu_torch", "status": "PASS" if torch_result["returncode"] == 0 else "FAIL",
                                  **torch_result})
            if torch_result["returncode"] != 0:
                base["status"] = "INSTALL_FAILED"; base["executed"] = True
                return base
        pip_cmd = [py, "-m", "pip", "install", *engine_packages]
        if wheel_path is not None:
            pip_cmd.extend(["--find-links", str(wheel_path)])
        if no_index:
            pip_cmd.append("--no-index")
        install_result = _run(pip_cmd, timeout=max(1, timeout - (time.monotonic() - start)), env=env)
        base["steps"].append({"id": "install_engine", "status": "PASS" if install_result["returncode"] == 0 else "FAIL",
                              **install_result})
        if install_result["returncode"] != 0:
            base["status"] = "INSTALL_FAILED"
            base["executed"] = True
            return base
        check = _run([py, "-m", "pip", "check"], timeout=min(120, max(1, timeout - (time.monotonic() - start))), env=env)
        base["steps"].append({"id": "pip_check", "status": "PASS" if check["returncode"] == 0 else "FAIL", **check})
        if check["returncode"] != 0:
            base["status"] = "DEPENDENCY_CONFLICT"
            base["executed"] = True
            return base
        if cpu_only:
            cpu_probe = _run([py, "-c", "import torch; assert torch.version.cuda is None; assert not torch.cuda.is_available(); print('cpu_only=true; torch=' + str(torch.__version__))"],
                             timeout=min(30, max(1, timeout - (time.monotonic() - start))), env=env)
            base["steps"].append({"id": "cpu_only_probe", "status": "PASS" if cpu_probe["returncode"] == 0 else "FAIL",
                                  **cpu_probe})
            if cpu_probe["returncode"] != 0:
                base["executed"] = True; base["status"] = "CPU_ONLY_VERIFICATION_FAILED"
                return base
        modules = ENGINE_REQUIRED_MODULES[engine]
        probe_code = ("import importlib.util,sys; modules=" + repr(modules) + "; "
                      "missing=[name for name in modules if importlib.util.find_spec(name) is None]; "
                      "print('missing_modules=' + ','.join(missing)); raise SystemExit(bool(missing))")
        import_check = _run([py, "-c", probe_code],
                            timeout=min(30, max(1, timeout - (time.monotonic() - start))), env=env)
        base["steps"].append({"id": "module_probe", "status": "PASS" if import_check["returncode"] == 0 else "FAIL",
                              **import_check})
        base["executed"] = True
        base["status"] = "PACKAGE_READY" if import_check["returncode"] == 0 else "PACKAGE_IMPORT_MISSING"
        base["venv_python"] = str(_venv_python(root))
        base["notes"] = ["Package readiness is not proof of model weights availability or successful audio inference.",
                         "Run the real inference smoke test in this virtual environment to verify generated audio."]
        return base
    except (SetupError, OSError, ValueError) as exc:
        base["executed"] = bool(root.exists())
        base["status"] = exc.code if isinstance(exc, SetupError) else "SETUP_FAILED"
        base["error_type"] = type(exc).__name__
        # Preserve the failed environment for inspection; never recursively delete user files.
        return base


def write_report(path: str | Path, report: dict[str, Any]) -> None:
    target = Path(path).expanduser().absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, target)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass
