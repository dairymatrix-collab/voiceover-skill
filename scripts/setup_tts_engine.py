#!/usr/bin/env python3
"""Plan or explicitly install one optional TTS engine into a new isolated venv."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from engine_setup import ENGINE_INSTALL_PACKAGES, ENGINE_PACKAGES, SetupError, setup_engine, write_report


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--engine", choices=("kokoro", "qwen3_tts"), required=True)
    p.add_argument("--environment", type=Path, required=True, help="new/empty dedicated venv directory")
    p.add_argument("--python", default=sys.executable, help="base Python executable; project policy currently accepts 3.10–3.12")
    p.add_argument("--install", action="store_true", help="actually create venv and install all declared engine runtime packages; otherwise plan only")
    p.add_argument("--timeout-seconds", type=float, default=1800)
    p.add_argument("--wheelhouse", type=Path, help="local wheel directory for offline installation")
    p.add_argument("--no-index", action="store_true", help="do not query package indexes; requires --wheelhouse")
    p.add_argument("--cpu-only", action="store_true", help="install and verify CPU-only PyTorch 2.6 wheels; no CUDA runtime")
    p.add_argument("--report", type=Path)
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()
    try:
        report = setup_engine(args.engine, args.environment, python_executable=args.python,
                              install=args.install, timeout_seconds=args.timeout_seconds,
                              wheelhouse=args.wheelhouse, no_index=args.no_index, cpu_only=args.cpu_only)
    except SetupError as exc:
        report = {"schema_version": 1, "engine": args.engine, "environment": str(args.environment.expanduser().absolute()),
                  "install_requested": args.install, "executed": False, "model_downloaded": False,
                  "inference_verified": False, "package": ENGINE_PACKAGES[args.engine],
                  "packages_to_install": list(ENGINE_INSTALL_PACKAGES[args.engine]), "cpu_only": args.cpu_only,
                  "python_executable": args.python, "wheelhouse": str(args.wheelhouse.expanduser().resolve()) if args.wheelhouse else None,
                  "no_index": args.no_index, "steps": [], "status": "BLOCKED",
                  "error": exc.code, "detail": exc.detail}
    if args.report:
        write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2 if args.pretty else None, allow_nan=False))
    status = report.get("status")
    return 0 if status == "PLAN_ONLY" or status == "PACKAGE_READY" else (3 if status == "BLOCKED" else 2)

if __name__ == "__main__":
    raise SystemExit(main())
