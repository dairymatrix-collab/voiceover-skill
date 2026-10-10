# Voiceover Skill — Contract Harness Test Evidence

## D0-32 result

- Scope: compatibility and error-code consistency audit for model-free IPC contract validation.
- Result: PASS for local validator and protocol error reporting only.
- Test command: `python -m pytest -q`
- Latest result: 122 passed in 0.97s.
- Python compilation: `python -m py_compile contracts.py ipc_contract.py tests/test_contracts.py tests/test_ipc_contract.py` — PASS.
- JSON Schema dialect: Draft 2020-12; request and result schemas pass `Draft202012Validator.check_schema`.
- `IPCContractError` now exposes machine-readable `.code` and optional `.detail` without changing `str(error)` compatibility.
- Regression tests compare direct-validation and parse-and-validate code, detail, and string output for JSON-representable invalid requests and results.
- Non-finite values supplied as raw JSON tokens are rejected by the parser as `PROTOCOL_NONFINITE_NUMBER`; direct Python non-finite values are rejected by semantic validation as `PROTOCOL_SCHEMA_INVALID`. This distinction reflects different failure stages.
- Fixtures are synthetic and local. No network, model weights, credentials, worker process, or TTS inference was used.

## Known limitations

- Numeric limits remain provisional and are not benchmarked against the approved agent runtime.
- This is not an IPC transport, OS sandbox, process-tree cancellation implementation, or security certification.
- Lexical path validation does not prevent symlink races or establish resolved-path containment. The future supervisor must enforce containment at filesystem operations.
- Audio metadata must be independently checked against actual bytes by the supervisor; a schema-valid manifest is not proof that an audio file is valid.
- No production TTS adapter, offline-readiness, or real-model capability is claimed.


## D0-33 result

- Scope: deterministic, model-free malformed-input regression suite for the JSONL parser.
- Result: PASS for tested parser robustness cases only.
- Test command: `python -m pytest -q` — **133 passed**.
- Added 500 seeded arbitrary-byte inputs and 150 seeded Unicode JSON round-trips, plus adversarial exponent-overflow, escaped lone-surrogate, deep nesting, oversized integer, and line-size cases.
- Parser now rejects floating-point exponent overflow (`1e999`) as `PROTOCOL_NONFINITE_NUMBER` and decoded lone surrogate code points as `PROTOCOL_INVALID_UNICODE`.
- Hypothesis is not installed in the current offline environment. Deterministic tests were used; no network install was attempted.
- No model downloads, credentials, network requests, worker processes, or real TTS inference.

### D0-33 limitations

- Seeded tests are not exhaustive fuzzing and do not constitute a security audit.
- Resource limits beyond the per-line byte cap, including parser CPU/memory under hostile repeated messages, need a real supervisor/transport design and process-level tests.
- OS sandboxing, filesystem containment at open time, symlink/race defenses, worker cancellation, and real TTS inference remain unimplemented.

## D0-34 result

- Scope: parser resource-boundary review and structured error-path regression for model-free JSONL parsing.
- Result: PASS for bounded line parsing, pre-parse nesting checks, integer token limits, and repeated hostile-message error stability.
- Test command: `python -m pytest -q` — **139 passed**.
- Added `MAX_JSON_NESTING = 128`; a lightweight string/escape-aware scan rejects excessive nesting before recursive JSON decoding with `PROTOCOL_NESTING_TOO_DEEP`.
- Added `MAX_INTEGER_DIGITS = 1024`; oversized integer tokens fail with `PROTOCOL_INTEGER_TOO_LONG` before integer conversion.
- Added exact-boundary tests, string-bracket/escaped-quote regression, malformed bracket error consistency, and 1,000 repeated hostile-message cases.
- Python compilation and both Draft 2020-12 schema self-checks pass.
- Synthetic local data only; no network, model weights, credentials, worker process, or real TTS inference.

### D0-34 limitations

- The nesting scanner and token limits bound specific parser work but do not constitute process-level memory/CPU isolation or a general denial-of-service guarantee.
- Repeated-message tests execute sequentially in one process; they do not test transport backpressure, concurrency, process restart, or supervisor cancellation.
- The 128-level nesting and 1,024-digit integer limits are conservative provisional values and need compatibility review against the eventual approved worker protocol.
- Filesystem containment, symlink/race defenses, actual IPC transport, worker cancellation, OS sandboxing, and real TTS inference remain unimplemented.

### D0-34 acceptance checklist

- [x] Review line, nesting, and numeric-token resource boundaries.
- [x] Add bounded pre-parse nesting rejection that respects quoted strings and escapes.
- [x] Add explicit integer-token digit limit and stable error code.
- [x] Add boundary, malformed-structure, and repeated hostile-input regressions.
- [x] Run complete tests, compilation, schema self-checks, manifest verification, and ZIP integrity checks.
- [ ] Test process-level resource limits, backpressure, cancellation, and worker supervision — NOT DONE.

### Decision and recovery checkpoint

**D0-34 result: PASS for local parser resource boundaries only.** Phase 0 remains **OPEN / HOLD**. Do not claim production IPC security, sandboxing, process-level resource guarantees, offline readiness, or real TTS capability.

- Last completed task: D0-34 — IPC Parser Resource-Boundary Review and Structured Error-Path Audit.
- Next task: D0-35 — Protocol Compatibility Fixtures and Versioned Contract Review. Keep the work model-free; production adapters remain gated on unresolved upstream/runtime feasibility.

## D0-35 — Protocol Compatibility Fixtures and Versioned Contract Review

- Added versioned v1 fixtures: valid request, valid result, request with an unknown field, and request with a future protocol version.
- Added automated checks for fixture validation through public entrypoints, strict rejection of unknown fields/future versions, and boolean protocol version rejection.
- Tightened both JSON Schemas to require `protocol_version` to be an integer as well as equal to 1. This closes the Python `True == 1` equality edge case in schema validators.
- Documented the compatibility policy: v1 is closed (`additionalProperties: false`); adding fields requires a coordinated version change; v2 migration/negotiation must be explicit.
- Full test suite: 144 passed (1.12s) at initial implementation check; final verification is recorded in the D0-35 ledger section.
- Scope remains model-free. No worker, actual IPC transport, filesystem sandbox, model weights, or TTS inference was tested.

### Final D0-35 verification

- `python -m py_compile contracts.py ipc_contract.py tests/test_contracts.py tests/test_ipc_contract.py tests/test_protocol_fuzz.py` — PASS.
- `python -m pytest -q` — **144 passed in 1.10s**.
- `Draft202012Validator.check_schema` on both request/result schemas — PASS.
- All four JSON fixtures parsed successfully — PASS.
- SHA-256 manifest and ZIP integrity checks are recorded in the final task output after packaging.

## D0-36 — Cross-Implementation Schema Conformance & Deterministic Serialization

- Added `canonical_jsonl_message()` for valid v1 request/result objects.
- Serialization profile: lexicographically sorted object keys at every depth, compact separators, UTF-8 with non-ASCII characters preserved, non-finite numbers forbidden, and exactly one LF terminator.
- Added regression tests for mapping insertion-order independence, Unicode (including non-Latin scripts and emoji), escaped embedded newlines, sorted keys, invalid schema/non-finite inputs, and request/result fixture round trips.
- Important scope caveat: this is deterministic for the Python JSON implementation; it is not RFC 8785/JCS canonicalization and does not prove byte-identical number formatting across programming languages.
- Final full test suite: 149 passed. Compilation, schema self-checks, manifest verification, and ZIP integrity were checked after packaging.
- No network, model weights, credentials, worker process, external agent runtime, or TTS inference was used.
- Phase 0 remains OPEN / HOLD. Process isolation, production transport, filesystem containment and real TTS adapters remain unimplemented.

## D0-37 result — Independent JSON Schema Conformance Vectors

- Added `tests/fixtures/schema-conformance-v1.json` with named request/result vectors for booleans, nulls, integer and numeric boundaries, protocol version, result status, and relative-path grammar.
- Added `tests/test_schema_conformance.py`, which compares expected outcomes against both Draft 2020-12 JSON Schema validation and the public direct Python validators. The test fails with named mismatch details if either validator disagrees with the expected vector.
- Audit finding: prior schema path regexes were more permissive than the direct validator for trailing separators and whitespace-containing paths. Tightened both schemas to a conservative ASCII relative-path alphabet and added vectors for trailing slash and spaces. Paths with spaces are now intentionally outside the v1 contract.
- JSON-representable vectors all agree across schema and public validator. Python-only `NaN`/infinity direct inputs remain separately rejected and are not JSON Schema interchange values.
- Full suite after implementation: `python -m pytest -q` — **155 passed**.
- Python compilation, both schema self-checks, vector fixture parsing, SHA-256 manifest verification, and ZIP integrity are included in final verification.

### D0-37 limitations

- Vectors are an independently authored test fixture, not a formal external conformance suite and not proof of cross-language or deployed-worker interoperability.
- Conservative path alphabet excludes spaces by design; changing this later requires a deliberate contract/schema update.
- Filesystem containment, symlink/race-safe file operations, production IPC transport, process isolation, worker cancellation, and real TTS inference remain unimplemented.
- Phase 0 remains **OPEN / HOLD**.

### Final D0-37 verification checkpoint

- `python -m py_compile contracts.py ipc_contract.py tests/test_contracts.py tests/test_ipc_contract.py tests/test_protocol_fuzz.py tests/test_schema_conformance.py` — PASS.
- `python -m pytest -q` — **155 passed**.
- Both Draft 2020-12 schemas pass `Draft202012Validator.check_schema` — PASS.
- All 5 JSON fixtures parse successfully — PASS.
- SHA-256 manifest — **17/17 entries OK**.
- ZIP integrity — PASS; `.pyc`, `__pycache__`, and `.pytest_cache` excluded.
- Final scope remains local model-free contract conformance only. Phase 0 is **OPEN / HOLD**.

## D0-38 — Schema Boundary Mutation Testing & Validator Error-Path Coverage

### Changes

- Added `tests/test_schema_mutation.py` with deterministic mutations for required-field deletion, top-level/nested unknown fields, invalid message-type values, valid baseline acceptance, and recursive direct-Python containers.
- Compared JSON Schema acceptance and public Python validator acceptance for the JSON-representable mutation cases.
- Found and fixed an error-path gap: cyclic/non-JSON Python containers supplied directly to the public validator could cause schema-library `RecursionError`/`TypeError` to escape. `_first_schema_error()` now converts these failures into the stable `PROTOCOL_SCHEMA_INVALID:$` contract error.
- Added canonical serialization regression coverage for recursive objects to ensure the public API returns a contract error rather than leaking the underlying exception.

### Verification

- Baseline before D0-38: `python -m pytest -q` — **155 passed**.
- Post-change full suite: `python -m pytest -q` — **180 passed**.
- Python compilation — PASS.
- Both Draft 2020-12 schemas pass `Draft202012Validator.check_schema` — PASS.
- All JSON fixtures parse — PASS.
- SHA-256 manifest and ZIP integrity — checked after packaging.

### Limitations

- Mutation cases are deterministic and locally authored, not exhaustive property-based fuzzing or an external conformance suite.
- Catching common schema-library errors for malformed direct-Python objects does not mean arbitrary Python objects are valid protocol values. Untrusted peers must still enter through strict JSONL parsing.
- This does not implement transport backpressure, worker process isolation, filesystem containment, cancellation, actual engine startup, or real TTS inference.
- Phase 0 remains **OPEN / HOLD**.

### Acceptance checklist

- [x] Add deterministic mutation cases across request/result schema boundaries.
- [x] Compare schema and public-validator acceptance for JSON-representable cases.
- [x] Cover missing required fields and unknown fields at multiple nesting levels.
- [x] Ensure malformed recursive Python containers produce structured contract errors.
- [x] Run full suite, compilation, schema self-checks, fixture parsing, manifest verification, and ZIP integrity checks.
- [ ] Establish formal external/cross-language conformance — NOT DONE.
- [ ] Implement production IPC, filesystem containment, process isolation, and actual TTS inference — NOT DONE.

### Decision and recovery checkpoint

**D0-38 result: PASS for local deterministic schema mutation and structured error-path coverage only.** Phase 0 remains **OPEN / HOLD**. Do not claim production IPC security, cross-runtime interoperability, offline readiness, or real TTS capability.

- Last completed task: D0-38 — Schema Boundary Mutation Testing & Validator Error-Path Coverage.
- Next task: D0-39 — JSONL End-to-End Contract Matrix and Failure Classification Audit. Keep it model-free and preserve all v1 fixtures.

## D0-39 result

- Scope: end-to-end JSONL framing, UTF-8 parsing, request/result validation, correlation checks, and stable failure classification.
- Result: PASS for the local model-free request/result pipeline matrix only.
- Added `tests/test_jsonl_e2e_matrix.py` to exercise existing valid/invalid protocol-v1 fixtures through public entry points, canonical serialization round-trips, malformed framing/JSON/UTF-8, duplicate keys, non-finite numeric tokens, escaped lone surrogates, schema-invalid requests, invalid relative paths, correlation ID mismatches, and multilingual text preservation.
- Full test suite: `python -m pytest -q` — **204 passed**.
- Python compilation — PASS.
- Both Draft 2020-12 schemas pass `Draft202012Validator.check_schema` — PASS.
- All JSON fixture files parse — PASS.
- SHA-256 manifest and ZIP integrity verified after packaging.
- No model weights, network access, credentials, worker process, external agent runtime, or actual TTS inference used.

### D0-39 limitations

