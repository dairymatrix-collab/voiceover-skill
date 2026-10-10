"""Bounded reference consumer for the versioned evidence-bundle audit report.

Consumers must validate the report schema version before interpreting fields and
branch on stable diagnostic ``code`` values, never on human-readable prose.
"""
from __future__ import annotations

import json
from enum import Enum
from itertools import islice
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

REPORT_SCHEMA_VERSION = "1.0"
DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "evidence-bundle-audit-report-v1.schema.json"
MAX_REPORT_BYTES = 5 * 1024 * 1024
MAX_DIAGNOSTICS = 10_000
MAX_JSON_NESTING_DEPTH = 100
MAX_SCHEMA_VALIDATION_ERRORS = 100


class AuditReportErrorCode(str, Enum):
    """Stable machine-readable failure categories for consumer integrations."""

    INVALID_INPUT = "AUDIT_REPORT_INVALID_INPUT"
    UNSUPPORTED_VERSION = "AUDIT_REPORT_UNSUPPORTED_VERSION"
    MALFORMED_JSON = "AUDIT_REPORT_MALFORMED_JSON"
    INVALID_UTF8 = "AUDIT_REPORT_INVALID_UTF8"
    DUPLICATE_KEYS = "AUDIT_REPORT_DUPLICATE_KEYS"
    NON_FINITE_NUMBER = "AUDIT_REPORT_NON_FINITE_NUMBER"
    NESTING_LIMIT = "AUDIT_REPORT_NESTING_LIMIT"
    SIZE_LIMIT = "AUDIT_REPORT_SIZE_LIMIT"
    DIAGNOSTIC_LIMIT = "AUDIT_REPORT_DIAGNOSTIC_LIMIT"
    SCHEMA_LOAD_FAILURE = "AUDIT_REPORT_SCHEMA_LOAD_FAILURE"
    SCHEMA_ERROR_LIMIT = "AUDIT_REPORT_SCHEMA_ERROR_LIMIT"
    SCHEMA_VIOLATION = "AUDIT_REPORT_SCHEMA_VIOLATION"
    INVARIANT_VIOLATION = "AUDIT_REPORT_INVARIANT_VIOLATION"


class AuditReportContractError(ValueError):
    """The report cannot safely be consumed under the supported contract."""

    def __init__(self, message: str, code: AuditReportErrorCode = AuditReportErrorCode.INVALID_INPUT):
        super().__init__(message)
        self.code = code.value


class UnsupportedAuditReportVersion(AuditReportContractError):
    """The report declares a version this consumer does not implement."""

    def __init__(self, message: str):
        super().__init__(message, AuditReportErrorCode.UNSUPPORTED_VERSION)


def _reject_non_finite_constant(token: str) -> None:
    """Reject JavaScript-style non-finite tokens accepted by Python's JSON parser."""
    raise AuditReportContractError("audit report contains a non-finite JSON number", AuditReportErrorCode.NON_FINITE_NUMBER)


def _check_json_nesting_depth(text: str, maximum: int | None = None) -> None:
    """Bound container nesting before invoking the recursive standard-library parser."""
    if maximum is None:
        maximum = MAX_JSON_NESTING_DEPTH
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > maximum:
                raise AuditReportContractError("audit report exceeds the maximum JSON nesting depth", AuditReportErrorCode.NESTING_LIMIT)
        elif character in "]}":
            depth -= 1
            # Mismatched closing tokens are left for json.loads to diagnose. Keep
            # the scanner non-recursive and avoid treating malformed input as valid.
            if depth < 0:
                return


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AuditReportContractError("audit report contains duplicate JSON object keys", AuditReportErrorCode.DUPLICATE_KEYS)
        result[key] = value
    return result


def parse_audit_report_json(
    raw: bytes | str,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
) -> dict[str, Any]:
    """Parse and validate untrusted JSON text/bytes under explicit resource limits."""
    if isinstance(raw, bytes):
        if len(raw) > MAX_REPORT_BYTES:
            raise AuditReportContractError("audit report exceeds the maximum allowed size", AuditReportErrorCode.SIZE_LIMIT)
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise AuditReportContractError("audit report must be valid UTF-8 JSON", AuditReportErrorCode.INVALID_UTF8) from exc
    elif isinstance(raw, str):
        # Every Unicode code point needs at least one UTF-8 byte; reject obviously
        # oversized text before allocating an encoded copy.
        if len(raw) > MAX_REPORT_BYTES:
            raise AuditReportContractError("audit report exceeds the maximum allowed size", AuditReportErrorCode.SIZE_LIMIT)
        try:
            encoded = raw.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise AuditReportContractError("audit report must be valid UTF-8 JSON", AuditReportErrorCode.INVALID_UTF8) from exc
        if len(encoded) > MAX_REPORT_BYTES:
            raise AuditReportContractError("audit report exceeds the maximum allowed size", AuditReportErrorCode.SIZE_LIMIT)
        text = raw
    else:
        raise AuditReportContractError("audit report input must be UTF-8 bytes or text", AuditReportErrorCode.INVALID_INPUT)

    _check_json_nesting_depth(text)
    try:
        report = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except AuditReportContractError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise AuditReportContractError("audit report contains malformed JSON", AuditReportErrorCode.MALFORMED_JSON) from exc
    if not isinstance(report, dict):
        raise AuditReportContractError("audit report must be a JSON object", AuditReportErrorCode.INVALID_INPUT)
    errors = report.get("errors")
    if isinstance(errors, list) and len(errors) > MAX_DIAGNOSTICS:
        raise AuditReportContractError("audit report exceeds the maximum diagnostic count", AuditReportErrorCode.DIAGNOSTIC_LIMIT)
    return validate_audit_report(report, schema_path)


