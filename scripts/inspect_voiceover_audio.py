#!/usr/bin/env python3
"""Inspect PCM WAV properties and emit a machine-readable quality report."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from audio_quality import AudioQualityError, inspect_wav


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--max-bytes", type=int, default=200_000_000)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    try:
        with args.audio.open("rb") as stream:
            payload = stream.read(args.max_bytes + 1)
        report = inspect_wav(payload, max_bytes=args.max_bytes).to_dict()
        report["path"] = args.audio.name
    except OSError:
        print(json.dumps({"ok": False, "error": "AUDIO_FILE_UNREADABLE"}, sort_keys=True))
        return 2
    except AudioQualityError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, "report": report}, ensure_ascii=False,
                     sort_keys=True, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