- The matrix exercises the current Python implementation only; it is not a formal external protocol conformance suite or cross-language interoperability proof.
- No real transport supervisor, streaming/backpressure, process cancellation, filesystem containment, symlink/race defense, OS isolation, or actual TTS inference is implemented.
- Error classification reflects pipeline stage: malformed/non-finite JSON tokens fail in parsing, while schema and path errors occur during validation.
- Phase 0 remains **OPEN / HOLD**.

## D0-40 — Protocol Documentation-to-Code Drift Audit

- Scope: compare user-facing README guarantees with shipped dependencies, source imports, manifest coverage, test evidence history, and explicit production limitations.
- Findings corrected: the README previously implied all contract helpers were standard-library-only even though `ipc_contract.py` imports `jsonschema`; it also understated manifest coverage by omitting `FINAL_TEST_EVIDENCE_REPORT.md`, and described the evidence report as only a D0-23 mapping despite later task sections.
- Changes: clarified that `contracts.py` helper logic uses the standard library while IPC schema validation depends on pinned `jsonschema==4.26.0`; documented the actual manifest coverage and its exclusions; described the evidence report as chronological; reiterated that this is not a production supervisor or TTS implementation.
- Added `tests/test_documentation_contract.py` to catch drift in dependency documentation, manifest-coverage wording, chronological evidence wording, and production-scope disclaimers.
- Full test suite: `python -m pytest -q` — **208 passed**.
- Python compilation for production modules and all test modules — PASS.
- Both Draft 2020-12 schemas pass `Draft202012Validator.check_schema` — PASS.
- All 5 JSON fixture files parse — PASS.
- Manifest verification and ZIP integrity checks are performed after rebuilding the archive.

### D0-40 limitations

- This audit checks selected high-impact README claims; it is not a formal proof that every sentence in all documentation is synchronized with every implementation detail.
- Historical task sections preserve the test counts recorded at each checkpoint; those counts are not intended to equal the current suite total.
- Production IPC supervision, process isolation, filesystem containment at open time, worker cancellation/backpressure, and actual TTS inference remain unimplemented.

### D0-40 decision and recovery checkpoint

**D0-40 result: PASS for selected documentation-to-artifact drift checks only.** Phase 0 remains **OPEN / HOLD**. Do not claim production IPC security, cross-runtime interoperability, offline readiness, or real TTS capability.

- Last completed task: D0-40 — Protocol Documentation-to-Code Drift Audit.
- Next task: D0-41 — Contract Harness Reproducibility & Clean-Archive Audit. Rebuild from the documented manifest, verify hashes from a clean extraction, and check that tests run from the packaged archive without relying on stale caches.

## D0-41 — Contract Harness Reproducibility & Clean-Archive Audit

- Scope: verify the distributed ZIP from a fresh extraction, independently of the original working tree and stale test caches.
- Extracted the ZIP into a new temporary directory (the archive root directly contains the harness files) and verified every entry in `SHA256SUMS` before executing tests.
- Full test suite from the extracted directory: `python -m pytest -q` — **208 passed in 1.57s**.
- Environment: Python 3.13.5, `pytest==9.0.2`, `jsonschema==4.26.0`; pinned dependencies were already installed in the test environment.
- The archive contained only intended source, tests, schemas, fixtures, README, requirements, manifest, and evidence report; no `__pycache__`, `.pyc`, `.pytest_cache`, or virtual-environment entries were present.
- This confirms clean-extraction testability in the current environment. A completely isolated environment with dependency installation from a blank cache and cross-platform reproducibility were not established.
- Phase 0 remains **OPEN / HOLD**; no production IPC supervisor, OS isolation, filesystem containment, or real TTS inference is implied.


## D0-42 — Deterministic Packaging & Verification Script

- Added `scripts/build_package.py`, a Python-standard-library CLI that regenerates a SHA-256 manifest, sorts archive paths, normalizes ZIP timestamps and file metadata, excludes common caches/temporary files, validates safe ZIP member paths, verifies archive CRCs, and checks the extracted manifest.
- Added packaging regression tests for reproducible output, cache/temp exclusions, archive manifest presence, and rejection of manifest path traversal.
- Reproducibility claims are scoped to byte-identical builds in the current Python/zlib environment; cross-platform archive equivalence is not claimed.
- Final suite from a fresh ZIP extraction: `python -m pytest -q` — **210 passed**.
- Python compilation, both JSON Schema self-checks, all five fixture parses, SHA-256 manifest verification, ZIP CRC/integrity, sorted archive member order, and cache/temp exclusion — **PASS**.
- Production IPC, filesystem containment at open time, worker supervision/isolation, actual TTS inference, and external agent-runtime integration remain unimplemented. Phase 0 remains **OPEN / HOLD**.

## D0-43 result — Packaging CLI failure-mode and atomicity audit

- Scope: invalid output location preflight, staged ZIP-write failure, prior-release preservation, temporary-file cleanup, malformed ZIP rejection, and source-tree immutability.
- Result: PASS for the failure modes exercised by local regression tests.
- Added a unique sibling staging file for each build. The final archive is replaced with `os.replace` only after ZIP CRC validation; failed staging writes preserve an existing destination and remove the failed staging file.
- Added CLI preflight for output paths that are directories or whose existing parent is not a directory. This prevents the known invalid-parent case from modifying `SHA256SUMS` before failing.
- Added tests for simulated `writestr` failure, existing release preservation, staging cleanup, malformed archive rejection, invalid output-parent behavior, and unchanged source files apart from the generated manifest.
- Full local test suite: **214 passed**. Python compilation: PASS.
- No actual TTS models, network downloads, external agent runtime, OS process sandbox, or production IPC were exercised.

### D0-43 limitations

- Atomic replacement guarantees depend on filesystem/platform semantics; power loss, disk-full during filesystem metadata updates, permission changes mid-build, and concurrent builds targeting the same output were not exhaustively simulated.
- The packager still regenerates `SHA256SUMS` as an intentional source-tree change. It does not alter other source files.
- Phase 0 remains **OPEN / HOLD**; no real TTS inference is implemented.

### D0-43 final distribution verification

- Rebuilt after documentation updates and generated two independent reproducibility archives; both hashes matched: `0e31fe5d61b183baf2b82ec8ab53d32319212fe47be0561bcf4c98c49ca7d3e6`.
- Fresh extraction: all 22 SHA-256 manifest entries passed; full suite **214 passed in 3.95s**.
- Both Draft 2020-12 schemas passed self-validation; all five JSON fixtures parsed; Python compilation passed.
- ZIP integrity passed; 23 members are sorted; cache/temporary artifacts are excluded.

## D0-44 — Package Integrity, Manifest Parsing & ZIP Member Type Audit

**Date:** 2026-10-04  
**Status:** PASS for the explicit local manifest/ZIP metadata cases covered by regression tests.

### Changes

- Require SHA-256 digests to be exactly 64 lowercase hexadecimal characters.
- Reject empty, non-canonical, traversal, absolute, backslash-containing, duplicate, and case-colliding manifest paths.
- Reject symlinked parent components and ensure manifest targets resolve inside the verification root.
- Preflight ZIP member count and declared uncompressed size before extraction; reject duplicate/case-colliding paths, directories, path traversal, symlink/special-file metadata, encrypted entries, unsupported compression methods, and cache/temp artifacts.
- Require `SHA256SUMS`, verify CRCs before extraction, and run manifest verification after extraction into a private temporary directory.
- Add adversarial regression tests for malformed digests, duplicate/case-colliding manifest and ZIP paths, symlinked manifest parents, symlink/FIFO/socket ZIP metadata, and oversized declared ZIP payloads.

### Verification evidence

- Focused packaging tests: **11 passed** (one expected Python warning emitted while deliberately creating a duplicate-name adversarial ZIP fixture).
- Full source-tree suite: **219 passed in 3.36s** (one expected duplicate-name fixture warning).
- Both Draft 2020-12 schemas passed self-validation; all five JSON fixtures parsed; Python compilation passed.
- Deterministic build: two independently generated temporary archives were byte-identical; the final distribution hash is recorded in the external development ledger.
- Fresh extraction and full-suite verification are repeated after this report update; final results are recorded in the recovery ledger.
- Limits configured: maximum 1,000 ZIP members and maximum 100 MiB declared uncompressed size. These are guardrails for this small contract harness, not a general-purpose archive service.

### Limitations

- Adversarial ZIP tests use synthetic metadata; this is not a formal security audit or proof against every ZIP parser/platform edge case.
- ZIP CRC and manifest SHA-256 checks provide integrity detection, not publisher authenticity or signatures.
- No actual TTS inference, production IPC supervisor, process isolation, or external agent integration is implemented by this task.
- Phase 0 remains **OPEN / HOLD**.

### Decision and recovery checkpoint

**D0-44 result: PASS for the tested manifest parsing and ZIP member safety checks.** Continue to avoid claims of production readiness. Next task: D0-45 — Re-run packaging and complete clean-extraction regression verification; then select the next smallest dependency-ready runtime design task only if all evidence remains green.


## D0-45 — Model-Free Runtime Worker Boundary

**Date:** 2026-10-04  
**Status:** PASS for the tested direct-child worker boundary; production isolation remains unverified.

### Changes

- Added `runtime_worker.py` to launch a trusted argv list with `shell=False`, a reduced child environment, explicit working-directory validation, and a single-request/single-result JSONL exchange.
- Request is validated and serialized before process launch. Terminal result must be newline-framed, parse as valid JSONL, satisfy the result schema, and match request/job IDs.
- stdout/stderr are drained concurrently with configured byte limits; deadline and `threading.Event` cancellation kill the direct child; start failure and non-zero exit have stable error codes.
- Added model-free subprocess tests for success, invalid request, launch failure, timeout, cancellation, stdout/stderr overflow, non-zero exit, malformed result, correlation mismatch, invalid timeout, and invalid cwd.

### Verification

- Full source-tree suite: **228 passed in 6.80s**; one expected `zipfile` warning is emitted by the pre-existing adversarial duplicate-member test.
- This result is the source-tree run before the final archive was rebuilt. A fresh extraction run, manifest checks, schema/fixture validation, compilation, and reproducible-build comparison must be recorded before release.

### Limitations

- This boundary is a model-free reference implementation; no TTS engine is invoked.
- Only the direct child is explicitly killed. Descendant process-tree termination, OS-level CPU/memory/network isolation, secure audio output path handling, and Windows-specific cancellation behavior are not established.
- The supplied executable/argv must come from trusted application configuration. This code is not a sandbox for arbitrary user-supplied commands.
- Phase 0 remains **OPEN / HOLD**.

### D0-45 final clean-archive checkpoint

- Packager generated 24 SHA-256 manifest entries and a 25-member archive (manifest included); CRC and extracted manifest verification passed.
- Two independent deterministic builds of the final source state matched byte-for-byte.
- Final archive fresh-extraction verification: **228 passed**; all 24 manifest entries matched; both schemas passed Draft 2020-12 self-validation; all five JSON fixtures parsed; Python compilation passed.
- One expected warning comes from deliberately constructing a duplicate ZIP member in the pre-existing adversarial packaging test.
- The archive includes this report and was rebuilt only after the evidence note was finalized; final SHA-256 is reported in the delivery message and independently verified against the generated artifact.

## D0-46 — Worker lifecycle race and I/O cleanup audit

**Date:** 2026-10-04  
**Status:** Implementation PASS for deterministic model-free lifecycle cases; final clean-archive verification pending.

### Changes

- Named the stdout, stderr, and stdin worker threads to make lifecycle leaks observable in regression tests.
- Added exact output-boundary tests: a valid terminal result succeeds when its encoded JSONL length exactly equals `max_stdout_bytes`; the same output fails when the cap is one byte smaller. Empty stderr is accepted with a zero-byte stderr limit.
- Added a 100,000-character valid request test to exercise a larger stdin write and confirm the worker can consume it without deadlocking.
- Added early-child-exit coverage to ensure the writer thread does not remain alive after broken-pipe/exit paths.
- Added deterministic cancellation ordering checks: cancellation observed while the child is running wins; if the child has exited before the supervisor polls, completed success is returned rather than retroactively cancelled.

### Verification

- Source-tree full suite: **233 passed in 10.44s**, with one expected warning from constructing a duplicate ZIP member in an existing adversarial archive test.
- Final deterministic archive build, clean extraction, manifest checks, schema/fixture validation, compilation, and final SHA-256 are recorded in the D0-46 recovery checkpoint below.

### Limitations

- The tests exercise local Python child processes only, not a TTS model or external agent runtime.
- Cancellation and timeout can race; the contract is intentionally based on what the supervisor observes: cancellation is applied while the child is still running, while an already-exited child is evaluated by its exit/result.
- The boundary still does not guarantee process-tree termination, OS-level CPU/RAM/network isolation, or Windows-specific race behavior. A subprocess descendant that inherits pipe descriptors may keep a reader blocked; this remains a known direct-child-only limitation.
- Phase 0 remains **OPEN / HOLD**.

### D0-46 final clean-archive verification checkpoint

- The packaged archive was extracted into a new temporary directory; all **24/24 SHA-256 manifest entries** passed before tests.
- Final clean-extraction suite: **233 passed**; one expected warning is emitted while creating a duplicate ZIP member in the adversarial packaging test.
- Both Draft 2020-12 schemas passed self-validation; all five JSON fixtures parsed; Python compilation passed.
- ZIP CRC verification passed with **25 sorted, unique members**; two independent package builds were byte-identical in this Python/zlib environment.
- No actual TTS inference was run. The external discovery ledger and delivery note record the final ZIP SHA-256.