def validate_audit_report(report: Any, schema_path: Path = DEFAULT_SCHEMA_PATH) -> dict[str, Any]:
    """Validate report version, resource boundary and v1 schema; return unchanged."""
    if not isinstance(report, dict):
        raise AuditReportContractError("audit report must be a JSON object", AuditReportErrorCode.INVALID_INPUT)
    version = report.get("audit_report_schema_version")
    if version != REPORT_SCHEMA_VERSION:
        raise UnsupportedAuditReportVersion(
            f"unsupported audit report schema version: {version!r}"
        )
    diagnostics = report.get("errors")
    if isinstance(diagnostics, list) and len(diagnostics) > MAX_DIAGNOSTICS:
        raise AuditReportContractError("audit report exceeds the maximum diagnostic count", AuditReportErrorCode.DIAGNOSTIC_LIMIT)
    # Classify a well-typed count/list mismatch consistently before schema rules
    # (such as FAIL requiring a positive count) can mask it as a generic violation.
    declared_count = report.get("error_count")
    if report.get("status") != "PASS" and isinstance(declared_count, int) and not isinstance(declared_count, bool) and isinstance(diagnostics, list):
        if declared_count != len(diagnostics):
            raise AuditReportContractError(
                "audit report error_count must equal the number of error entries",
                AuditReportErrorCode.INVARIANT_VIOLATION,
            )
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        # Never materialize/sort an unbounded iterator of schema errors. Consume
        # at most one beyond the public cap, then fail closed if the cap is crossed.
        errors = list(islice(
            Draft202012Validator(
                schema, format_checker=Draft202012Validator.FORMAT_CHECKER
            ).iter_errors(report),
            MAX_SCHEMA_VALIDATION_ERRORS + 1,
        ))
        if len(errors) > MAX_SCHEMA_VALIDATION_ERRORS:
            raise AuditReportContractError(
                "audit report exceeds the maximum schema validation error count", AuditReportErrorCode.SCHEMA_ERROR_LIMIT
            )
        errors.sort(key=lambda error: list(map(str, error.absolute_path)))
    except AuditReportContractError:
        raise
    except Exception as exc:
        # Keep filesystem/parser/schema internals out of the consumer-facing error.
        raise AuditReportContractError("audit report schema could not be loaded or validated", AuditReportErrorCode.SCHEMA_LOAD_FAILURE) from exc
    if errors:
        first = errors[0]
        location = ".".join(map(str, first.absolute_path)) or "$"
        raise AuditReportContractError(
            f"audit report violates schema at {location}: {first.message}", AuditReportErrorCode.SCHEMA_VIOLATION
        )

    # JSON Schema cannot express equality between error_count and errors.length.
    # Enforce these cross-field invariants after structural validation succeeds.
    diagnostics = report["errors"]
    if report["error_count"] != len(diagnostics):
        raise AuditReportContractError(
            "audit report error_count must equal the number of error entries",
            AuditReportErrorCode.INVARIANT_VIOLATION,
        )
    core_checks = (
        report["checks"]["manifest_schema"],
        report["checks"]["file_inventory_and_hashes"],
        report["checks"]["envelope_payload_binding"],
    )
    if report["status"] == "FAIL" and "SEE_ERRORS" not in core_checks:
        raise AuditReportContractError(
            "FAIL status requires at least one core check to reference errors",
            AuditReportErrorCode.INVARIANT_VIOLATION,
        )
    if report["status"] == "ERROR" and not diagnostics:
        raise AuditReportContractError(
            "ERROR status requires at least one diagnostic entry",
            AuditReportErrorCode.INVARIANT_VIOLATION,
        )
    return report


def consume_audit_report_json(raw: bytes | str, schema_path: Path = DEFAULT_SCHEMA_PATH) -> dict[str, Any]:
    """Simulate an integration consuming a report and mapping it to a stable result.

    Parsing/schema/invariant errors raise ``AuditReportContractError``. Successful
    consumption exposes only stable status, exit mapping, count, and code groups.
    """
    report = parse_audit_report_json(raw, schema_path)
    status = report["status"]
    exit_code = {"PASS": 0, "FAIL": 1, "ERROR": 2}[status]
    return {
        "status": status,
        "exit_code": exit_code,
        "error_count": report["error_count"],
        "diagnostics_by_code": diagnostics_by_code(report),
    }


def diagnostics_by_code(report: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """Group already-validated diagnostics by stable code, preserving item order."""
    grouped: dict[str, list[dict[str, str]]] = {}
    for diagnostic in report["errors"]:
        grouped.setdefault(diagnostic["code"], []).append(diagnostic)
    return grouped
