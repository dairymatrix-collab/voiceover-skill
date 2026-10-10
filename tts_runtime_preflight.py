"""Read-only interpreter discovery and install-readiness checks for optional TTS engines.

No packages are installed and no model weights are downloaded by this module.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Iterable

from tts_environment import ENGINE_SPECS
from tts_artifact_readiness import inspect_engine_artifacts_v2, normalize_engine_id

SUPPORTED_PYTHON_MIN = (3, 10)
SUPPORTED_PYTHON_MAX = (3, 12)
PROBE_TIMEOUT_SECONDS = 8.0
NETWORK_TIMEOUT_SECONDS = 4.0
MAX_WHEELHOUSE_FILES = 20_000
_PROBE = r'''import importlib.util,json,platform,sys
mods=('pip','torch','numpy','soundfile','kokoro','chatterbox','qwen_tts','transformers','torchaudio','accelerate')
print(json.dumps({'executable':sys.executable,'version':list(sys.version_info[:3]),'implementation':platform.python_implementation(),'machine':platform.machine(),'bits':platform.architecture()[0],'modules':{m:bool(importlib.util.find_spec(m)) for m in mods}}))'''


def _version_tuple(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, list) or len(value) != 3 or any(isinstance(x, bool) or not isinstance(x, int) for x in value):
        return None
    if any(x < 0 for x in value):
        return None
    return tuple(value)  # type: ignore[return-value]


def _candidate_names() -> list[str]:
    names = ["python3.12", "python3.11", "python3.10", "python3", "python"]
    if os.name == "nt":
        names = ["py -3.12", "py -3.11", "py -3.10", "python3.12", "python3.11", "python3.10", "python"]
    return names


def _common_paths() -> list[str]:
    paths: list[str] = []
    if os.name == "nt":
        roots = [os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")]
        for root in roots:
            if root:
                for minor in (12, 11, 10):
                    paths.append(str(Path(root) / "Programs" / "Python" / f"Python3{minor}" / "python.exe"))
                    paths.append(str(Path(root) / f"Python3{minor}" / "python.exe"))
    else:
        paths.extend([f"/usr/bin/python3.{minor}" for minor in (12, 11, 10)])
        paths.extend([f"/usr/local/bin/python3.{minor}" for minor in (12, 11, 10)])
        paths.extend([f"/opt/homebrew/bin/python3.{minor}" for minor in (12, 11, 10)])
    return paths


def _venv_aware_executable_path(found: str) -> Path:
    """Canonicalize system interpreters but preserve a venv's identity path.

    A venv executable is often a symlink to the base Python. Resolving that
    symlink before probing loses the adjacent ``pyvenv.cfg`` and inspects the
    base interpreter instead of the environment the caller supplied.
    """
    absolute = Path(os.path.abspath(os.path.expanduser(found)))
    resolved = absolute.resolve(strict=True)

    def belongs_to_venv(path: Path) -> bool:
        return any((parent / "pyvenv.cfg").is_file() for parent in (path, *path.parents))

    if belongs_to_venv(absolute):
        return absolute
    if belongs_to_venv(resolved):
        return resolved
    return resolved


def discover_interpreters(extra_candidates: Iterable[str] = (), *, timeout_seconds: float = PROBE_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Probe known Python executables without a shell; return a ranked, JSON-safe report."""
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not (1 <= timeout_seconds <= 30):
        raise ValueError("timeout_seconds must be in [1, 30]")
    supplied = list(extra_candidates)
    if any(not isinstance(x, str) or not x.strip() or "\x00" in x for x in supplied):
        raise ValueError("candidate paths must be non-empty strings without NUL")
    candidates = [*supplied, *[x for x in _candidate_names() if not x.startswith("py -")], *_common_paths(), sys.executable]
    resolved: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        found = shutil.which(candidate) if not (os.path.isabs(candidate) or os.path.sep in candidate) else candidate
        if not found:
            continue
        try:
            executable_path = str(_venv_aware_executable_path(found))
        except (OSError, RuntimeError):
            continue
        key = os.path.normcase(executable_path)
        if key not in seen and Path(executable_path).is_file():
            seen.add(key)
            resolved.append(executable_path)
    records: list[dict[str, Any]] = []
    for executable in resolved:
        record: dict[str, Any] = {"executable": executable, "status": "UNPROBED", "supported_by_project_policy": False}
        try:
            child = subprocess.run([executable, "-I", "-c", _PROBE], shell=False, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=float(timeout_seconds),
                                   check=False, text=True, errors="replace", env={"PATH": os.environ.get("PATH", "")})
            if child.returncode != 0:
                record.update(status="PROBE_FAILED", detail=f"exit={child.returncode}; {child.stderr[-300:]}")
            else:
                try:
                    data = json.loads(child.stdout.strip().splitlines()[-1])
                    version = _version_tuple(data.get("version"))
                    if version is None:
                        raise ValueError("invalid version response")
                    supported = SUPPORTED_PYTHON_MIN <= version[:2] <= SUPPORTED_PYTHON_MAX
                    data["version_text"] = ".".join(map(str, version))
                    data["supported_by_project_policy"] = supported
                    record.update(status="PASS", **data)
                except (ValueError, json.JSONDecodeError, IndexError, TypeError):
                    record.update(status="PROBE_PROTOCOL_ERROR", detail="interpreter did not return valid probe JSON")
        except subprocess.TimeoutExpired:
            record.update(status="PROBE_TIMEOUT", detail=f"probe exceeded {timeout_seconds:g}s")
        except OSError as exc:
            record.update(status="PROBE_LAUNCH_FAILED", detail=type(exc).__name__)
        records.append(record)
    records.sort(key=lambda r: (not bool(r.get("supported_by_project_policy")),
                                tuple(r.get("version", [0, 0, 0])) if isinstance(r.get("version"), list) else (0, 0, 0),
                                str(r.get("executable", ""))), reverse=True)
    selected = next((r for r in records if r.get("status") == "PASS" and r.get("supported_by_project_policy")), None)
    return {"schema_version": 1, "diagnostic_only": True, "installation_performed": False,
            "model_downloaded": False, "inference_verified": False, "candidate_count": len(records),
            "selected_interpreter": selected.get("executable") if selected else None,
            "selected_python_version": selected.get("version_text") if selected else None,
            "supported_policy": {"minimum": "3.10", "maximum": "3.12", "note": "Project policy gate; verify each engine's upstream wheel compatibility."},
            "interpreters": records,
            "status": "READY_FOR_ENGINE_PREFLIGHT" if selected else "NO_SUPPORTED_INTERPRETER"}


