# Audit Report Consumer Compatibility Contract

**Current report schema:** `1.0`  
**Schema file:** `schemas/evidence-bundle-audit-report-v1.schema.json`  
**Golden consumer fixture:** `tests/fixtures/audit-report-consumer-v1.json`

## Consumer requirements

1. Read `audit_report_schema_version` before interpreting the rest of the report. This release supports exactly `1.0`; reject missing or unknown versions instead of guessing.
2. Validate the full report against the versioned JSON Schema. The v1 top-level object and nested objects are closed (`additionalProperties: false`) so unreviewed structural changes fail clearly.
3. Branch on `errors[].code`, not `message`, `remediation`, or `raw_message`. Human-readable prose may be clarified without changing the code's meaning.
4. Treat diagnostic codes as opaque stable identifiers. A consumer should handle unknown codes generically (display message, preserve raw message, log code) rather than crash or assume the code is impossible.
5. Preserve repeated errors and order. `error_count` must equal `len(errors)`; `PASS` requires no errors, while `FAIL` requires at least one.
6. `cryptographic_authenticity: NOT_ESTABLISHED` is not a positive authenticity claim.

## Input parsing and resource boundaries

- Prefer `parse_audit_report_json(bytes_or_text, schema_path=...)` for untrusted serialized input. It accepts strict UTF-8 bytes or text, rejects malformed/truncated JSON, duplicate object keys, and top-level non-object JSON, then validates the supported report contract.
- The default maximum serialized report size is **5 MiB** (UTF-8 bytes). Inputs above the limit are rejected before JSON parsing.
- The default maximum diagnostic count is **10,000**. Reports exceeding this count are rejected before full JSON Schema validation.
- The default maximum JSON container nesting depth is **100**. A non-recursive pre-scan rejects excessive nesting before calling the standard-library JSON parser.
- Schema validation consumes at most **101** errors to enforce a maximum of **100** reported schema errors; exceeding that cap fails closed rather than materializing or sorting an unbounded error list. This bounds error amplification, not total CPU/memory usage for every valid-under-limit report.
- Reject Python JSON parser extensions `NaN`, `Infinity`, and `-Infinity`; these are not valid JSON numbers. Duplicate keys are rejected rather than silently accepting the last value.
- These limits are consumer safety ceilings, not a promise that every report below them is cheap to process.
- Invalid UTF-8 and malformed JSON produce `AuditReportContractError` with generic messages. Missing, unreadable, malformed, or invalid schema files also fail closed with a generic consumer-facing error; inspect chained exception details only in a trusted debugging context.
- `validate_audit_report()` accepts an already-parsed object and therefore cannot enforce the serialized byte limit; it still enforces schema version and diagnostic-count limits. Untrusted input should enter through the parsing helper.

## Stable consumer failure taxonomy

`AuditReportContractError.code` is a stable machine-readable category. Integrations should branch on `code`, not exception prose. Current codes are:

- `AUDIT_REPORT_INVALID_INPUT` — wrong input type or top-level JSON value is not an object.
- `AUDIT_REPORT_UNSUPPORTED_VERSION` — missing or unsupported schema version (subclass: `UnsupportedAuditReportVersion`).
- `AUDIT_REPORT_MALFORMED_JSON` — malformed/truncated JSON syntax.
- `AUDIT_REPORT_INVALID_UTF8` — bytes/text cannot be represented as strict UTF-8.
- `AUDIT_REPORT_DUPLICATE_KEYS` — duplicate object keys.
- `AUDIT_REPORT_NON_FINITE_NUMBER` — `NaN`, `Infinity`, or `-Infinity` token.
- `AUDIT_REPORT_NESTING_LIMIT`, `AUDIT_REPORT_SIZE_LIMIT`, `AUDIT_REPORT_DIAGNOSTIC_LIMIT` — respective resource ceiling exceeded.
- `AUDIT_REPORT_SCHEMA_LOAD_FAILURE` — schema could not be loaded or self-validated; internal details remain in the chained cause for trusted debugging.
- `AUDIT_REPORT_SCHEMA_ERROR_LIMIT` — more than 100 schema validation errors encountered.
- `AUDIT_REPORT_SCHEMA_VIOLATION` — parsed report does not match the supported schema.
- `AUDIT_REPORT_INVARIANT_VIOLATION` — cross-field report invariants are inconsistent (including count/list mismatch, FAIL without a core check pointing to errors, or ERROR without diagnostics).

The prose message may be clarified without changing a code's meaning. Add a new code for a materially new failure category; do not repurpose an existing code. Consumers should preserve and handle unknown future codes generically.

## Compatibility policy