**D0-46 final result: PASS for tested model-free lifecycle and I/O boundary cases.** This does not prove process-tree cancellation, OS isolation, cross-platform race behavior, or production readiness.

## D0-47 — Process-tree cancellation capability gate

**Date:** 2026-10-04  
**Status:** PASS for the tested POSIX process-group lifecycle cases; Windows behavior remains unverified.

### Changes

- POSIX worker launches now use `start_new_session=True`, isolating the worker and ordinary descendants into a dedicated process group.
- Timeout, cancellation, output overflow, wait fallback, and stuck pipe-reader cleanup now terminate the process group with SIGTERM followed by SIGKILL after a short grace period.
- If the direct worker exits while a descendant retains inherited stdout/stderr descriptors, the supervisor detects readers that do not close, terminates the remaining process group, and joins the reader threads again.
- Windows uses a best-effort `taskkill /T /F` request and falls back to direct-child termination. No Windows runner was available, so Windows semantics remain an explicit capability gate rather than a verified claim.
- Added POSIX regression tests for timeout with a grandchild holding inherited pipes and direct-worker exit while a grandchild keeps pipes open.

### Limitations

- This is process-group lifecycle cleanup, not a security sandbox. Descendants that deliberately escape the process group/session may survive.
- Windows tree termination has not been tested in Windows CI. CPU, memory, filesystem, and network isolation are not implemented.
- No actual TTS model or external agent runtime was invoked.

### D0-47 final local verification checkpoint

- Source-tree full suite: **235 passed in 13.74s**; one expected warning is emitted by the adversarial duplicate-ZIP-member fixture.
- `py_compile` passed for source modules and test modules.
- Deterministic packaging check passed: two independent builds had identical SHA-256 values; archive CRC and extracted manifest verification passed.
- Clean extraction and full-suite rerun are required on the final rebuilt archive before release.

- Final archive clean-extraction full suite: **235 passed in 13.50s**; one expected duplicate-ZIP-member warning.
- Fresh extraction verified all **24/24** manifest entries, both JSON schemas, all five JSON fixtures, Python compilation, ZIP CRC, 25 unique regular-file members, and absence of cache/bytecode/temp artifacts.
- Final verification was performed on a clean extraction, independent of the source working tree.


## D0-48 — Worker descendant escape and cleanup policy review

- Scope: characterize, rather than overclaim, POSIX process-group behavior when a descendant deliberately calls `setsid()` and retains inherited stdout/stderr descriptors.
- Added a POSIX-only adversarial regression that launches an escaped grandchild, confirms the supervisor raises `WORKER_IO_THREAD_STUCK` after bounded cleanup cannot close the inherited pipes, and explicitly kills the grandchild in the test's `finally` block.
- Decision: `WORKER_IO_THREAD_STUCK` means the supervisor could not prove I/O cleanup; it does **not** mean the escaped descendant was terminated. Process-group cancellation is lifecycle management, not a security sandbox.
- Documented deployment requirements for hostile-code containment: platform-native controls (for example Linux cgroups/containers or Windows Job Objects) and target-platform-specific tests. These controls are recommendations only and are not implemented by this harness.
- Windows remains unverified. No actual TTS engine or agent runtime is invoked.

### D0-48 implementation verification

- Focused POSIX escape regression: **1 passed**; it observed the expected `WORKER_IO_THREAD_STUCK` outcome and killed the escaped grandchild in test cleanup.
- Source-tree full suite: **236 passed in 17.07s**; one expected warning from the adversarial duplicate-ZIP-member fixture.
- This result characterizes the current Linux/POSIX behavior only. It does not prove containment of untrusted code, Windows behavior, or actual TTS functionality.

### D0-48 final clean-archive verification

- Fresh extraction of the package: **236 passed in 16.89s**; one expected warning from the duplicate-ZIP-member adversarial fixture.
- SHA-256 manifest: **24/24 PASS**; ZIP CRC PASS; 25 sorted unique regular-file members; cache/bytecode/temp artifacts absent.
- Draft 2020-12 schema self-checks: **2/2 PASS**; JSON fixtures: **5/5 PASS**; Python compilation PASS.
- Deterministic packaging check: two independent builds byte-identical in the current Python/zlib environment.
- D0-48 final result: **PASS for Linux/POSIX escape characterization only**. The escaped descendant is intentionally killed by test cleanup; `WORKER_IO_THREAD_STUCK` is not proof of containment.

## D0-49 — OS Isolation Capability Contract & Deployment Acceptance Matrix

**Status: PASS for documentation/acceptance-matrix checks only; phase remains OPEN / HOLD.**

- Added `OS_ISOLATION_CAPABILITY_CONTRACT.md` defining provider reporting, launch/terminate/wait/inspect/cleanup semantics, fail-closed startup, minimum controls, deployment gates, and explicit platform-specific acceptance criteria.
- Matrix covers Linux cgroup v2/container policy, Windows Job Objects plus restricted identity/policy, macOS candidate isolation, current POSIX process-group behavior, and the unverified Windows `taskkill` fallback.
- Added documentation regression tests that assert the design-only status, platform coverage, fail-closed semantics, cleanup evidence, and no premature sandbox-support claims.
- No OS isolation provider was implemented or run. CPU/RAM enforcement, network denial, filesystem containment, process escape prevention, Windows behavior, and macOS behavior remain NOT IMPLEMENTED / NOT RUN.
- Acceptance requires the exact target OS image and provider to pass adversarial child/grandchild, resource exhaustion, filesystem escape, network-denial, cleanup, and supervisor-crash tests before a deployment may claim isolated-worker support.
- No model weights, external network, credentials, or TTS inference were used.

### D0-49 final clean-archive verification

- Source-tree full suite: **240 passed**; one expected warning is emitted when the adversarial duplicate-ZIP-member test deliberately creates a duplicate entry.
- Fresh-extraction suite: **240 passed**; SHA-256 manifest verification passed for **26/26** entries before tests.
- Python compilation passed for source and test modules; both Draft 2020-12 schemas self-validated and the JSON fixture parsed.
- Deterministic package check passed: two independent builds were byte-identical. Archive CRC and extracted manifest verification passed.
- Platform isolation tests were not run; this task validates documentation contracts only and does not implement or certify OS containment.

## D0-50 — Platform-neutral isolation provider interface

**Status:** PASS for interface/contract negotiation and model-free tests only. Phase 0 remains OPEN / HOLD.

- Added `isolation_provider.py` with typed capability report, production-required capability set, explicit isolation policy, opaque job handle, inspection/wait result structures, runtime-checkable provider protocol, and fail-closed negotiation.
- Capability negotiation blocks target-platform mismatch, unverified provider, missing evidence references, unknown/false required capabilities, and missing network-policy capability. It does not verify evidence provenance or implement a sandbox.
- Worker environment secrets are prohibited by the contract. Provider implementations and production evidence attestation remain future work.
- Added regression tests for capability success, unknown/false capability rejection, target mismatch, unverified/missing-evidence rejection, malformed metadata, secret policy rejection, and lifecycle data invariants.
- Full source-tree suite: **257 passed** with one expected warning from the duplicate-ZIP-member adversarial test. Clean-archive test results are recorded after packaging below.
- No OS isolation provider, model weights, external TTS inference, or AI-agent runtime was installed or invoked.

### D0-50 clean-archive verification

- Fresh extraction of the generated ZIP: **257 passed in 17.76s**; one expected warning from the adversarial duplicate-ZIP-member test.
- SHA-256 manifest: **28/28 PASS**; archive had 29 unique regular-file members; CRC PASS; cache/bytecode/temp artifacts absent.
- Python compilation PASS; JSON schemas **2/2 PASS**; included JSON fixtures parsed successfully.
- Two deterministic package builds were byte-for-byte identical in the current Python/zlib environment.
- This verifies contract code and test packaging only. It does not verify a real isolation provider, OS sandbox, model inference, or target-agent integration.
- Final rebuilt ZIP after this report update: **257 passed in 17.91s** from fresh extraction; manifest **28/28 PASS**, ZIP CRC PASS, 29 unique members, schemas **2/2 PASS**, fixtures parsed, compilation PASS, and no cache/temp artifacts. Two builds matched byte-for-byte.

## D0-51 — provider conformance suite and machine-readable evidence

**Scope:** model-free interface conformance and evidence serialization only; no OS isolation provider or TTS engine was implemented.

- Added `provider_conformance.py` with capability-gate evaluation, trusted-probe input validation, launch/wait/inspect/terminate/cleanup exercise, explicit containment/exit checks, and stable-key JSON serialization.
- Added `schemas/provider-conformance-evidence-v1.schema.json` (Draft 2020-12) with strict top-level/nested properties and enumerated check/outcome states.
- Added tests for valid evidence-schema output, fail-closed unverified provider, non-zero probe exit, incomplete containment, cleanup exceptions, timeout/termination path, malformed probe inputs, and JSON round-trip/key ordering.
- Evidence is diagnostic, not signed or cryptographically attested. A structurally valid report does not establish evidence provenance, effective OS controls, hostile-code containment, or production support. Tests use a fake provider and must not be described as a sandbox test.
- First run exposed a malformed closing brace in the new JSON Schema; corrected it before the passing run. Final source-tree suite: **268 passed** with one expected duplicate-ZIP-member warning.

### D0-51 final clean-archive checkpoint

- The generated archive was extracted to a new temporary directory and tested independently of the source tree: **268 passed in 16.92s**; one expected warning from the duplicate-ZIP-member adversarial test.
- All **31/31** SHA-256 manifest entries verified by the packaging script; archive contains 32 unique members including the manifest, ZIP CRC PASS, no cache/bytecode/temp entries.
- Draft 2020-12 schema self-checks: **3/3 PASS** (two synthesis schemas plus provider-conformance evidence schema); JSON fixtures parsed; Python compilation PASS.
- Two deterministic builds matched byte-for-byte in the current Python/zlib environment. This does not establish cross-platform reproducibility.
- D0-51 result: **PASS for model-free provider-conformance contracts and evidence serialization only**. No real provider or OS isolation was tested. Phase 0 remains **OPEN / HOLD**.

## D0-52 — Evidence Record Semantic Consistency & Tamper-Resistance Audit

- Scope: model-free evidence payload consistency, duplicate-key JSON parsing, canonical digest and externally anchored digest comparison.
- Implementation: semantic validator checks unique `check_id` values, top-level/capability-report metadata agreement, gate reason/status consistency, fail-closed launch claims, and overall status against individual check statuses.
- Parser rejects duplicate JSON object keys at any nesting level and non-standard JSON constants.
- Canonical SHA-256 helper hashes stable JSON bytes. Digest comparison detects edits only if the expected digest is separately trusted; it does not authenticate who created the evidence and is not a digital signature.
- Added regressions for duplicate check IDs, false PASS claims, denied-gate contradictions, provider metadata mismatch, tampered payload digest, duplicate JSON keys, and semantic JSON parsing.
- Verification: `python -m pytest -q` — **274 passed** in 16.21 seconds; one expected warning from the duplicate-ZIP-member adversarial packaging test.
- No real isolation provider, OS sandbox, TTS model, network download, or target-agent runtime was used.
- Acceptance: PASS for model-free semantic validation and digest tamper-detection tests only. Signed attestations, trusted timestamping, key management, and real-provider evidence provenance remain NOT IMPLEMENTED.
- Phase 0 remains **OPEN / HOLD**.

### D0-52 final clean-archive checkpoint

- Final archive was extracted to a new temporary directory; full suite: **274 passed in 16.38s** with one expected duplicate-ZIP-member warning.
- SHA-256 manifest: **31/31 PASS**; ZIP contains **32 unique members**, CRC PASS, no cache/bytecode/temp entries.
- JSON Schema self-check: **3/3 PASS**; all **5 fixture JSON files** parse successfully; Python compilation PASS.
- Two independent reproducibility builds were byte-for-byte identical in the current Python/zlib environment.
- Result is limited to model-free evidence semantics and packaging verification. No signed attestation, real OS isolation, TTS inference, or target-agent integration was verified.


## D0-53 — Evidence Provenance Envelope & Trust-Boundary Design

- **Status:** PASS for model-free envelope schema and trust-boundary semantic tests only; Phase 0 remains OPEN / HOLD.
- Added `evidence_provenance.py` and `schemas/evidence-provenance-envelope-v1.schema.json`. The envelope records evidence ID/digest, source tool/version/invocation, provider identity claim basis, test environment and timestamps, artifact paths and SHA-256 hashes, trust level, verification state, limitations, and optional signature metadata.
- Semantic checks reject invalid timezone-aware timestamps, reversed test intervals, malformed digests, unsafe or duplicate artifact paths, unsupported trust states, self-asserted elevated trust without a separately supplied verifier boundary, contradictory signature claims, and secret/private-key fields.
- Added tests for schema and semantic acceptance, trust-boundary elevation, signature consistency, timestamps, hashes, paths, and secret material.
- Test command: `python -m pytest -q`; **285 passed** in 17.33 seconds; one expected duplicate-ZIP-member warning from the existing adversarial packaging test.
- No cryptographic signing, trusted timestamping, key management, real provider, OS sandbox, TTS inference, or target-agent integration was implemented or tested. `verifier_evidence=True` is a trust-boundary parameter for a future trusted caller; it is not itself proof.
- Acceptance: envelope schema and semantic checks PASS; authenticity/signature/key lifecycle NOT IMPLEMENTED; Phase 0 OPEN / HOLD.

### D0-53 final clean-archive checkpoint

