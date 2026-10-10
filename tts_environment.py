"""Read-only diagnostics and conservative setup guidance for optional TTS engines.

This module never installs packages, downloads models, or loads neural weights.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import importlib.metadata
import importlib.util
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any
from cache_paths import hf_home_path, hf_hub_cache_path

ENGINE_SPECS: dict[str, dict[str, Any]] = {
    "kokoro": {
        "distribution": "kokoro", "module": "kokoro",
        "required_distributions": ("kokoro", "torch", "numpy", "soundfile"),
        "required_modules": ("kokoro", "torch", "numpy", "soundfile"),
        "recommended_python": "3.10–3.12 (verify upstream wheels before choosing 3.13+)",
        "install_packages": ("kokoro==0.9.4", "torch", "numpy", "soundfile"),
        "install_command": ["python", "-m", "pip", "install", "kokoro==0.9.4", "torch", "numpy", "soundfile"],
        "notes": ["May need espeak-ng or another supported eSpeak executable for phonemization.",
                  "Model files may be downloaded at first pipeline load."],
    },
    "chatterbox": {
        "distribution": "chatterbox-tts", "module": "chatterbox",
        "required_distributions": ("chatterbox-tts", "torch", "torchaudio", "numpy", "soundfile", "transformers", "librosa", "safetensors"),
        "required_modules": ("chatterbox", "torch", "torchaudio", "numpy", "soundfile", "transformers", "librosa", "safetensors"),
        "recommended_python": "Use the Python version supported by the upstream release; verify before install.",
        "install_packages": ("chatterbox-tts==0.1.7", "torch", "torchaudio", "numpy<2.0.0", "soundfile",
                             "librosa==0.11.0", "s3tokenizer", "transformers==5.2.0", "diffusers==0.29.0",
                             "resemble-perth>=1.0.0", "conformer==0.3.2", "safetensors==0.5.3",
                             "spacy-pkuseg", "pykakasi==2.3.0", "gradio==6.8.0", "pyloudnorm", "omegaconf"),
        "install_command": ["python", "-m", "pip", "install", "chatterbox-tts==0.1.7", "torch", "torchaudio",
                            "numpy<2.0.0", "soundfile", "librosa==0.11.0", "s3tokenizer", "transformers==5.2.0",
                            "diffusers==0.29.0", "resemble-perth>=1.0.0", "conformer==0.3.2", "safetensors==0.5.3",
                            "spacy-pkuseg", "pykakasi==2.3.0", "gradio==6.8.0", "pyloudnorm", "omegaconf"],
        "notes": ["Large model/runtime dependencies; a dedicated virtual environment is recommended.",
                  "Multilingual and English model paths differ."],
    },
    "qwen3_tts": {
        "distribution": "qwen-tts", "module": "qwen_tts",
        "required_distributions": ("qwen-tts", "torch", "torchaudio", "transformers", "accelerate", "soundfile", "librosa", "onnxruntime"),
        "required_modules": ("qwen_tts", "torch", "torchaudio", "transformers", "accelerate", "soundfile", "librosa", "onnxruntime", "einops"),
        "recommended_python": "Use the Python version supported by the upstream release; verify before install.",
        "install_packages": ("qwen-tts==0.1.1", "torch", "torchaudio", "transformers==4.57.3", "accelerate==1.12.0",
                             "gradio", "librosa", "soundfile", "sox", "onnxruntime", "einops"),
        "install_command": ["python", "-m", "pip", "install", "qwen-tts==0.1.1", "torch", "torchaudio",
                            "transformers==4.57.3", "accelerate==1.12.0", "gradio", "librosa", "soundfile",
                            "sox", "onnxruntime", "einops"],
        "notes": ["Model checkpoints can be multiple gigabytes.",
                  "A model ID must be selected and real inference separately verified."],
    },
}

@dataclass(frozen=True)
class Diagnostic:
    id: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _safe_module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def _memory_bytes() -> int | None:
    # Linux/macOS POSIX estimate; no third-party psutil requirement.
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            return int(pages * page_size)
    except (AttributeError, OSError, ValueError):
        pass
    return None


def _model_cache() -> dict[str, Any]:
    home = hf_home_path()
    hub = hf_hub_cache_path()
    qwen = hub / "models--Qwen--Qwen3-TTS-12Hz-1.7B-CustomVoice"
    # Size is intentionally bounded to avoid walking an untrusted, enormous cache.
    total = 0
    files_seen = 0
    truncated = False
    if hub.is_dir():
        try:
            for root, dirs, files in os.walk(hub):
                dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
                for name in files:
                    p = Path(root) / name
                    if p.is_symlink():
                        continue
                    try:
                        total += p.stat().st_size
                    except OSError:
                        continue
                    files_seen += 1
                    if files_seen >= 100_000:
                        truncated = True
                        raise StopIteration
        except StopIteration:
            pass
        except OSError:
            pass
    return {"hf_home": str(home), "hub_exists": hub.is_dir(),
            "qwen_default_model_directory_exists": qwen.is_dir(),
            "hub_bytes_scanned": total, "files_scanned": files_seen,
            "scan_truncated": truncated}


def collect_environment(output_dir: str | Path | None = None) -> dict[str, Any]:
    """Collect reproducible local facts without installing or loading models."""
    checks: list[Diagnostic] = []
    version = sys.version_info
    checks.append(Diagnostic("python_version", "PASS" if (3, 10) <= (version.major, version.minor) <= (3, 12)
                             else "CAUTION", f"Python {platform.python_version()}; upstream engine wheel compatibility must be checked"))
    pip_version = _distribution_version("pip")
    checks.append(Diagnostic("pip", "PASS" if pip_version else "INFO", pip_version or "pip distribution metadata unavailable"))
    checks.append(Diagnostic("numpy", "PASS" if _safe_module_available("numpy") else "MISSING",
                             _distribution_version("numpy") or "numpy not detected"))
    checks.append(Diagnostic("soundfile", "PASS" if _safe_module_available("soundfile") else "MISSING",
                             _distribution_version("soundfile") or "soundfile not detected"))

    torch_data: dict[str, Any] = {"available": False, "version": None, "cuda_available": False,
                                  "cuda_version": None, "mps_available": False, "device": "unknown"}
    if _safe_module_available("torch"):
        try:
            import torch
            cuda = bool(torch.cuda.is_available())
            mps_backend = getattr(getattr(torch, "backends", None), "mps", None)
            mps = bool(mps_backend and mps_backend.is_available())
            torch_data = {"available": True, "version": str(torch.__version__), "cuda_available": cuda,
                          "cuda_version": getattr(torch.version, "cuda", None), "mps_available": mps,
                          "device": "cuda" if cuda else "mps" if mps else "cpu"}
            checks.append(Diagnostic("torch", "PASS", f"PyTorch {torch.__version__}; device={torch_data['device']}"))
        except Exception as exc:  # diagnostic only; don't let a broken optional import crash report
            checks.append(Diagnostic("torch", "BROKEN", f"PyTorch import/device probe failed: {type(exc).__name__}"))
    else:
        checks.append(Diagnostic("torch", "MISSING", "PyTorch module not detected"))

    binaries = {name: shutil.which(name) for name in ("ffmpeg", "espeak-ng", "espeak")}
    checks.append(Diagnostic("phonemizer", "PASS" if binaries["espeak-ng"] or binaries["espeak"] else "CAUTION",
                             "eSpeak executable detected" if binaries["espeak-ng"] or binaries["espeak"]
                             else "neither espeak-ng nor espeak found; Kokoro phonemization may fail"))
    disk = None
    if output_dir is not None:
        target = Path(output_dir).expanduser()
        try:
            target.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(target)
            disk = {"path": str(target.resolve()), "free_bytes": usage.free, "total_bytes": usage.total}
            checks.append(Diagnostic("output_disk", "PASS" if usage.free > 0 else "FAIL",
                                     f"{usage.free} bytes free at output location"))
        except OSError as exc:
            checks.append(Diagnostic("output_disk", "FAIL", f"Cannot inspect/create output path: {type(exc).__name__}"))
    else:
        disk = {"path": None, "free_bytes": None, "total_bytes": None}

    packages = {}
    for engine, spec in ENGINE_SPECS.items():
        required = {}
        for dist in spec["required_distributions"]:
            required[dist] = _distribution_version(dist)
        packages[engine] = {
            "module_available": _safe_module_available(spec["module"]),
            "inference_verified": False,
            "distribution": spec["distribution"],
            "distribution_version": _distribution_version(spec["distribution"]),
            "required_distributions": required,
            "missing_distributions": [name for name, found in required.items() if found is None],
            "recommended_python": spec["recommended_python"],
            "install_command": list(spec["install_command"]),
            "notes": list(spec["notes"]),
        }
    return {
        "schema_version": 1,
        "diagnostic_only": True,
        "inference_verified": False,
        "python": {"version": platform.python_version(), "implementation": platform.python_implementation(),
                   "executable": sys.executable, "platform": platform.platform(), "architecture": platform.machine()},
        "memory_bytes_estimate": _memory_bytes(),
        "torch": torch_data,
        "binaries": binaries,
        "disk": disk,
        "model_cache": _model_cache(),
        "checks": [c.to_dict() for c in checks],
        "engines": packages,
    }


def build_install_plan(engine: str, *, python_executable: str = "python") -> dict[str, Any]:
    """Return commands only. No subprocess or installation is executed."""
    if engine not in ENGINE_SPECS:
        raise ValueError(f"unknown engine: {engine}")
    spec = ENGINE_SPECS[engine]
    command = [python_executable, "-m", "pip", "install", *spec["install_packages"]]
    return {"schema_version": 1, "engine": engine, "executed": False,
            "warning": "Review upstream Python/platform requirements first. This plan does not pin versions and installs nothing.",
            "commands": [[python_executable, "-m", "venv", ".venv"],
                         [".venv/bin/python", "-m", "pip", "install", "--upgrade", "pip"],
                         command],
            "windows_activation_note": ".venv\\Scripts\\python.exe may be used instead of .venv/bin/python on Windows.",
            "upstream_notes": list(spec["notes"])}
