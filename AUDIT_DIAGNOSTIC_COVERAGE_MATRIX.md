# Audit Diagnostic Coverage Matrix (D0-58)

Version: 1.0  
Scope: stable mapping from `verify_evidence_bundle()` raw error prefixes to audit-report diagnostic codes. The matrix covers every configured matching needle; the golden JSON corpus is the executable source of expected classifications.

| Source condition / raw-message prefix | Stable code | Category | Severity | Golden test |
|---|---|---|---|---|
| `manifest is missing or unsafe` | `BUNDLE_MANIFEST_MISSING_OR_UNSAFE` | `manifest` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| `manifest exceeds size limit` | `BUNDLE_MANIFEST_TOO_LARGE` | `resource_limit` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| `manifest parse failed:` | `BUNDLE_MANIFEST_PARSE_FAILED` | `manifest` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| `manifest schema:` | `BUNDLE_MANIFEST_SCHEMA_INVALID` | `schema` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| `manifest schema unavailable` | `BUNDLE_MANIFEST_SCHEMA_INVALID` | `schema` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| `unsupported manifest version` | `BUNDLE_MANIFEST_FORMAT_UNSUPPORTED` | `compatibility` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| `unsafe manifest file path:` | `BUNDLE_PATH_UNSAFE_OR_DUPLICATE` | `path` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| `envelope_path is unsafe` | `BUNDLE_PATH_UNSAFE_OR_DUPLICATE` | `path` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| `duplicate manifest path:` | `BUNDLE_PATH_UNSAFE_OR_DUPLICATE` | `path` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| `unsafe or duplicate` | `BUNDLE_PATH_UNSAFE_OR_DUPLICATE` | `path` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| `missing or unsafe file:` | `BUNDLE_FILE_MISSING_OR_UNSAFE` | `inventory` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| `manifest lists absent file:` | `BUNDLE_FILE_MISSING_OR_UNSAFE` | `inventory` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| `size mismatch:` | `BUNDLE_FILE_SIZE_MISMATCH` | `integrity` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| `SHA-256 mismatch:` | `BUNDLE_FILE_HASH_MISMATCH` | `integrity` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| `unlisted file:` | `BUNDLE_FILE_UNLISTED` | `inventory` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| `symlink is not allowed:` | `BUNDLE_SYMLINK_FORBIDDEN` | `path` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| `envelope_sha256 does not match` | `BUNDLE_ENVELOPE_HASH_BINDING_MISMATCH` | `binding` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| `envelope artifact hashes do not exactly match` | `BUNDLE_ENVELOPE_INVENTORY_MISMATCH` | `binding` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| `envelope verification failed:` | `BUNDLE_ENVELOPE_INVALID` | `envelope` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| `manifest envelope_path is not in file inventory` | `BUNDLE_ENVELOPE_INVALID` | `envelope` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| `provenance envelope missing from file inventory` | `BUNDLE_ENVELOPE_INVALID` | `envelope` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |
| Any unmatched verifier message | `BUNDLE_VERIFICATION_FAILED_UNCLASSIFIED` | `verification` | `error` | `tests/fixtures/audit-diagnostics-v1.json` |

## Contract rules

- Codes are public identifiers: never rename, renumber, or reuse a code; introduce a new code for a new stable failure class.
- The first matching rule wins. Keep prefixes specific enough to avoid accidental shadowing; add collision tests when prefixes overlap.
- `raw_message` is retained verbatim for diagnosis; consumers should branch on `code`, not message prose.
- Unrecognized messages use the explicit fallback code and remain a verification failure.
- The golden corpus tests all configured prefix needles and one unknown-message fallback. It does not prove every future runtime error is mapped; newly observed messages must be triaged and added deliberately.
- This is model-free local verifier evidence only; no signatures, trusted identity, provider execution, OS sandbox, TTS inference, or target-agent integration is established.

## Verification command

```bash
python -m pytest -q tests/test_audit_diagnostics.py tests/test_audit_diagnostic_golden_corpus.py tests/test_evidence_bundle_cli.py
```

## D0-59 precedence and shadowing audit

- Matching uses **first configured rule wins**; `_RULES` order is therefore part of the diagnostic API behavior.
- A regression test checks every pair of distinct configured rules by combining representative needles and verifies the earlier rule wins deterministically.
- A separate test rejects literal substring shadowing between needles that belong to different stable codes. Same-code alternative needles are allowed because they intentionally share one diagnostic.
- Current configured needle set has no cross-code literal-substring collisions. Pairwise combined-message tests are synthetic precedence probes; they do not claim the underlying verifier naturally emits every combined message.
- If future rules intentionally overlap, narrow the needle or introduce an explicit documented exception plus a focused regression test before merging.