def probe_network(urls: Iterable[str] = ("https://pypi.org/simple/", "https://huggingface.co/"), *, timeout_seconds: float = NETWORK_TIMEOUT_SECONDS) -> list[dict[str, Any]]:
    """Bounded HTTPS reachability probes; report only status/error class, not response bodies."""
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not (1 <= timeout_seconds <= 15):
        raise ValueError("timeout_seconds must be in [1, 15]")
    results = []
    for url in urls:
        if not isinstance(url, str) or not (url.startswith("https://pypi.org/") or url.startswith("https://huggingface.co/")):
            raise ValueError("only approved PyPI and Hugging Face HTTPS URLs are allowed")
        req = urllib.request.Request(url, headers={"User-Agent": "voiceover-runtime-preflight/1.0"}, method="GET")
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=float(timeout_seconds)) as response:
                results.append({"url": url, "status": "REACHABLE", "http_status": int(response.status),
                                "elapsed_ms": round((time.monotonic() - started) * 1000)})
        except urllib.error.HTTPError as exc:
            # HTTP response proves name resolution/connectivity even if endpoint returns 4xx/5xx.
            results.append({"url": url, "status": "REACHABLE_HTTP_ERROR", "http_status": int(exc.code),
                            "elapsed_ms": round((time.monotonic() - started) * 1000)})
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            results.append({"url": url, "status": "UNREACHABLE", "error_type": type(reason).__name__,
                            "elapsed_ms": round((time.monotonic() - started) * 1000)})
    return results