- Fresh extraction: **285 passed**, with one expected duplicate-ZIP-member warning.
- Manifest **34/34 PASS**; archive **35 unique members**, CRC PASS, zero cache/bytecode/temp entries.
- JSON Schema self-check **4/4 PASS**; all **5 fixture JSON files** parse; Python compilation **19 files PASS**.
- Reproducible build check passed twice with identical ZIP hashes. No signature implementation, trusted timestamping, real provider, OS sandbox, TTS inference, or target-agent integration was tested.

## D0-54 — Provenance Envelope Mutation, Adversarial Parsing & Schema/Semantic Parity Audit

- **Status:** PASS for model-free adversarial parsing and schema/semantic rejection parity; Phase 0 remains OPEN / HOLD.
- Public semantic validation now validates the envelope against the published Draft 2020-12 schema first, rejecting schema-invalid fields/objects and failing closed if schema validation cannot run. Additional semantic rules are intentionally stricter than schema shape for trust elevation, safe relative artifact paths, and timestamp ordering by actual timezone-aware instants rather than lexicographic strings.
- Added `parse_provenance_json()` with a 1 MiB default input cap, strict UTF-8, duplicate-key rejection at every nesting level, non-standard constant rejection, object-root enforcement, and fail-closed handling for malformed or excessively nested JSON.
- Added adversarial mutations for missing/unknown/nested fields, malformed enum types, traversal/drive/backslash/NUL paths, elevated self-claims, timezone offsets, duplicate nested keys, non-finite constants, non-object roots, oversized and invalid-UTF-8 input, recursive Python structures, and non-JSON canonicalization values.
- Targeted tests: **24 passed**. Full source-tree suite: **298 passed** in 16.60 seconds; one expected duplicate-ZIP-member warning from the existing adversarial packaging test.
- Acceptance is limited to local model-free schema/parser/semantic behavior. This does not prove authenticity, safe OS isolation, real provider provenance, TTS inference, or target-agent compatibility. Phase 0 remains **OPEN / HOLD**.

### D0-54 final clean-archive checkpoint

- Source-tree full suite: **298 passed in 18.04s**; final fresh-archive suite: **298 passed in 17.11s**, with one expected duplicate-ZIP-member warning from the adversarial packaging test.
- Manifest **34/34 PASS**; archive **35 unique members**, CRC PASS, zero cache/bytecode/temp entries.
- JSON Schema self-check **4/4 PASS**; fixture JSON under `tests/fixtures` **1/1 parsed**; Python compilation **20 files PASS**.
- Two deterministic builds were byte-identical in the current Python/zlib environment. The final ZIP SHA-256 is recorded in the external discovery ledger; the archive does not self-embed its own digest.
- D0-54 acceptance limited to local model-free parsing/schema/semantic behavior. Phase 0 remains **OPEN / HOLD**; no signed evidence, real provider, OS sandbox, TTS inference, or target-agent integration verified.

## D0-55 — Provenance Evidence Bundle Cross-File Hash Binding & Reproducible Verification Plan

- **Status:** PASS for model-free bundle inventory, cross-file digest consistency, and local tamper detection only; Phase 0 remains OPEN / HOLD.
- Added `evidence_bundle.py` and `schemas/evidence-bundle-manifest-v1.schema.json`. The manifest hashes every regular file including the provenance envelope, while the envelope artifact list describes payload files excluding the envelope and manifest to avoid circular hashing.
- The verifier checks schema, safe/unique relative paths, duplicate JSON keys, exact inventory (no missing or unlisted files), symlink rejection, byte size and SHA-256, manifest-to-envelope digest binding, and exact envelope-to-payload artifact hash binding.
- Documented a reproducible process for bundle assembly, transfer, independent manifest-digest comparison, extraction, and repeat verification. A self-consistent manifest is not authenticated if an attacker can rewrite both the payload and manifest.
- Targeted tests: 6 passed. Full suite result is recorded below after final clean-extract verification.
- No digital signature, external trust root, trusted timestamp, real provider provenance, OS sandbox, TTS inference, or target-agent integration was implemented or tested.

### D0-55 final clean-archive checkpoint

- Source-tree suite: **304 passed in 16.79s**; fresh-extract suite: **304 passed in 16.68s**. One expected warning from the existing duplicate-ZIP-member adversarial packaging test.
- Manifest **37/37 PASS**; archive **38 unique members**, CRC PASS, zero cache/bytecode/temp entries.
- JSON Schema self-check target includes **5 schema files**; **5 JSON fixtures** found. Python compilation passed before packaging.
- Two deterministic builds were byte-identical in the current Python/zlib environment. Final ZIP SHA-256: `031772561b6f04f1a43d56143124fd4bf5ae59df13efbe6f4d29dd8007eda6c6`.
- Result is limited to local model-free cross-file integrity and tamper detection. Manifest remains unsigned; no real provider, OS sandbox, TTS inference, signature/key lifecycle, or target-agent integration was tested. Phase 0 remains **OPEN / HOLD**.


## D0-57 — Audit Report Diagnostic Classification & Stable Error Codes

**Date:** 2026-10-04  
**Status:** IMPLEMENTED; verification pending until the final clean-extract run below.

### Implementation

- Added `audit_diagnostics.py` with stable, documented diagnostic codes, categories, severity, user-facing message, remediation, and retained raw verifier message.
- Changed the audit report's `errors` array from strings to closed structured objects and updated the report JSON Schema.
- Added deterministic classification tests for known failures, unknown-error fail-closed fallback, and preservation of order/cardinality.
- CLI consumers should branch on `code`; prose is explanatory and may evolve. Existing codes must never be reused or renumbered.

## D0-58 — Audit Diagnostic Coverage Matrix & Golden Regression Corpus

- **Scope:** make every configured verifier-message prefix traceable to a stable code and protect structured classifications with a versioned golden corpus.
- **Implementation:** added `AUDIT_DIAGNOSTIC_COVERAGE_MATRIX.md`, `tests/fixtures/audit-diagnostics-v1.json` (22 cases spanning all configured prefix needles and the unknown fallback), and golden tests for complete output stability, code uniqueness, corpus coverage, matrix completeness, and fail-closed fallback behavior.
- **Focused verification:** `python -m pytest -q tests/test_audit_diagnostics.py tests/test_audit_diagnostic_golden_corpus.py tests/test_evidence_bundle_cli.py` — 13 passed.
- **Acceptance limit:** the matrix covers all currently configured matcher needles, not every possible future verifier string. New observed conditions still require deliberate triage. Phase 0 remains OPEN / HOLD; no authenticity, production sandbox, real provider, TTS inference, or target-agent integration is established.
- **Final full-suite, clean-extract, manifest, and reproducible-build evidence:** see the D0-58 final checkpoint in the discovery ledger.

### D0-58 final clean-archive checkpoint

- Source-tree full suite: **317 passed in 24.23s**; exact final ZIP fresh-extract suite: **317 passed in 24.46s**. One expected warning is emitted by the adversarial duplicate-ZIP-member test.
- Golden diagnostic corpus: **22 cases** covering every configured matcher prefix and fallback.
- Schemas **6/6 PASS**; JSON fixtures **6/6 parse**; Python compilation **27 files PASS**.
- Final archive before this report update: **45/45 manifest entries**, **46 unique ZIP members**, CRC PASS, no cache/temporary members; two reproducibility builds matched byte-for-byte.
- The report and external ledger are updated after this run; the final ZIP is rebuilt and rechecked afterward so the packaged report matches the final evidence.
- Phase 0 remains **OPEN / HOLD**. No signatures/trust roots, real provider, OS sandbox, real TTS inference, or target-agent integration are established.
- **Final packaged report refresh:** after the evidence-report update, the rebuilt archive was extracted again and its own manifest verified; final extracted-suite result **317 passed in 24.54s**. Final archive has **46 unique members**, **45 manifest entries**, **6/6 schemas**, **6/6 JSON fixtures**, and **27 Python files compile**; CRC PASS and no cache/temp members. The authoritative final archive hash is recorded in the external discovery ledger.


## D0-59 — Diagnostic Rule Precedence & Overlap/Shadowing Analysis

- Added a cross-code literal-substring shadowing guard for configured matcher needles.
- Added pairwise synthetic combined-message probes for all ordered rule pairs; tests confirm first-match precedence is deterministic.
- Documented the precedence contract, current no-collision finding, and future overlap policy in `AUDIT_DIAGNOSTIC_COVERAGE_MATRIX.md` and README.
- Source-tree full suite: **319 passed in 24.47s**, with one expected warning from the adversarial duplicate-ZIP-member test. Clean-extract and reproducible-build results are recorded after final packaging.

### D0-59 final clean-archive checkpoint

- Source-tree suite: **319 passed in 24.47s**; first final-package fresh-extract suite: **319 passed in 25.54s**. One expected warning is produced by the adversarial duplicate-ZIP-member test.
- Current archive: **45/45 manifest entries verified**, **46 unique ZIP members**, CRC PASS; **6/6 schemas** and **2/2 JSON fixtures under `tests/fixtures`** parse; **27 Python files** compile; no cache/temp members.
- Two deterministic builds matched byte-for-byte after the report update. The authoritative final package SHA-256 is recorded in the D0-59 final ledger checkpoint; the exact final archive was freshly extracted and retested.
- Precedence test covers all ordered pairs of distinct configured rules; current cross-code literal-substring shadowing count is zero.
- Phase 0 remains **OPEN / HOLD**. No signature/trust root, real provider, OS sandbox, real TTS inference, or target-agent integration is established.

- Final exact-archive fresh-extract run after report refresh: **319 passed** (elapsed time varies by execution environment). The authoritative final archive SHA-256 is recorded in the external development ledger because an archive cannot contain its own final hash without changing that hash.

## D0-60 — CLI Exit Codes, Report Status & Error-Count Consistency

- **Scope:** model-free audit CLI result semantics and structured report consistency.
- Added `report_exit_code()` as a fail-closed contract check: exit `0` requires `PASS` plus zero errors; exit `1` requires `FAIL` plus one or more errors; mismatched status/count/list cardinality is rejected.
- `make_report()` now derives status and error count from the exact classified diagnostics and no longer accepts a status override that could produce contradictory reports.
- CLI operational failures use exit `2`, stderr, and no JSON success report; tested argument-usage failure and report-file write failure.
- Regression tests validate schema-compatible PASS and multi-error FAIL reports, exact `error_count == len(errors)`, invalid drift cases, and exit-code behavior.
- Scope remains model-free. The CLI's `ERROR` schema enum is reserved for future use and is not emitted by this CLI version.
- Final test/build/extraction evidence is recorded in the D0-60 ledger checkpoint after packaging.

### D0-60 final extracted-package checkpoint

- Fresh extraction of the built ZIP: `python -m pytest -q` — **323 passed in 28.46s**, one expected warning from the adversarial duplicate-ZIP-member test.
- Archive SHA-256 at this checkpoint: `f3bd9dfb0253df6cffdfba8ddf60a3b8b08c491903ea8f9bdf698b2107a4b3fc`; **46 unique ZIP members**, CRC PASS, **45/45** SHA256SUMS entries verified.
- **6/6** JSON schemas and **2/2** JSON test fixtures parsed; **27 Python files** compiled to an external temporary directory; archive cache/temporary-file scan PASS.
- Reproducible package build produced byte-identical archives. This is local contract-harness evidence only, not a claim of real TTS inference or target-agent compatibility.

## D0-61 — Audit Report Consumer Contract & Versioned Compatibility Tests

- Added `AUDIT_REPORT_CONSUMER_COMPATIBILITY.md` defining schema-version gating, code-based branching, unknown-code behavior, additive diagnostic policy, breaking-change policy, and handling of CLI operational failures.
- Added `audit_report_consumer.py`, a reference consumer that explicitly accepts schema `1.0`, validates the complete report against the closed JSON Schema, and groups errors by stable diagnostic code.
- Added `tests/fixtures/audit-report-consumer-v1.json` and six compatibility regression tests covering valid v1 reports, missing/unknown versions, malformed object/schema drift, prose-independent code branching, duplicate diagnostic preservation, and additive unknown codes.
- Focused consumer + CLI tests: **16 passed**.
- Source-tree full suite: **329 passed in 29.28s**, with one expected warning from the adversarial duplicate-ZIP-member test.
- Scope is reference-consumer contract verification only; no external target agent or production consumer has been integrated.

### D0-61 final clean-archive checkpoint

- Final archive was freshly extracted and tested: `python -m pytest -q` — **329 passed in 30.51s**, with one expected warning from the adversarial duplicate-ZIP-member test.
- Deterministic build check: two byte-identical archives. The authoritative final ZIP SHA-256 is recorded in the external discovery ledger because an archive cannot include its own final hash without changing that hash.
- Archive integrity: **50 unique ZIP members**, **49/49** SHA256SUMS entries verified, CRC PASS, and no cache/temp entries.
- Parsed **6/6 schemas** and **3/3 JSON fixtures**; compiled **29 Python files** successfully.
- This establishes local consumer-contract behavior only. External target-agent integration and all real TTS inference remain unverified.


## D0-62 — Audit Consumer Error Handling, Malformed JSON & Resource Boundaries

