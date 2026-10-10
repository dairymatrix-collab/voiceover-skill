#!/usr/bin/env python3
"""Inspect local TTS model artifacts without installation or downloads."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tts_artifact_readiness import (
    inspect_all,
    inspect_all_v2,
    inspect_engine_artifacts,
    inspect_engine_artifacts_v2,
    resolve_model_root,
    write_report_atomic,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect local TTS model artifacts without installing or downloading anything."
    )
    parser.add_argument("--engine", help="canonical engine ID or a documented alias; omit to inspect all")
    parser.add_argument("--model-root")
    parser.add_argument("--hash-files", action="store_true",
                        help="hash file artifacts and v2 matched required files, subject to the byte limit")
    parser.add_argument("--schema-version", type=int, choices=(1, 2), default=1,
                        help="report contract version (v1 remains the compatibility default)")
    parser.add_argument("--model-variant",
                        help="artifact variant for a single engine (v2 only; e.g. qwen3_tts voice_design)")
    parser.add_argument("--report", type=Path, help="atomically write the same JSON report to this path")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    try:
        if args.model_variant is not None and (args.schema_version != 2 or args.engine is None):
            parser.error("--model-variant requires --schema-version 2 and --engine")
        if args.schema_version == 1:
            data = (inspect_engine_artifacts(args.engine, model_root=args.model_root, hash_files=args.hash_files)
                    if args.engine else inspect_all(args.model_root, hash_files=args.hash_files))
        else:
            data = (inspect_engine_artifacts_v2(args.engine, model_root=args.model_root,
                                                hash_files=args.hash_files,
                                                model_variant=args.model_variant)
                    if args.engine else inspect_all_v2(args.model_root, hash_files=args.hash_files))
        if args.report:
            root = resolve_model_root(args.model_root)
            write_report_atomic(args.report, data, protected_root=root)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2 if args.pretty else None, allow_nan=False))
    ready = data["artifact_ready"] if args.engine else data["ready_engine_count"] > 0
    return 0 if ready else 3


if __name__ == "__main__":
    raise SystemExit(main())
