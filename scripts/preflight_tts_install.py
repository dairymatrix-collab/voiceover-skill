#!/usr/bin/env python3
"""Read-only Python/engine/network/wheelhouse preflight; never installs packages."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tts_artifact_readiness import resolve_model_root, write_report_atomic
from tts_runtime_preflight import collect_preflight


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True,
                        help="canonical engine ID or a documented alias (kokoro, chatterbox, qwen3_tts, etc.)")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--skip-network", action="store_true", help="skip bounded PyPI/Hugging Face HTTPS probes")
    parser.add_argument("--python-candidate", action="append", default=[], help="additional Python executable to probe; repeatable")
    parser.add_argument("--include-artifacts", action="store_true",
                        help="include version-2, local-only model-artifact readiness (does not load models)")
    parser.add_argument("--model-root", type=Path,
                        help="artifact root; default: VOICEOVER_MODEL_ROOT/TTS_MODEL_ROOT, then effective Hugging Face Hub cache")
    parser.add_argument("--model-variant",
                        help="single-engine artifact variant (requires --include-artifacts; e.g. voice_design)")
    parser.add_argument("--hash-artifacts", action="store_true", help="hash complete small file artifacts, subject to the byte limit")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    try:
        report = collect_preflight(
            args.engine, output_dir=args.output_dir, wheelhouse=args.wheelhouse,
            check_network=not args.skip_network, extra_candidates=args.python_candidate,
            include_artifacts=args.include_artifacts, model_root=args.model_root,
            hash_artifacts=args.hash_artifacts,
            model_variant=args.model_variant,
        )
        if args.report:
            protected_root = resolve_model_root(args.model_root) if args.include_artifacts else None
            write_report_atomic(args.report, report, protected_root=protected_root)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    text = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2 if args.pretty else None,
                      allow_nan=False) + "\n"
    sys.stdout.write(text)
    if report["status"] == "ENGINE_PREREQUISITES_PRESENT":
        if args.include_artifacts and not report["artifact_readiness"]["artifact_ready"]:
            return 4
        return 0
    return 3 if report["status"] in {"NO_SUPPORTED_INTERPRETER", "NETWORK_UNAVAILABLE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
