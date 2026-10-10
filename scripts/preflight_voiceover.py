#!/usr/bin/env python3
"""Check local TTS readiness without downloading or loading model weights."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from voiceover_preflight import run_preflight


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("voiceover-output"))
    parser.add_argument("--engine", choices=("qwen3_tts", "chatterbox", "kokoro"))
    parser.add_argument("--require-gpu", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    report = run_preflight(args.output_dir, requested_engine=args.engine, require_gpu=args.require_gpu)
    print(json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True,
                     indent=2 if args.pretty else None))
    return 0 if report.overall_status in {"PASS", "READY_TO_ATTEMPT"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
