#!/usr/bin/env python3
"""Report optional TTS package/cache status without loading or downloading models."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tts_engine_adapters import probe_engines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-any-package", action="store_true",
                        help="return exit code 1 if none of the optional engine packages is installed")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    args = parser.parse_args()
    probes = [probe.to_dict() for probe in probe_engines()]
    print(json.dumps({"schema_version": 1, "inference_verified": False, "engines": probes},
                     ensure_ascii=False, sort_keys=True, indent=2 if args.pretty else None))
    if args.require_any_package and not any(item["package_available"] for item in probes):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
