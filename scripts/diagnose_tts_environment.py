#!/usr/bin/env python3
"""Read-only TTS environment diagnostics; does not install packages or load models."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tts_environment import collect_environment, build_install_plan, ENGINE_SPECS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=None, help="optional path whose disk space should be checked")
    parser.add_argument("--engine", choices=sorted(ENGINE_SPECS), help="include a non-executing install plan for this engine")
    parser.add_argument("--write-json", type=Path, help="write report atomically to this path")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--strict-engine-ready", action="store_true", help="exit 2 if selected engine's required distributions are missing")
    args = parser.parse_args()
    report = collect_environment(args.output_dir)
    if args.engine:
        report["selected_engine"] = args.engine
        report["install_plan"] = build_install_plan(args.engine)
        report["selected_engine_ready"] = not report["engines"][args.engine]["missing_distributions"]
    payload = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2 if args.pretty else None, allow_nan=False) + "\n"
    if args.write_json:
        target = args.write_json.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, target)
        finally:
            if temp.exists():
                temp.unlink()
    print(payload, end="")
    if args.strict_engine_ready and args.engine and not report["selected_engine_ready"]:
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
