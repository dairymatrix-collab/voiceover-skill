#!/usr/bin/env python3
"""Validate an audit report and emit a stable, machine-readable consumer result.

Input is a JSON file path or '-' (stdin). Exit codes: 0=PASS, 1=verified FAIL,
2=invalid/unconsumable report or CLI/I/O error. A valid FAIL report is not a
consumer error; its diagnostic groups are emitted as JSON and the process exits 1.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from audit_report_consumer import (  # noqa: E402
    DEFAULT_SCHEMA_PATH,
    MAX_REPORT_BYTES,
    AuditReportContractError,
    consume_audit_report_json,
)


def _read_bounded(path: Path | None) -> bytes:
    """Read at most one byte beyond the consumer's cap, never unbounded input."""
    stream = sys.stdin.buffer if path is None else path.open("rb")
    try:
        raw = stream.read(MAX_REPORT_BYTES + 1)
    finally:
        if path is not None:
            stream.close()
    if len(raw) > MAX_REPORT_BYTES:
        # Let the shared parser classify the exact same size boundary.
        return raw
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", nargs="?", default="-", help="JSON report file, or '-' for stdin (default)")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA_PATH, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    path = None if args.report == "-" else Path(args.report)
    try:
        raw = _read_bounded(path)
        result = consume_audit_report_json(raw, args.schema)
    except AuditReportContractError as exc:
        print(f"ERROR: {exc.code}", file=sys.stderr)
        return 2
    except OSError as exc:
        # Do not leak local paths or OS exception details into automation logs.
        print(f"ERROR: AUDIT_REPORT_INPUT_IO ({type(exc).__name__})", file=sys.stderr)
        return 2
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