- Added a bounded parsing entry point for untrusted report bytes/text: strict UTF-8, malformed/truncated JSON rejection, duplicate-key rejection, and top-level object requirement.
- Added configurable module constants for a 5 MiB serialized input ceiling and a 10,000-diagnostic ceiling; both are checked before full schema validation. The direct already-parsed-object validator enforces the diagnostic ceiling but cannot enforce raw serialized byte size.
- Schema load/parse/validation setup failures now fail closed with a generic consumer-facing contract error.
- Added regression tests for malformed/truncated payloads, invalid UTF-8, non-object roots, duplicate keys, exact and over-limit boundaries, and missing schema files.
- Focused consumer tests: **22 passed**. Source-tree full suite: **345 passed in 28.51s**, with one expected warning from the adversarial duplicate-ZIP-member packaging test.
- Reproducible package build matched byte-for-byte. Final exact-archive clean extraction: **345 passed in 28.41s**, one expected duplicate-member warning; **51 unique ZIP members**, **50/50** manifest entries, ZIP CRC PASS, **6/6** schemas parsed, **7/7** JSON fixtures parsed, **30** Python files compiled, and zero cache/temp archive members.
- These are local reference-consumer tests only; no external target-agent integration or real TTS inference is implied. Phase 0 remains **OPEN / HOLD**.

## D0-63 — Audit Consumer Deep-Nesting, Non-Finite Tokens & Parser Hardening

- Added a non-recursive JSON nesting pre-scan with a default maximum of **100** nested object/array containers, rejecting deeply nested input before recursive parsing.
- Configured the JSON parser to reject Python-specific `NaN`, `Infinity`, and `-Infinity` tokens; these are not valid JSON numeric literals.
- Added adversarial regression cases for all non-finite tokens, exact/over nesting boundaries, deeply nested input, and bracket/escape characters inside strings.
- Updated the compatibility contract and README to document the nesting and numeric-token policy.
- Focused consumer tests: **28 passed**. Source-tree full suite: **351 passed in 28.73s**, with one expected warning from the duplicate-ZIP-member packaging test.
- Final clean-extract, manifest, schema/fixture, compilation, cache/temp, and reproducible-build checks are recorded in the D0-63 final checkpoint in the external discovery ledger.
- Scope is parser hardening in the local model-free reference consumer. No production agent integration, TTS inference, or OS sandbox is implied; Phase 0 remains **OPEN / HOLD**.

### D0-63 final clean-archive checkpoint

- Exact final ZIP freshly extracted and tested with `python -m pytest -q`: **351 passed in 27.70s**, one expected warning from the adversarial duplicate-ZIP-member packaging test.
- Two deterministic package builds matched byte-for-byte; archive SHA-256 is recorded in the external discovery ledger.
- **51 unique ZIP members**, **50/50** SHA256SUMS entries verified, ZIP CRC PASS, no cache/temporary members.
- **6/6** JSON schemas parsed, **7/7** JSON test fixtures parsed, Python compilation PASS.
- This confirms local model-free parser hardening only. Phase 0 remains **OPEN / HOLD**; real TTS inference, production sandbox and target-agent integration remain unverified.


## D0-64 — Audit Consumer Schema Validation Cost, Diagnostic Explosion & Failure-Path Stability

- Added `MAX_SCHEMA_VALIDATION_ERRORS = 100`; the consumer consumes at most 101 schema errors and fails closed if the cap is crossed, avoiding materializing and sorting an unbounded iterator.
- Preserved generic stable failure text for unreadable, malformed, or invalid schema setup and ensured schema-error-cap failure remains a specific contract error.
- Added adversarial tests proving validator iteration stops at cap + 1, schema failure messages do not expose paths, and unsupported versions fail before schema I/O.
- This bounds schema-error amplification, not all possible CPU/memory costs; process-level isolation and real TTS/agent integration remain unverified.

### D0-64 final clean-archive checkpoint

- Exact final ZIP freshly extracted and tested with `python -m pytest -q`: **355 passed**; one expected warning from the adversarial duplicate-ZIP-member packaging test.
- Two deterministic package builds matched byte-for-byte; the authoritative final ZIP SHA-256 is recorded in the external discovery ledger.
- **52 unique ZIP members**, **51/51** SHA256SUMS entries verified, ZIP CRC PASS, no cache/temp members in the archive.
- **6/6** JSON schemas and **3/3** JSON fixtures parsed; **31** Python files compiled.
- D0-64 PASS for bounded schema-error iteration and stable local failure paths only. Phase 0 remains **OPEN / HOLD**; real TTS inference, target-agent integration, cryptographic authenticity, and production OS sandbox remain unverified.

## D0-65 — Consumer Contract Mutation Matrix & Stable Error Taxonomy

- Added `AuditReportErrorCode` and stable `AuditReportContractError.code` categories for invalid input, unsupported versions, malformed JSON, invalid UTF-8, duplicate keys, non-finite numbers, nesting/size/diagnostic limits, schema-load failures, schema-error amplification, and schema violations.
- Kept human-readable messages separate from machine-readable categories; `UnsupportedAuditReportVersion` maps to `AUDIT_REPORT_UNSUPPORTED_VERSION`.
- Added `tests/test_audit_report_consumer_taxonomy.py` with parser failure cases, resource-limit classifications, unsupported-version behavior, schema load/error-cap distinctions, and a mutation matrix for closed-schema and field-type constraints.
- Documented the error taxonomy and consumer compatibility rules in `AUDIT_REPORT_CONSUMER_COMPATIBILITY.md` and README.
- Scope: local reference consumer contract only. Stable error codes do not constitute target-agent integration or real TTS verification; Phase 0 remains OPEN / HOLD.

### D0-65 final clean-archive checkpoint

- Exact package fresh extraction: `python -m pytest -q` — **370 passed (runtime varies by environment)**, with one expected warning from the adversarial duplicate-ZIP-member packaging test.
- Two deterministic package builds matched byte-for-byte; authoritative final archive SHA-256 is recorded in the external discovery ledger.
- **53 unique ZIP members**, **52/52** manifest entries verified, ZIP CRC PASS, no cache/temp archive members.
- **6/6** JSON schemas parsed, **3/3** JSON fixtures parsed, **32** Python files compiled.
- D0-65 PASS for local consumer schema mutation coverage and stable machine-readable error taxonomy only. Phase 0 remains **OPEN / HOLD**; real TTS inference, target-agent integration, cryptographic authenticity, and production OS sandbox remain unverified.


## D0-66 — Cross-entry contract invariants and consumer integration simulation

- Scope: audit-report count/status/check invariants and local end-to-end consumer simulation.
- Implementation: stable `AUDIT_REPORT_INVARIANT_VIOLATION` classification for cross-field inconsistencies; `consume_audit_report_json()` maps validated PASS/FAIL/ERROR to 0/1/2 and groups diagnostic entries by stable code.
- Regression coverage: PASS and FAIL workflows, unknown future diagnostic codes, count/list drift, FAIL with no `SEE_ERRORS` core check, ERROR without diagnostics, and malformed payload rejection.
- External target-agent integration remains NOT RUN; this simulation does not substitute for that gate.

### D0-66 final verification checkpoint

- Focused consumer suite: **54 passed in 1.08s**.
- Source-tree full suite: **377 passed in 28.59s**, with one expected warning from the adversarial duplicate-ZIP-member test.
- Final package verification is performed from a clean extraction; authoritative ZIP hash and exact package counts are recorded in the external discovery ledger to avoid self-reference.
- Acceptance remains local model-free integration simulation only; Phase 0 remains **OPEN / HOLD**.


## D0-67 — CLI-to-consumer end-to-end contract and exit-status reconciliation

- Added `scripts/consume_audit_report.py`, a runnable bounded consumer CLI supporting stdin or report-file input.
- The consumer CLI delegates to the shared strict parser, schema/version validator, cross-entry invariant checks, and stable diagnostic grouping. It emits normalized JSON only after validation succeeds.
- Public exit contract: `0` = validated PASS; `1` = validated FAIL; `2` = invalid/unconsumable report or CLI/input I/O failure. Invalid reports emit stable error codes to stderr and no normalized JSON to stdout.
- Added `tests/test_z_cli_consumer_e2e.py` with real subprocess integration: verifier PASS→consumer PASS; verifier FAIL→consumer FAIL; status/exit/count reconciliation; stdin/file parity; malformed JSON fail-closed behavior; usage failure; and path-safe missing-file handling.
- Scope is local process-level CLI integration only; no external target-agent or TTS-engine integration is established by this task.
- Exact final test counts, ZIP SHA-256, manifest/CRC results, schema/fixture parse results, compilation count, and fresh-extract verification are recorded in the external `VOICEOVER_SKILL_DISCOVERY_LEDGER.md` to avoid archive self-reference.

## D0-68 — CLI error-path matrix, output atomicity, and stream/path parity

- Hardened verifier report destination handling: canonicalize the parent directory for containment checks without dereferencing the final destination component; parent-directory symlinks cannot bypass the outside-bundle rule.
- Extracted `_write_report_atomically()` to stage output in a unique same-directory temporary file, flush and `fsync` it, then atomically replace the destination. Failed replacement preserves the previous report and cleans temporary artifacts.
- Added `tests/test_d0_68_cli_output_atomicity.py` for successful replacement, simulated `os.replace` failure, temp cleanup, symlink destination semantics, parent-symlink containment, stdin/file error parity for malformed JSON and invalid UTF-8, directory-as-input failure, and oversized-input parity.
- Scope: local CLI/filesystem behavior. Atomic rename semantics and durability can still vary by filesystem; no claim of target-agent integration or production sandbox is implied.
- Final exact-package verification evidence and SHA-256 are recorded in the external `VOICEOVER_SKILL_DISCOVERY_LEDGER.md` to avoid archive self-reference.

### D0-68 final verification checkpoint

- Exact final ZIP was extracted to a clean directory; all collected tests were run in seven non-overlapping groups from that extraction because monolithic pytest runs exceeded the execution window in this environment.
- Group results: consumer/contract group **111 passed in 1.31s**; documentation + bundle CLI group **20 passed in 12.65s**; consumer E2E group **6 passed in 17.02s**; D0-68 atomicity/parity group **8 passed in 19.37s**; IPC/JSONL/fuzz/schema group **156 passed in 1.94s**; provenance/isolation/package/provider/runtime group **85 passed in 17.55s**; OS isolation docs **5 passed in 0.04s**. Aggregate: **391 passed**, one expected warning from the duplicate-ZIP-member adversarial packaging test.
- ZIP integrity PASS; **57 unique members**, **56/56** SHA256SUMS entries verified; **6/6** schemas and **7/7** JSON fixtures parsed; **36** Python files compiled; zero cache/temp archive members.
- Two reproducible builds matched byte-for-byte. The authoritative final archive SHA-256 is recorded in the external discovery ledger.
- D0-68 PASS for local CLI output atomicity, path containment, stable input errors, and stdin/file parity only. Phase 0 remains **OPEN / HOLD**; real TTS inference, target-agent integration, cryptographic authenticity, and production OS sandbox remain NOT IMPLEMENTED / NOT RUN.

## D0-69 — verifier report destination race and atomic-failure fault injection

- Added `tests/test_d0_69_report_race_faults.py` with deterministic injection for a final-component symlink appearing immediately before atomic replacement, a parent alias being swapped after destination canonicalization, temporary-file creation failure, staged-data write failure, `fsync` failure, and replacement failure when the destination is a directory.
- Acceptance: a destination symlink is replaced as a link entry rather than followed; an alias swap after destination resolution does not redirect output; failed staging/replacement leaves an existing report or destination directory intact and cleans any temporary stage.
- Focused suite: **6 passed**. Exact distributable package verification and complete clean-extraction test counts are recorded in the external discovery ledger to avoid archive self-reference.
- Scope remains local filesystem/CLI regression evidence. These tests do not establish resistance to every hostile filesystem race, network filesystem behavior, power loss, or platform-specific rename semantics. Phase 0 remains **OPEN / HOLD**; real TTS inference, external target-agent integration, cryptographic authenticity, and production OS sandbox remain NOT IMPLEMENTED / NOT RUN.

### D0-69 final package verification checkpoint

- Exact ZIP extracted into a new temporary directory; all tests passed in six non-overlapping groups: consumer/contract/docs **115 passed**; evidence bundle/provenance/schema **71 passed**; IPC/isolation/JSONL/fuzz/provider/runtime/docs **180 passed**; D0-68 plus D0-69 atomicity/race **14 passed**; consumer CLI E2E **6 passed**; packaging **11 passed**. Aggregate: **397 passed**; one expected warning from the duplicate-ZIP-member adversarial packaging test.
- Final ZIP: **58 members**, **57/57** SHA256SUMS entries verified, ZIP CRC PASS, **0** cache/temp members. **6/6** JSON schemas and **7/7** JSON fixtures parsed; **37** Python files compiled.
- Reproducible build check PASS; two independent archive builds matched byte-for-byte. Exact SHA-256 is recorded in the external discovery ledger.
- D0-69 PASS for deterministic local report-destination race and atomic-failure regression tests only. Phase 0 remains **OPEN / HOLD**; real TTS inference, external target-agent integration, cryptographic authenticity, and production OS sandbox remain NOT IMPLEMENTED / NOT RUN.


## D0-70 — Directory-FD anchored atomic writes and parent replacement race hardening

- On supported POSIX runtimes, report staging-file creation, replacement, and cleanup are now anchored to one open parent-directory file descriptor. Staging names are unpredictable, opened exclusively with no-follow where available, written with restrictive permissions, flushed, and fsynced before dirfd-relative replacement.
- The writer detects whether the runtime exposes the required `dir_fd` operations and replacement signature. Unsupported platforms use the existing same-directory path-based atomic-write fallback; documentation explicitly limits its parent-path race guarantees.
- Added regression coverage for renaming the actual opened parent directory and placing a symlink at its former path before temp creation, plus dirfd-relative replacement failure preserving an existing report and cleaning the stage. Existing D0-68/D0-69 atomicity and CLI behavior tests remain part of verification.
- Scope is local filesystem behavior on the tested POSIX environment. This does not establish universal hostile-filesystem race resistance, crash durability, network filesystem semantics, production sandboxing, or TTS inference.

