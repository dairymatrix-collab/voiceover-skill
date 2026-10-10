#!/usr/bin/env python3
"""Read-only RAM/disk/CPU resource gate; does not install packages or load models."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resource_guard import ENGINE_POLICIES, resource_preflight


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, choices=tuple(sorted(ENGINE_POLICIES)))
    parser.add_argument("--model-root", type=Path, help="optional model-cache directory to use for disk-space checks")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = resource_preflight(args.engine, model_root=args.model_root)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2 if args.pretty else None))
    return 0 if report["status"] == "READY_TO_ATTEMPT" else 3


if __name__ == "__main__":
    raise SystemExit(main())