- **Patch-level maintenance:** wording, remediation text, or bug fixes may change only when they do not contradict the published meaning of existing fields/codes. Consumers must not branch on prose.
- **Additive diagnostics:** new stable `errors[].code` values may be added under schema `1.0`; consumers must support unknown codes generically. The field shape and code syntax remain unchanged.
- **Breaking structural changes:** removing/renaming fields, changing types/semantics, or changing the required error object shape requires a new schema version and schema file. Do not silently reinterpret `1.0`.
- **Unsupported versions:** fail closed with `UnsupportedAuditReportVersion`; do not attempt to parse a newer report using an older schema.
- **Operational failures:** CLI exit `2` may produce no JSON report. Consumers must not parse empty stdout as a report.

## Reference implementation

`audit_report_consumer.py` implements explicit version gating, JSON Schema validation, cross-entry invariants, grouping diagnostics by stable code, and `consume_audit_report_json()` as a local integration simulation. The simulation maps PASS/FAIL/ERROR to exit values 0/1/2 and returns status, count, and code groups only after validation. It is not a target-agent integration test.

## Regression coverage

`tests/test_audit_report_consumer.py` covers the golden v1 report, unknown/missing versions, non-object input, schema drift, stable-code branching independent of prose, repeated diagnostics, additive unknown diagnostic codes, and the explicit schema version. `tests/test_audit_report_consumer_taxonomy.py` covers the schema mutation matrix and stable machine-readable failure codes. `tests/test_audit_report_consumer_limits.py` covers malformed/truncated JSON, invalid UTF-8, duplicate keys, non-object JSON, exact/over size and diagnostic limits, generic schema-load failures, non-finite tokens, nesting limits, brackets/escapes inside strings, bounded schema-error iteration, and stable schema-failure messages. `tests/test_audit_report_consumer_cost.py` verifies the bounded schema-error iterator.


## D0-66 cross-entry invariants and integration simulation

After schema validation, the consumer also enforces relationships that JSON Schema cannot express reliably: `error_count` must equal the number of `errors` entries; `FAIL` must have at least one core check marked `SEE_ERRORS`; and `ERROR` must include at least one diagnostic. `PASS` remains constrained by the schema to have zero diagnostics and all core checks `PASS`. Count/list drift on non-PASS reports receives `AUDIT_REPORT_INVARIANT_VIOLATION`; schema-defined PASS contradictions retain `AUDIT_REPORT_SCHEMA_VIOLATION` for backward compatibility.

`consume_audit_report_json()` exercises the parse → version/schema → invariant → stable-code grouping path and maps report status to a local integration result (PASS=0, FAIL=1, ERROR=2). This is a model-free simulation only; it does not prove compatibility with any external agent runtime. Coverage: `tests/test_audit_report_consumer_integration.py`.

## D0-67 runnable CLI consumer and exit reconciliation

`scripts/consume_audit_report.py` provides a process-level consumer interface. It accepts a report path or `-`/stdin (default), reads no more than `MAX_REPORT_BYTES + 1` bytes before delegating to the bounded parser, and emits a compact normalized JSON result only after parsing, version/schema validation, and cross-entry invariant checks succeed.

- Exit `0`: validated `PASS` report; normalized result has `status=PASS`, `exit_code=0`, and zero diagnostics.
- Exit `1`: validated `FAIL` report; normalized result has `status=FAIL`, `exit_code=1`, and diagnostic-code groups whose total item count equals `error_count`.
- Exit `2`: malformed/untrusted report, schema/invariant rejection, CLI usage error, or input I/O failure. Consumer contract errors print only the stable error code to stderr and produce no JSON on stdout. Input I/O failures do not disclose the supplied filesystem path.
- A producer CLI exit `2` may have no JSON report; never feed empty stdout to a consumer as if it were a report.

`tests/test_z_cli_consumer_e2e.py` launches the verifier and consumer in real subprocesses and verifies PASS/FAIL exit reconciliation, normalized diagnostic cardinality, stdin/file equivalence, malformed JSON fail-closed behavior, usage errors, and generic path-safe input I/O errors. This verifies the shipped local CLIs only; it does not establish integration with an external AI-agent runtime.

## D0-68 CLI output atomicity and input parity

The verifier's optional `--json-report` output is staged in a uniquely named temporary file in the destination directory, flushed and `fsync`ed, then installed with `os.replace`. A failed write/replace returns exit `2`, emits no JSON on stdout, preserves any existing destination file, and removes its temporary file. The destination parent is canonicalized for bundle-containment checks, but the final path component is not dereferenced: an existing destination symlink is replaced as a directory entry, and its target is not overwritten. Parent-directory symlinks cannot be used to bypass the rule that report outputs must be outside the bundle.

The consumer CLI must behave identically for stdin and file inputs: same stable error code and exit `2` for malformed JSON, invalid UTF-8, or an oversized report, with no normalized JSON on stdout. Input file errors must not disclose the supplied path. Regression coverage lives in `tests/test_d0_68_cli_output_atomicity.py`; this is local filesystem/process behavior, not a guarantee against every filesystem or power-loss failure mode.