### D0-70 final clean-archive verification checkpoint

- The exact final ZIP was freshly extracted to a clean directory. All tests passed in six non-overlapping groups: consumer/contracts/docs **115 passed**; evidence bundle/provenance/schema **71 passed**; IPC/isolation/JSONL/fuzz/provider/runtime/docs **180 passed**; D0-68/D0-69/D0-70 atomicity and race suite **17 passed**; consumer CLI E2E **6 passed**; packaging **11 passed**. Aggregate: **400 passed**. One expected warning came from the adversarial duplicate-ZIP-member packaging test. The monolithic run exceeded this environment's execution window, so no monolithic-pass claim is made.
- Archive integrity and SHA256SUMS verification passed: **58 ZIP members**, **57/57** manifest entries verified, ZIP CRC PASS, zero cache/temp archive members. **6/6** JSON schemas and **7/7** JSON fixtures parsed; **37** Python files compiled.
- Two reproducible builds matched byte-for-byte. The authoritative final ZIP SHA-256 is recorded in the external discovery ledger.
- D0-70 PASS for tested local POSIX directory-FD anchoring, parent-path replacement race regression, atomic failure cleanup, and explicit path-based fallback coverage. Phase 0 remains **OPEN / HOLD**; real TTS inference, target-agent integration, cryptographic authenticity, and production OS sandbox remain NOT IMPLEMENTED / NOT RUN.

## D0-71..D0-80 — Report-writer portability and contract regression batch

- Added `tests/test_d0_71_80_report_writer_contract.py` covering capability detection, unsupported-platform behavior, replace-signature checks, report-path containment, parent directory open flags, exclusive stage creation and restrictive mode, descriptor cleanup, fallback failure preservation, UTF-8 JSON byte preservation, empty payloads, parent-open failures, and docs/contract drift.
- Focused tests: **31 passed** across the new portability contract file plus the D0-68/D0-69 race/atomicity tests from the exact clean extraction. The 31 include 14 new D0-71..D0-80 tests and 17 prior race/atomicity tests.
- This batch is local filesystem and test-harness evidence only. It does not establish universal POSIX/Windows/network-filesystem behavior, crash durability, cryptographic authenticity, real TTS inference, target-agent integration, or production sandboxing.

### D0-71..D0-80 final exact-package verification checkpoint

- Exact distributable ZIP was freshly extracted to `/tmp/voiceover-d0-71-80-release`. All tests passed in six non-overlapping groups: contracts/audit/docs **120 passed**; evidence bundle/provenance/schema **71 passed**; IPC/isolation/JSONL/fuzz/provider/runtime **175 passed**; D0-68/D0-69/D0-71..D0-80 writer contracts **31 passed**; CLI consumer E2E **6 passed**; packaging **11 passed**. Aggregate: **414 passed**. One expected warning came from the adversarial duplicate-ZIP-member packaging test. The monolithic run was not used.
- Reproducible package construction passed with two independent builds matching byte-for-byte. The final archive SHA-256 is recorded in the external discovery ledger so the in-archive report does not embed a stale or self-referential archive hash.
- Archive contains **59 members**, with **58/58** manifest entries verified, ZIP CRC PASS, no cache/temp members, all **6/6** schemas and **7/7** JSON fixtures parsed, and all Python files compiled.
- D0-71..D0-80 PASS for the enumerated local report-writer portability and contract regressions only. Phase 0 remains **OPEN / HOLD**. Real Qwen3-TTS, Chatterbox TTS, and Kokoro inference, target-agent integration, cryptographic authenticity, and production OS sandbox remain NOT IMPLEMENTED / NOT RUN.

## D0-81..D0-90 — Directory identity and atomic-writer hardening

- Added a fail-closed check comparing the parent directory's pre-open `(st_dev, st_ino)` with the opened descriptor's `fstat()` identity. A mismatch closes the descriptor and raises before staging or replacing a report.
- Added `tests/test_d0_81_90_report_writer_hardening.py` with ten focused cases: parent inode swap, concurrent writers, POSIX restrictive mode, destination symlink target protection, staging-name collision retry, collision exhaustion, injected write failure, same-dirfd replacement arguments, directory destination preservation, and repeated payload round trips.
- Initial test run exposed three test-harness issues (fallback accidentally selected after monkeypatching capability primitives, constant collision token, and tuple indexing); those were corrected. Focused final regression group: **41 passed** across D0-68 through D0-90 writer tests.
- Scope remains local filesystem behavior on this POSIX host. This is not proof of universal race resistance, Windows or network filesystem equivalence, crash durability, cryptographic authenticity, production sandboxing, target-agent integration, or real TTS inference.

### D0-81..D0-90 final exact-package checkpoint

- Final archive was freshly extracted to `/tmp/voiceover-d0-81-90-release` and verified through non-overlapping test groups: contracts/audit/docs **115 passed**; evidence bundle/provenance/schema **71 passed**; IPC/isolation/JSONL/fuzz/provider/runtime/docs **180 passed**; D0-68/D0-69/D0-71..D0-90 writer tests **41 passed**; CLI consumer E2E **6 passed**; packaging **11 passed**. Aggregate: **424 passed**. One expected warning is emitted by the adversarial duplicate-ZIP-member packaging test.
- Reproducible package construction passed: two independent builds matched byte-for-byte. Exact archive SHA-256 is recorded in the external ledger.
- Final archive integrity: **60 ZIP members**, **59/59** SHA256SUMS entries verified, ZIP CRC PASS, no duplicate names, no cache/temp members; **6/6** JSON schemas and **7/7** JSON fixtures parsed; **39** Python files compiled.
- D0-81..D0-90 PASS for the enumerated local directory identity, atomic replacement, and fault/stress regressions only. Phase 0 remains **OPEN / HOLD**; real TTS inference, target-agent integration, cryptographic authenticity, and production OS sandbox remain NOT IMPLEMENTED / NOT RUN.

## D0-91..D0-100 — report-writer integration and boundary contracts

- Added `tests/test_d0_91_100_report_writer_contract.py` with ten regression cases covering relative destination anchoring, parent-symlink containment, missing-parent creation, private replacement mode, fsync-failure preservation/cleanup, fallback fdopen-failure cleanup, fallback symlink behavior, CLI containment rejection, stdout/file canonical report parity, and CLI error semantics.
- Focused initial test run: **10 passed**. This is only the focused source-tree run, not the final distributable-package verification.
- Acceptance is limited to tested local filesystem behavior and subprocess CLI contracts. It does not prove all-platform behavior, hostile filesystem race immunity, crash durability, cryptographic authenticity, target-agent integration, real TTS inference, or production OS sandboxing.

### D0-91..D0-100 final exact-package verification checkpoint

- Final ZIP was built reproducibly and freshly extracted to `/tmp/voiceover-d0-91-100-release-final`. Six non-overlapping test groups passed: contracts/audit/docs **120 passed**; evidence bundle/provenance/schema **61 passed**; IPC/isolation/JSONL/fuzz/provider/runtime **175 passed**; report-writer regressions D0-68..D0-100 **51 passed**; verifier/consumer CLI **16 passed**; packaging **11 passed**. Aggregate: **434 passed**. The packaging adversarial duplicate-member test emitted one expected warning; no monolithic-pass claim is made.
- Archive integrity: **61 ZIP members**, no duplicate names, ZIP CRC PASS, **60/60** SHA256SUMS entries verified, no cache/temp archive members; **6/6** schemas and **7/7** JSON fixtures parsed; **40** Python files compiled.
- Two independent reproducibility builds matched byte-for-byte. Final archive SHA-256 is recorded in the external discovery ledger.
- D0-91..D0-100 PASS for the enumerated local filesystem and CLI contract tests only. Phase 0 remains **OPEN / HOLD**; real Qwen3-TTS, Chatterbox TTS, and Kokoro inference, target-agent integration, cryptographic authenticity, and production OS sandbox remain NOT IMPLEMENTED / NOT RUN.

## D0-101..D0-130 — Model-independent voiceover orchestration

- **Scope:** validated request model, safe single-component output naming, deterministic language-aware adapter selection, bounded text chunking, WAV payload validation, same-format PCM assembly, atomic per-file output writes, and an audio integrity manifest.
- **Focused result:** `python -m pytest -q tests/test_voiceover_pipeline.py` — **30 passed**. Additional focused run with evidence-bundle CLI: **40 passed**.
- **Clean-group verification:** contracts/audit/docs **61 passed**; evidence bundle/provenance/schema **61 passed**; evidence-bundle CLI plus pipeline **40 passed**; IPC/isolation/JSONL/fuzz/provider/runtime **180 passed**; report-writer regressions **51 passed**; report-consumer/CLI integration **60 passed**; packaging **11 passed** (one expected warning from duplicate-ZIP adversarial fixture). These separately completed groups total **464 passed**. A monolithic `pytest -q` attempt exceeded the execution window at approximately 62%; therefore no monolithic-pass claim is made.
- **Important scope limit:** the new orchestration only works when the caller injects a genuine synthesis adapter. Test adapters are deterministic test fixtures, not TTS engines. No Qwen3-TTS, Chatterbox, or Kokoro model inference was run; no model download or target-agent integration was performed.
- **Known limitations:** chunk boundaries are whitespace-based; no sentence-aware linguistic segmentation, crossfading, resampling, loudness normalization, silence trimming, subtitle generation, music mixing, or cancellation/progress reporting is implemented here. WAV chunks must share PCM format. Audio and manifest are separate atomic writes rather than a two-file transaction. Provider code is trusted and not sandboxed.
- **Result:** PASS for the model-independent orchestration contract and listed local test cases only. Phase 0 remains **OPEN / HOLD** pending actual model inference, target-agent integration, cryptographic authenticity, and verified production OS isolation.

## D0-131..D0-160 — optional real-engine adapters and honest capability probe

- **Implementation:** `tts_engine_adapters.py` adds lazy Qwen3-TTS CustomVoice/VoiceDesign, Chatterbox multilingual/English, and Kokoro `KPipeline` adapters; normalized WAV serialization; format/finite-value checks; conservative language maps; explicit errors for options/modes not wired; stable adapter registry; and `probe_engines()` that never claims inference was verified. `scripts/probe_tts_engines.py` exposes the package/cache report as JSON. `OPTIONAL_TTS_ENGINES.md` documents setup and limitations.
- **Focused checks:** adapter conformance **30 passed**; model-independent orchestration **30 passed**. A Chatterbox channel-first mono tensor issue was found in the first test run and fixed; focused tests then passed.
- **Clean test groups:** contracts/audit/docs **113 passed**; evidence bundle/provenance/schema **61 passed**; evidence CLI plus pipeline plus adapter contracts **70 passed**; IPC/isolation/JSONL/fuzz/provider/runtime **175 passed** (the combined command timed out, so the six test files were rerun separately and each passed); report-writer regressions **51 passed**; report-consumer/CLI integration **13 passed**; packaging **11 passed**. Aggregate: **494 passed** across completed groups. One expected warning is emitted by the adversarial duplicate-ZIP fixture.
- **Local environment probe:** `qwen_tts`, `chatterbox`, and `kokoro` packages are all absent. The configured/default Qwen model cache was not found. Consequently **actual model inference is NOT RUN** and all probe entries explicitly set `inference_verified=false`.
- **Limitations:** upstream package APIs can change and must be pinned/verified in the target environment. Model-free fake-object tests prove adapter-boundary behavior only, not acoustic quality, model loading, GPU operation, or compatibility across package versions. Qwen voice-clone prompt configuration is intentionally blocked; engine options not wired to native controls are rejected rather than silently ignored. The adapters do not sandbox model code or authenticate model downloads.
- **Result:** PASS for the enumerated local adapter-boundary, orchestration, contract, CLI, and packaging checks. Phase 0 remains **OPEN / HOLD** pending actual Qwen3-TTS, Chatterbox, or Kokoro inference, target-agent integration, verified production OS isolation, and trusted artifact provenance.

### D0-131..D0-160 exact distributable verification checkpoint

- Rebuilt the final ZIP twice with `--check-reproducible`; both archives were byte-identical and the embedded `SHA256SUMS` manifest validated.
- Extracted the distributable ZIP into a new directory and reran the non-overlapping test groups against that fresh extraction. All **494 tests passed**: orchestration + adapters 60; contracts/audit/docs 113; evidence/provenance/schema 61; evidence-bundle CLI 10; IPC 84; isolation 16; JSONL matrix 24; protocol fuzz 17; provider conformance 17; runtime worker 17; report-writer regressions 51; report-consumer/CLI integration 13; packaging 11. Several IPC files were run separately after a combined shell invocation hit its time limit; each individual file completed successfully.
- Fresh package checks: **67 ZIP members**, CRC PASS, no duplicate member names, **66/66** SHA256SUMS entries verified, and **45 Python files** compiled. The package probe reports all three optional engine packages absent and `inference_verified=false` for every engine.
- The one packaging warning (`Duplicate name: 'payload'`) is expected from the adversarial duplicate-member rejection test.
- This checkpoint proves local tests and package integrity only. Real TTS inference remains **NOT RUN**; Phase 0 remains **OPEN / HOLD**.


## D0-161..D0-190 — readiness preflight and bounded inference runner