def audit_wheelhouse(path: str | Path, *, max_files: int = MAX_WHEELHOUSE_FILES) -> dict[str, Any]:
    """Inventory a local wheelhouse without installing files or importing their code."""
    root = Path(path).expanduser().resolve()
    if isinstance(max_files, bool) or not isinstance(max_files, int) or not (1 <= max_files <= 100_000):
        raise ValueError("max_files must be in [1, 100000]")
    if not root.is_dir():
        return {"path": str(root), "status": "WHEELHOUSE_NOT_FOUND", "wheel_count": 0, "packages": [], "truncated": False}
    wheels: list[str] = []
    truncated = False
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(current) / d).is_symlink()]
        for name in files:
            candidate = Path(current) / name
            if candidate.is_symlink():
                continue
            if name.lower().endswith(".whl"):
                wheels.append(str(candidate.relative_to(root)))
                if len(wheels) >= max_files:
                    truncated = True
                    break
        if truncated:
            break
    # Parse package name from wheel filename without importing wheel contents.
    packages: dict[str, list[str]] = {}
    for relative in sorted(wheels):
        parts = Path(relative).name.split("-")
        if len(parts) < 5:
            continue
        dist = parts[0].replace("_", "-").lower()
        packages.setdefault(dist, []).append(relative)
    return {"path": str(root), "status": "PASS" if wheels else "EMPTY_WHEELHOUSE", "wheel_count": len(wheels),
            "package_count": len(packages), "packages": [{"normalized_name": key, "wheels": values} for key, values in sorted(packages.items())],
            "truncated": truncated, "max_files": max_files,
            "warning": "Inventory only: wheel tags, transitive dependency closure, signatures, and wheel trust are not validated."}


def collect_preflight(engine: str, *, output_dir: str | Path | None = None, wheelhouse: str | Path | None = None,
                      check_network: bool = True, extra_candidates: Iterable[str] = (),
                      include_artifacts: bool = False, model_root: str | Path | None = None,
                      hash_artifacts: bool = False,
                      model_variant: str | None = None) -> dict[str, Any]:
    engine = normalize_engine_id(engine)
    if not isinstance(include_artifacts, bool) or not isinstance(hash_artifacts, bool):
        raise ValueError("artifact preflight options must be boolean")
    if model_variant is not None and not include_artifacts:
        raise ValueError("model_variant requires include_artifacts=True")
    interpreters = discover_interpreters(extra_candidates)
    selected = next((r for r in interpreters["interpreters"] if r.get("executable") == interpreters["selected_interpreter"]), None)
    required = ENGINE_SPECS[engine]["required_distributions"]
    missing: list[str] = []
    if selected:
        modules = selected.get("modules", {})
        missing = [name for name in required if not modules.get({"qwen-tts": "qwen_tts", "chatterbox-tts": "chatterbox"}.get(name, name.replace("-", "_")), False)]
    wheel_report = audit_wheelhouse(wheelhouse) if wheelhouse is not None else None
    network = probe_network() if check_network else []
    network_ready = bool(network) and all(item["status"].startswith("REACHABLE") for item in network) if check_network else None
    if not selected:
        status = "NO_SUPPORTED_INTERPRETER"
    elif check_network and not network_ready and wheel_report and wheel_report.get("wheel_count", 0):
        status = "WHEELHOUSE_PRESENT_UNVERIFIED"
    elif check_network and not network_ready:
        status = "NETWORK_UNAVAILABLE"
    elif missing:
        status = "ENGINE_DEPENDENCIES_MISSING"
    else:
        status = "ENGINE_PREREQUISITES_PRESENT"
    report = {"schema_version": 1, "engine": engine, "status": status, "diagnostic_only": True,
              "installation_performed": False, "model_downloaded": False, "inference_verified": False,
              "interpreter_report": interpreters, "selected_engine_interpreter": interpreters["selected_interpreter"],
              "required_distributions": list(required), "missing_engine_modules": missing,
              "network": network, "network_ready": network_ready, "wheelhouse": wheel_report,
              "notes": ["This preflight never installs packages or downloads model weights.",
                        "Interpreter policy is conservative; check upstream engine compatibility before installation.",
                        "Module presence does not prove that model weights load or audio synthesis works."]}
    if include_artifacts:
        # Version 2 is opt-in so closed version-1 consumers keep their exact contract.
        # Artifact presence is a separate readiness signal and does not alter the
        # interpreter/package status or prove model loading/inference.
        report["schema_version"] = 2
        report["artifact_readiness"] = inspect_engine_artifacts_v2(
            engine, model_root=model_root, hash_files=hash_artifacts,
            model_variant=model_variant,
        )
    return report
