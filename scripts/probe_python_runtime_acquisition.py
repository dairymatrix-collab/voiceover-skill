#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from python_runtime_acquisition import collect_runtime_acquisition_report

p = argparse.ArgumentParser(description="Read-only offline Python runtime acquisition diagnostic")
p.add_argument("--versions", default="3.12,3.11,3.10")
p.add_argument("--timeout", type=float, default=20.0)
p.add_argument("--pretty", action="store_true")
args = p.parse_args()
try:
    report = collect_runtime_acquisition_report(versions=tuple(x.strip() for x in args.versions.split(",") if x.strip()), timeout_seconds=args.timeout)
except ValueError as exc:
    p.error(str(exc))
print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=True))
sys.exit(0 if report["status"] == "OFFLINE_RUNTIME_CANDIDATE" else 3)