- Added `voiceover_preflight.py`, which checks output write access, Python/JSON runtime, optional FFmpeg, optional PyTorch device capability, and local optional engine package status. It never downloads model files or claims that package presence proves inference.
- Added `scripts/preflight_voiceover.py` for machine-readable preflight JSON; `scripts/voiceover_worker.py` for one-request/one-result worker execution; and `scripts/run_voiceover.py` for a bounded wall-clock subprocess invocation. Request-file parsing, reserved fields, invalid timeout ranges, malformed worker JSON, and timeout errors use stable structured responses. The subprocess is launched with an argument array, fixed worker path and no shell; child stderr is not echoed.
- Added `tests/test_voiceover_preflight_runner.py`, including failure injection for timeout and malformed worker output, CLI request parsing, preflight status semantics, and dependency-absent behavior.
- Focused exact-tree verification: `PYTHONPATH=. pytest -q -p no:cacheprovider tests/test_voiceover_preflight_runner.py tests/test_tts_engine_adapters.py tests/test_voiceover_pipeline.py` — **99 passed in 15.63s**.
- Local preflight output: Python 3.13.5; FFmpeg available; PyTorch detected CPU capability; `qwen_tts`, `chatterbox`, and `kokoro` packages absent; overall status `BLOCKED_DEPENDENCIES`. The package probe explicitly reports `inference_verified=false` for all three engines.
- **Important boundary:** the timeout applies to the direct worker process. This runner has not been demonstrated to kill every descendant on every OS and is not a sandbox. Model package installation, model-cache integrity, real model loading, actual audio generation, GPU inference, voice quality and target-agent integration remain NOT TESTED / BLOCKED.
- **Batch result:** PASS for the listed preflight, runner, structured-error and model-free regression contracts. Phase 0 remains **OPEN / HOLD** until at least one real engine inference is executed in a supported environment and its generated audio is decoded and inspected.


### D0-161..D0-190 exact distributable verification checkpoint

- The final source tree contains a deterministic preflight report and a bounded subprocess runner; it does not claim that optional package presence proves a model can load or synthesize audio.
- Fresh-extracted non-overlapping test groups passed **533 tests**: preflight/adapters/pipeline 99; audit/contracts/docs 120; evidence/provenance/schema 61; evidence CLI 10; IPC 84; isolation 16; JSONL E2E 24; protocol fuzz 17; provider conformance 17; runtime worker 17; report-writer regressions 51; CLI consumer E2E 6; packaging 11. A monolithic run reached approximately 67% before the execution limit; no single-run pass is claimed.
- Fresh archive validation: SHA256SUMS passed for 72 entries; ZIP CRC passed; 73 ZIP members with no duplicate names; 50 Python files compiled.
- Reproducible packaging passed with two byte-identical builds. The final archive hash is recorded in the external discovery ledger after the last documentation update.
- Local preflight status is `BLOCKED_DEPENDENCIES`: all three optional TTS engine packages are absent. No real model was downloaded or loaded; no real speech was generated. Phase 0 remains **OPEN / HOLD** pending real inference, audio inspection, target-agent integration, and production OS isolation.

## D0-191..D0-220 — PCM audio QA and real-inference acceptance gate

- Added `audio_quality.py`: versioned report; bounded uncompressed WAV parsing; mono/stereo validation; 8/16/24/32-bit PCM support; sample-rate and frame-count checks; incremental sample decoding; peak/RMS/clipping/silence metrics; all-silent, near-silent, clipping and low-RMS warnings; SHA-256 and deterministic JSON conversion.
- Added `scripts/inspect_voiceover_audio.py` and `schemas/voiceover-audio-quality-v1.schema.json`.
- Added `scripts/real_inference_smoke.py`: invokes the real worker via an argv list with a deadline; classifies missing dependencies as BLOCKED; checks output containment, WAV decode, SHA-256/size, pipeline manifest identity and metadata, duration range and duration consistency, silence ratio, clipping ratio; writes a machine-readable report atomically; prevents report/audio path collisions. Added `schemas/real-inference-smoke-report-v1.schema.json`.
- Focused regression suite includes generated WAV fixtures, PCM widths/rates/channels, invalid WAV and threshold handling, clipping/silence cases, artifact and manifest integrity, duration gates, report schema validation, CLI behavior, report collision protection, and missing-engine behavior.
- Latest focused run: `PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider tests/test_audio_quality_real_inference.py tests/test_voiceover_preflight_runner.py tests/test_tts_engine_adapters.py tests/test_voiceover_pipeline.py` — **151 passed** before the final manifest-consistency additions. The audio QA test file after those additions independently passed **52 tests**; the combined focused group must be rerun for the final count.
- Actual local smoke attempt: **BLOCKED**, exit code 3, `NO_COMPATIBLE_ENGINE`. The local probe confirms `qwen_tts`, `chatterbox`, and `kokoro` packages are all absent; no real speech was generated. No actual inference PASS is claimed. Phase 0 remains **OPEN / HOLD**.

- Full suite was run as non-overlapping groups because a combined invocation exceeded the execution window: all 585 tests passed across the listed groups. One packaging test intentionally creates a duplicate ZIP member and emitted Python's expected duplicate-name warning; the test itself passed.

### Fresh-extracted release verification

- Final candidate extracted to a new directory; 80 ZIP members, no duplicate paths, ZIP CRC PASS, 79/79 manifest entries verified, 54 Python files compiled, both new JSON schemas structurally valid.
- All 585 tests passed from the fresh extraction in non-overlapping groups: 151 audio/preflight/adapters/pipeline; 120 audit/contracts/docs; 61 evidence/schema; 10 evidence CLI; 84 IPC; 30 JSONL/consumer E2E; 67 isolation/protocol/provider/runtime; 62 report-writer/packaging. The packaging suite emitted one expected warning while deliberately creating a duplicate ZIP entry to test rejection.
- Reproducibility check passed: two built archives were byte-identical.
- Real inference smoke is still BLOCKED with `NO_COMPATIBLE_ENGINE`; all three optional packages are absent, no generated speech was produced, and `inference_verified=false`.


## D0-221–D0-250 — TTS environment readiness diagnostics

Added `tts_environment.py`, `scripts/diagnose_tts_environment.py`, `schemas/tts-environment-diagnostic-v1.schema.json`, and `tests/test_tts_environment.py`. The diagnostic is read-only: it reports Python/platform, PyTorch device visibility, installed/missing distribution prerequisites for Kokoro, Chatterbox, and Qwen3-TTS, eSpeak/ffmpeg binaries, bounded Hugging Face cache metadata, optional output disk space, and a non-executing virtual-environment/install plan. It never downloads model weights or claims inference success.

Validation performed in this environment: `tests/test_tts_environment.py` — 32 passed; `tests/test_tts_engine_adapters.py` — 30 passed; `tests/test_voiceover_pipeline.py` — 30 passed; `tests/test_voiceover_preflight_runner.py` — 39 passed. A combined invocation of these groups exceeded the tool time limit, so each suite was rerun separately and completed successfully.

Environment observation at execution time: Python 3.13.5; PyTorch 2.10.0+cpu; CPU-only device visible; `/usr/bin/espeak` and `/usr/bin/ffmpeg` present. The `kokoro`, `chatterbox`, `qwen_tts`, `transformers`, and `accelerate` modules/distributions required by the selected adapters were not all installed (Kokoro, Chatterbox, and Qwen engine packages absent). The diagnostic returned `inference_verified=false` and `selected_engine_ready=false` for Kokoro. No installation was attempted because dependency resolution/model size and upstream compatibility need deliberate target-environment selection. **Real inference status: BLOCKED, not PASS.**

### Smoke-test-discovered request mapping correction

The first end-to-end smoke test returned `INVALID_REQUEST_JSON` because the public version-1 envelope was passed directly to `PipelineRequest`, which expects flat fields. The runner now normalizes the public envelope into internal fields, preserves legacy flat request compatibility, applies `deadline_ms` as an upper timeout bound, and rejects unsupported non-null reference audio explicitly. Regression validation: `tests/test_request_mapping.py` plus `tests/test_voiceover_preflight_runner.py` — 57 passed. The repeat smoke test no longer fails request parsing; it reports `status=BLOCKED`, `error=PREFERRED_ENGINE_UNAVAILABLE`, `inference_verified=false`, exit code 3. This is the correct and honest result for the current environment because the Kokoro engine package is absent; no audio was generated.

## Final D0-221–D0-250 release verification

Fresh-extraction regression tests completed in separate, non-overlapping groups: core audio/adapters/pipeline 112 passed; audit/contracts/documentation 120 passed; evidence/schema 61 passed; evidence CLI 10 passed; IPC 84 passed; JSONL consumer end-to-end 30 passed; isolation/protocol/provider/runtime 67 passed; report-writer/packaging 62 passed (one expected warning from the duplicate-ZIP-entry rejection test); environment diagnostics 32 passed; request mapping 18 passed; preflight/runner 39 passed. **Total: 635 tests passed.** A combined command exceeded the execution time limit, so the groups were executed separately; each completed successfully.

The package was built reproducibly and extracted from the final archive for verification. Real-inference smoke result remains **BLOCKED** (`PREFERRED_ENGINE_UNAVAILABLE`), with `inference_verified=false` and no WAV output, because the Kokoro package is absent in this runtime. No inference success is claimed.

## D0-251–D0-280 — explicit engine setup and offline-safe installation

Added `engine_setup.py`, `scripts/setup_tts_engine.py`, `schemas/tts-engine-setup-report-v1.schema.json`, and `tests/test_engine_setup.py`. Setup is plan-only unless the caller explicitly passes `--install`. The opt-in path checks the base interpreter against a conservative Python 3.10–3.12 project policy, creates a new isolated venv, installs one allowlisted top-level engine distribution using an argv list without a shell, supports a local wheelhouse with optional `--no-index`, bounds command time and captured output, sanitizes child environment, redacts common credential-like values, runs `pip check`, and probes the expected module. It never loads or downloads model weights. JSON reports use an atomic replacement and schema coverage.

Targeted test result: **37 passed** (`python -m pytest -q tests/test_engine_setup.py`). The tests include default no-side-effect planning, all three engine IDs, invalid inputs, path safety, symlink rejection, Python-version gating, mocked install success/failure, dependency conflict, missing import, bounded/redacted logs, no-shell subprocess invocation, atomic report output, CLI behavior, and schema validation.

External dependency availability check: requests to `https://pypi.org/pypi/kokoro/json` and `https://huggingface.co/api/models/hexgrad/Kokoro-82M` both failed due to DNS resolution (`Temporary failure in name resolution`). No package installation was attempted; no model was downloaded; no WAV was generated. Real inference remains **BLOCKED**.

Release gate for this batch: targeted tests PASS; complete-suite and final archive verification must be recorded separately below before publication.

### Final fresh-extraction release verification (2026-10-05)

The release ZIP was extracted to a new directory and every non-overlapping test group was run from that clean extraction. All groups passed:

| Group | Result |
|---|---:|
| Audio quality, adapters, pipeline, preflight/runner | 151 passed |
| Audit diagnostics, contracts, documentation, OS-isolation docs | 120 passed |
| Evidence bundle/provenance and schema conformance/mutation | 61 passed |
| Evidence CLI | 10 passed |
| Runtime worker + IPC contract | 101 passed |
| JSONL + consumer E2E | 30 passed |
| Isolation provider + protocol fuzz + provider conformance | 50 passed |
| Report-writer hardening + packaging | 62 passed, 1 expected duplicate-ZIP test warning |
| Engine setup + request mapping + environment diagnostics | 87 passed |
| **Total across disjoint groups** | **672 passed** |

A single monolithic `python -m pytest -q` attempt exceeded the 180-second command limit at about 32%; it is not reported as a monolithic pass. The complete suite was instead covered in the disjoint groups above, each of which completed successfully in the fresh release extraction.

Release package checks: **91 ZIP members**, 0 duplicate member names, ZIP CRC PASS, 90 SHA256SUMS entries verified, 61 Python files compiled, 10 JSON schemas passed Draft 2020-12 schema checks. Two reproducible builds were byte-identical. Final archive SHA-256 is recorded in the external discovery ledger; the embedded report omits its own enclosing ZIP digest to avoid a self-reference.

Actual Kokoro smoke test against the fresh extraction: exit code 3, `status=BLOCKED`, `error=PREFERRED_ENGINE_UNAVAILABLE`, `inference_verified=false`; no WAV output. The local diagnostic reports Python 3.13.5, PyTorch 2.10.0+cpu, CPU-only device; Kokoro and Chatterbox packages are missing, and Qwen TTS, Transformers, and Accelerate are missing. The setup tool's Python 3.10–3.12 policy correctly prevents trying to install into the current Python 3.13 environment. Network probes to PyPI and Hugging Face failed with DNS resolution errors. **No real inference PASS is claimed.**

## D0-281–D0-310 — runtime discovery and install preflight

Added `tts_runtime_preflight.py`, `scripts/preflight_tts_install.py`, `schemas/tts-runtime-preflight-v1.schema.json`, and `tests/test_tts_runtime_preflight.py`. The preflight discovers Python interpreters within the project's conservative 3.10–3.12 policy, runs isolated non-shell probes, checks approved PyPI and Hugging Face HTTPS reachability with bounded timeouts, inventories local wheelhouse filenames without executing them, and produces an atomic JSON report. Wheelhouse inventory explicitly does not validate Python/ABI/platform compatibility, dependency closure, provenance, or trust. Diagnostic reports can never claim that installation, model download, or inference occurred.

Targeted preflight tests: **52 passed**. The real CLI was run with network checks enabled: it exited 3 with `NO_SUPPORTED_INTERPRETER`; no supported interpreter was discovered. PyPI and Hugging Face both returned `UNREACHABLE` with DNS (`gaierror`) failures. `inference_verified=false`. No package install or model download was attempted.

Final fresh-extraction verification: **724 passed** in nine disjoint groups: audio/adapters/pipeline/preflight 151; audit/contracts/docs 66; evidence/schema 61; evidence CLI 10; runtime worker + IPC 101; JSONL + report-consumer E2E 84; isolation/protocol/provider 50; report-writer/packaging 62 (one expected duplicate-entry warning); setup/request mapping/environment/runtime preflight 139. The clean extraction collected 724 tests. The monolithic suite is not claimed as a single-command pass.

The final ZIP contains 96 members (95 manifest entries), no duplicate names, valid CRC, 95/95 manifest entries verified, 64 Python files compiled, 11 Draft 2020-12 schemas checked, and two reproducible builds are byte-identical. Final archive SHA-256 is recorded in the external discovery ledger. Actual smoke test against the fresh extraction returned `BLOCKED / PREFERRED_ENGINE_UNAVAILABLE`, exit 3, no output directory/audio, `inference_verified=false`. Actual speech synthesis remains blocked until a compatible interpreter, engine dependencies, network or verified offline wheelhouse, and model assets are available.

## D0-311–D0-340: offline speech baseline and final package

A new `scripts/offline_speech_probe.py` was added. It runs local `espeak-ng`/`espeak` without a shell, enforces bounded input and timeout, refuses existing output by default, writes to a temporary WAV first, validates PCM properties and non-silence, then publishes the validated file. The separate JSON report uses atomic replacement, excludes transcript text, rejects audio/report path collisions, and preserves `neural_engine=false` and `inference_verified=false`.

Actual local run: `speech_output_verified=true`; generated mono 16-bit PCM at 22050 Hz, duration 5.926485261 s, size 261402 bytes, peak 0.843226417, RMS 0.091866443, clipping ratio 0, all-silent false, no quality warnings. WAV SHA-256: `7699335a0d8a54f3e87727a99c074bf94db27ca496785ec51723ff79c310a707`. This is a system/formant TTS baseline only and does not verify intelligibility or any neural engine.

The full 732-test source suite passed when split into bounded non-overlapping groups. A monolithic run hit the execution timeout, so the successful claim is based on the separate completed groups, not that timed-out aggregate invocation. The new focused probe/schema/docs set passed 18 tests. Final ZIP build and reproducibility passed with 100 manifest entries. The final archive hash is recorded in the external release note, not embedded into the package (to avoid a self-referential build hash).

Neural inference remains BLOCKED: only Python 3.13.5 was available while current project policy requires 3.10–3.12; no local wheelhouse was found; PyPI and Hugging Face DNS probes failed. No neural audio was generated and no neural inference PASS is claimed.

## D0-341–D0-370 runtime acquisition evidence

A fresh runtime acquisition diagnostic was added. The active interpreter remains Python 3.13.5, while the project policy accepts Python 3.10–3.12. `uv` is installed and advertises downloadable CPython 3.12/3.11/3.10 candidates, but the offline acquisition attempt for CPython 3.12.12 failed because the required archive was not in the local cache and network access is disabled. The diagnostic records this as `OFFLINE_CACHE_MISS`; it does not claim that a runtime was installed. Optional neural packages remain absent in the active environment, so neural inference acceptance remains BLOCKED.


## D0-401–D0-430 — adapter-accurate readiness and Kokoro CPU inference

The v2 artifact inventory now matches the adapters' official file layouts. Kokoro requires `config.json`, `kokoro-v1_0.pth`, and a `voices/*.pt` file; Qwen3-TTS checks core model/tokenizer assets plus its nested speech tokenizer; Chatterbox checks the multilingual loader's required checkpoint files. Hugging Face cache paths are discovered without importing the Hub client, explicit model roots are strict, and internal cache symlinks are scanned only within the selected root. A separate Python-preflight fix preserves a virtual environment's executable path instead of resolving its symlink to the base Python.

The complete source suite covered **44 test modules in three disjoint groups: 221 + 275 + 311 = 807 passed, 2 skipped, 0 failed**. The two skips are real eSpeak synthesis tests because no eSpeak executable is installed. The duplicate-ZIP-member warning from its rejection fixture is expected. The previously failing existing-output/symlink tests now pass because output validation runs before the missing-eSpeak early return.

A local-only artifact-v2 audit returned `ARTIFACTS_READY`. The isolated Kokoro interpreter was explicitly selected in the runtime preflight; it returned exit 0, `ENGINE_PREREQUISITES_PRESENT`, and nested `ARTIFACTS_READY`. The 327,212,226-byte model checkpoint was not fully hashed because the per-file hashing ceiling is 64 MiB; the small configuration and voice files were hashed.

A real, synthetic English request loaded Kokoro 0.9.4 and generated speech on CPU with voice `af_heart`. The smoke report returned `PASS`, `inference_verified=true`, and all seven objective checks passed. A separate `inspect_voiceover_audio.py` run independently decoded the WAV: 24 kHz, mono, 16-bit PCM, 4.225 seconds, non-silent, clipping ratio 0, and no warnings. Audio SHA-256: `9d328112dd41f42c1d859c99ab2fcaf845646193e0f2096b3b09242cf843bf39`. Detailed evidence is in `D0_401_430_TEST_EVIDENCE.md` and the two JSON evidence files.

This proof is limited to one Kokoro English CPU profile; it does not establish subjective speech quality, Qwen3-TTS/Chatterbox inference, offline operation, or custom voice design. The Android feasibility probe found no manifest, Gradle project/wrapper, SDK, or build tools, so no genuine APK could be built from the supplied Python project. Prompt-based custom-voice model selection is continuing as a separate follow-on scope.


### D0-401–D0-430 release archive and extraction

The standard-library builder produced a ZIP with 126 manifest entries (127 ZIP members); CRC and extracted SHA256SUMS verification passed. Two reproducibility archives were byte-identical. A fresh extraction compiled 78 Python files, validated all 16 Draft 2020-12 schemas, and passed the complete 44-module suite in three disjoint groups: **221 + 275 + 311 = 807 passed, 2 skipped, 0 failed**. The two skips are the eSpeak synthesis tests; one expected duplicate-ZIP-entry warning comes from the rejection fixture. The final enclosing ZIP SHA-256 is in the external release-evidence note, not embedded here.


## D0-431–D0-460 — Custom voice profiles, installable Skill, and MiniMax packaging (2026-10-10)

The complete source suite passes: **925 passed, 2 skipped, 0 failed**. The two skips are real eSpeak tests because the executable is absent; the existing duplicate-ZIP-entry test emits one expected Python warning. The focused package test file passed 3 tests, and the official Agent Skill validator passed. The four Skill/plugin ZIP targets (standalone Skill, Claude Code, MiniMax Code dual layout, and MiniMax Marketplace submission) pass structural/CRC checks and byte-identical reproducibility builds. The Code 0.3.x/0.4.0+ compatibility package and the Marketplace submission package are separate: the latter carries only `.minimax-plugin/plugin.json` and referenced Skill files, with no root `plugin.json` or `.claude-plugin` manifest. This follows the current MiniMax submission guide's native-format requirement.

The reproducible source ZIP contains 246 ZIP members and 245 `SHA256SUMS` entries. A fresh extraction under a path containing spaces and non-ASCII characters passed ZIP CRC, safe-path/duplicate checks, and all manifest hashes. Python compilation passed for 162 files. From that extraction, the full suite again passed **925 passed, 2 skipped**, the Agent Skill validator passed, runner/profile CLIs worked (including a non-ASCII profile-store path), and read-only resource/artifact commands succeeded. The Qwen VoiceDesign artifact report was `ARTIFACTS_READY` with no missing required files; `inference_verified=false` remained unchanged. Final release artifact SHA-256 values are provided in the companion release manifest rather than embedded into the enclosing source ZIP.

Qwen3-TTS CPU setup returned `PACKAGE_READY`, and pinned VoiceDesign assets at revision `5ecdb67327fd37bb2e042aab12ff7391903235d3` downloaded (4,520,159,099 bytes across 11 allowlisted files); local full-file hashes were not recomputed. One real profile-backed CPU inference attempt was made under the 14-GiB preflight, two-thread limit, 300-second deadline, and fixed 10-GiB process-tree RSS cap. It ended with `RESOURCE_LIMIT_EXCEEDED`, worker exit 137. No WAV was produced, so independent audio inspection was not possible. Qwen inference remains **unverified** and Phase 0 remains **OPEN / HOLD**. The existing Kokoro evidence is limited to one English CPU profile. Android feasibility remains negative for this Python-only tree: no Android manifest, Gradle project/wrapper, SDK, or build tools were present; no APK was fabricated.

### हिंदी सारांश

इस batch में पूरा Skill, reusable voice-profile workflow, bounded downloader और चार अलग packages तैयार हुए। पूरा suite source और fresh extraction—दोनों जगह **925 पास, 2 स्किप** रहा; Skill validator तथा reproducible ZIP checks पास हुए। MiniMax Code dual-layout और native Marketplace submission ZIP अलग हैं ताकि असंगत manifests submission package में न जाएँ। Qwen CPU setup/model files तैयार हैं, लेकिन inference 10-GiB RSS guard पर रुक गया; WAV नहीं बना और Qwen `inference_verified=false` है। Phase 0 **OPEN / HOLD** है; Android build toolchain न होने से APK नहीं बनाया गया।


## D0-461–D0-470 follow-up — Qwen VoiceDesign BF16 and verified-only runtime (2026-10-10)

The earlier D0-431–D0-460 default-FP32 Qwen VoiceDesign CPU attempt remains a valid historical `RESOURCE_LIMIT_EXCEEDED` failure with no WAV. Without changing the existing 14-GiB RAM preflight, two-thread policy, 300-second deadline, or fixed 10-GiB process-tree RSS cap, the Qwen CPU adapter was changed to request the pinned checkpoint's native BF16 dtype. One real, v2 profile-backed English VoiceDesign request completed successfully. Its smoke report is `PASS`, worker return code is 0, and `inference_verified=true`.

The actual output is 24-kHz mono PCM16, 76,800 frames / 3.2 seconds, 153,644 bytes. All seven objective smoke checks passed. Independent WAV inspection returned `ok=true`, no warnings, zero clipping, and the same SHA-256: `a998c90bc521e1bf9bfcbf72fbf0c96d97a13c482cbd315ad03bc920dbdc2b73`. Evidence: `research/d0_431_460/qwen_voice_design_bf16_cpu_smoke_report.json`, `research/d0_431_460/qwen_voice_design_bf16_audio_inspection.json`, and `research/d0_431_460/qwen_voice_design_bf16_smoke_output/qwen-voice-design-bf16-smoke.wav`. The resource guard did not trigger, but the report has no measured peak-RSS value; no exact peak is claimed. This verifies one English prompt-profile path on this host, not subjective quality, broad language/control coverage, identity, or other-host performance.

The shipped runtime surface now fails closed to the real-WAV-verified pairs only: `kokoro/preset` and `qwen3_tts/voice_design`. Legacy v1 execution is Kokoro-only; v2 schema/normalizer accepts only Kokoro and Qwen, with Qwen requiring a profile. Profile creation, engine setup, and model-download CLIs reject unverified modes/targets. Chatterbox/reference clone and Qwen CustomVoice preset are not selectable through the installed Skill. The full suite after these changes passed **932 tests, 2 skipped, 0 failed**; the two skips are optional eSpeak tests, and the duplicate-ZIP warning is expected. The Agent Skill validator passed. Phase 0 remains **OPEN / HOLD** for broader acceptance. Final exact archive and clean-extraction evidence is in the D0-461–D0-470 release manifest.

### हिंदी सारांश

पहला FP32 Qwen प्रयास 10-GiB RSS guard पर रुकने का ऐतिहासिक तथ्य बना रहता है। कोई सीमा बढ़ाए बिना native-BF16 CPU load के साथ बाद का वास्तविक profile-backed English VoiceDesign run सफल हुआ: 24 kHz mono PCM16 WAV, 3.2 सेकंड, 153,644 bytes; सातों objective checks और independent inspection पास। SHA-256 `a998c90bc521e1bf9bfcbf72fbf0c96d97a13c482cbd315ad03bc920dbdc2b73` है। Guard trigger नहीं हुआ, लेकिन measured peak RSS रिपोर्ट में नहीं है। अब Skill केवल `kokoro/preset` और `qwen3_tts/voice_design` routes expose करती है; Chatterbox/reference clone और Qwen CustomVoice preset अभी unsupported हैं। पूरा suite **932 पास, 2 स्किप**; Skill validator पास। Phase 0 **OPEN / HOLD** है। Final archives की clean-extraction व hash evidence D0-461–D0-470 release manifest में दर्ज है।

### D0-461–D0-470 final release extraction

The four Skill/plugin ZIPs were rebuilt with byte-identical reproducibility checks and passed CRC/structural audits. The final source ZIP has 252 members, including `SHA256SUMS`; all 251 manifest entries passed. Its fresh extraction under `/tmp/voiceover source café final d0-461-470/` compiled 162 Python files and contained 20 JSON schemas. The complete suite passed **932 passed, 2 skipped, 0 failed**; the two skips are unavailable eSpeak checks. The Agent Skill validator passed. Profile listing worked with a non-ASCII/space-containing store path; the extracted v2 engine schema and runner/setup/downloader CLI help contain only the verified Kokoro/Qwen user-facing routes. Rebuilding all four plugin ZIPs from the extracted source produced the same release ZIP digests. Exact artifact hashes and the separate Qwen WAV/sample-report hashes are in `D0_461_470_RELEASE_MANIFEST.md` outside the source archive.