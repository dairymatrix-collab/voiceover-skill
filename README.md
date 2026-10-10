# Voiceover Skill — Local Pipeline and Contract Harness

**Purpose:** a local voiceover pipeline with versioned request contracts, reusable profiles, setup/artifact preflights, isolation, and independent WAV checks. **Phase 0 remains open for broader coverage:** real inference has been demonstrated for one Kokoro English CPU smoke profile and one Qwen3-TTS VoiceDesign English CPU profile. Both generated WAVs passed seven objective checks on this host; this does not prove subjective quality, broad language/voice coverage, or long-run stability. Chatterbox and Qwen CustomVoice preset remain unverified and are withheld from the Skill runtime; external agent-runtime integration also remains unverified.

## Requirements
- Python 3.10–3.12 for the current optional-engine setup policy; check each upstream engine's requirements before extending it.
- Test dependencies: pinned `pytest`/`jsonschema` plus bounded `numpy`/`soundfile` for adapter conversion tests (install with `python -m pip install -r requirements-dev.txt`).
- The local contract suite does not contact services or download weights. A real-inference smoke is a separate, explicit operation that needs an installed engine and model cache; it is not run by `pytest`.

## Verify packaged source files
From this directory, verify the SHA-256 manifest before running tests:

  ```bash
  sha256sum -c SHA256SUMS
  ```

The manifest covers the packaged source modules, tests and fixtures, schemas, configuration, documentation, research notes, and evidence files; it does not hash itself or the ZIP container.

## Run
From this directory:

```bash
python -m pytest -q
```


## D0-161..D0-190 — readiness preflight and bounded inference runner

`voiceover_preflight.py` checks output-directory writeability, Python/JSON runtime basics, optional FFmpeg presence, PyTorch device availability, and installed optional engine packages. It **does not load model weights, download files, or claim that inference works**. Use:

```bash
python scripts/preflight_voiceover.py --output-dir ./voiceover-output --pretty
python scripts/preflight_voiceover.py --engine kokoro --output-dir ./voiceover-output
```

`scripts/run_voiceover.py` accepts a JSON request and runs the selected real adapter in a separate Python worker process. The parent applies a wall-clock timeout and returns structured JSON for invalid requests, worker protocol failures, dependency failures, and timeouts. Example request:

```json
{
  "request_id": "demo-001",
  "text": "Hello. This is a voiceover test.",
  "language": "en",
  "voice_id": "af_heart",
  "chunk_chars": 1200,
  "speed": 1.0
}
```

Run with:

```bash
python scripts/run_voiceover.py --request request.json --output-dir ./voiceover-output --engine kokoro --timeout-seconds 900
```

The runner uses the current Python interpreter, a fixed worker script path, an argv array (no shell), a resolved output directory, and a bounded timeout. It inherits the environment so model-cache and device variables can be honored; it does not print the environment or child stderr. Only pass trusted environment variables to production jobs. A subprocess timeout kills the direct worker process; this runner has not been proven to terminate all descendants on every OS and is **not a sandbox**.

Preflight status `READY_TO_ATTEMPT` means at least one optional package is installed, not that its model is cached, loads, supports the requested voice, or produces audio. The earlier D0-161 environment snapshot reported all three optional packages (`qwen_tts`, `chatterbox`, `kokoro`) absent; the later D0-401–430 evidence supersedes that package snapshot for Kokoro, and a subsequent Qwen VoiceDesign BF16 smoke verified one English profile-backed CPU WAV. Chatterbox and Qwen CustomVoice preset remain unverified.

## Deterministic packaging (D0-42)

The standard-library packager regenerates `SHA256SUMS`, creates a ZIP with sorted paths and normalized timestamps, excludes cache/temporary artifacts, and verifies both ZIP integrity and the extracted manifest. Run from any working directory:

```bash
python scripts/build_package.py --output /path/to/voiceover_contract_harness.zip --check-reproducible
```

The output ZIP must be outside the source root. `--check-reproducible` builds two temporary archives and requires byte-identical output. This verifies deterministic packaging in the current Python/zlib environment; it is not a cross-platform bit-for-bit guarantee.

## Covered contracts
- input validation and stable error codes
- bounded chunking and order/character preservation
- deterministic engine routing, language and availability filtering
- explicit engine preference without silent fallback
- voice catalogue lookup
- WAV readability, metadata, empty/corrupt files and sample-rate validation
- output path traversal prevention
- common API-token redaction patterns
- offline model-cache preflight errors and cache path containment
- malformed requests, invalid language/engine IDs, duplicate engines, and unavailable-adapter routing
- malformed adapter availability/language metadata and malformed explicit engine preferences
- Unicode chunk boundaries and invalid boolean/non-integer limits
- truncated WAV payloads, invalid duration limits, and configured duration caps
- invalid output-name types and NUL-containing names

## Final test evidence
See `FINAL_TEST_EVIDENCE_REPORT.md` for the chronological task-by-task test evidence, acceptance mappings, final command outputs, and known limitations.

## Limitations
- Fake adapters do not call actual TTS models.
- Tests do not establish subjective audio quality, intelligibility, voice identity, latency, peak RAM, long-run stability, or agent-platform compatibility.
- The helpers are executable reference contracts; production code must implement equivalent behavior and then be tested against these cases. The negative-case suite is not a security certification or a substitute for integration tests.

## D0-30 IPC contract validation

The `schemas/` directory contains Draft 2020-12 JSON Schemas for the version-1 synthesis request and terminal result. `ipc_contract.py` adds strict JSONL framing, duplicate-key and non-finite-number rejection, schema validation, and request/job correlation checks. These are model-free contract validators, not a worker supervisor or process sandbox.

The IPC validator uses `jsonschema==4.26.0`, pinned in `requirements-dev.txt`. Run all tests with:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Coverage includes valid messages, malformed UTF-8/JSONL, duplicate keys, oversized lines, unknown fields/versions, invalid engine/options, path-traversal-shaped reference/output paths, response status invariants, and request/job ID mismatches. Process-tree cancellation, symlink-swap races, real worker startup, actual audio-file probing at the supervisor boundary, and real TTS inference are not implemented by this task.

## D0-31 validator edge-case audit

The IPC contract now rejects non-canonical relative paths before schema validation: absolute paths, Windows-style backslashes/drive prefixes, empty path components, `.`/`..` components, repeated separators, trailing separators, and segments with leading/trailing whitespace. This is lexical validation only; the future supervisor must still enforce resolved-path containment and symlink/race safety at filesystem operations.

Regression tests cover direct Python boolean/non-finite numeric inputs, numeric boundaries, canonical nested POSIX paths, and the exact encoded JSONL line-size boundary. This remains model-free contract validation; it does not prove process isolation, safe file opening, or real TTS functionality.

## D0-32 contract error compatibility

`IPCContractError` exposes `.code` and optional `.detail` fields while preserving its original string representation for backwards compatibility. Regression tests compare direct-validator and parse-and-validate errors for JSON-representable invalid requests/results, including both the stable category and detail. Non-finite JSON tokens are intentionally rejected at the parser boundary (`PROTOCOL_NONFINITE_NUMBER`), while non-finite values supplied directly by Python callers are rejected by semantic validation (`PROTOCOL_SCHEMA_INVALID`); these are different failure stages by design.


## D0-33 deterministic protocol robustness tests

`tests/test_protocol_fuzz.py` adds seeded malformed-byte and Unicode cases, deeply nested JSON, oversized integer tokens, exponent overflow, escaped lone surrogates, and line-size boundary checks. The JSON parser now rejects numeric exponent overflow that would otherwise become `inf`, and rejects unpaired surrogate code points in decoded object keys or values. These tests are deterministic regression tests, not exhaustive fuzzing. Hypothesis is not installed in the current offline environment; no network install was attempted.

## Parser resource boundaries (D0-34)

The JSONL parser rejects messages larger than 1 MiB, structural nesting beyond 128 levels, and integer tokens longer than 1,024 digits. These are provisional application-level parser limits, not process-level resource isolation or a security certification. The eventual worker supervisor must separately enforce timeouts, bounded queues/backpressure, process-tree cancellation, and OS-level isolation.


## Protocol compatibility policy (D0-35)

Protocol v1 is a **closed contract**: `additionalProperties: false` is deliberate, so a v1 peer rejects unknown fields and any `protocol_version` other than the integer `1`. Boolean `true` is not accepted as version 1. Versioned sample fixtures live in `tests/fixtures/protocol-v1/` and are exercised by the test suite.

Because v1 is closed to unknown fields, adding fields—even optional fields—requires a coordinated schema/protocol version change rather than silently extending v1. A future v2 must define migration/negotiation explicitly; do not assume v1 and v2 peers interoperate. Keep old v1 fixtures as regression evidence when adding later versions.

### D0-35 compatibility fixture coverage

The versioned fixture tests exercise both direct validators and parse-and-validate entrypoints. Schema `protocol_version` fields require both JSON Schema integer type and `const: 1`, preventing Python's `True == 1` equality behavior from accidentally treating a boolean as protocol version 1.

## D0-36 deterministic JSONL serialization

`canonical_jsonl_message()` validates a version-1 request/result and serializes it using sorted object keys at every depth, compact separators, literal UTF-8 Unicode, finite JSON numbers, and exactly one LF terminator. The output is deterministic for the Python JSON implementation used here; it is **not** an implementation of RFC 8785/JCS number canonicalization and does not by itself prove cross-language byte-for-byte equivalence. Consumers should validate protocol semantics against the JSON Schemas and treat canonical bytes as this harness's serialization profile.

Regression tests cover insertion-order independence, Unicode round-trips, escaped embedded newlines, stable key order, strict schema rejection, and canonical serialization/parse round trips for the v1 request/result fixtures. No worker transport or TTS engine is exercised.

## D0-37 independent schema conformance vectors

`tests/fixtures/schema-conformance-v1.json` is a machine-readable vector set for request and result boundaries. `tests/test_schema_conformance.py` checks each vector against both the Draft 2020-12 schema validator and the public direct Python validator, requiring both outcomes to match the expected result. Coverage includes booleans vs integer/number fields, nulls, minimum/maximum values, protocol versions, status values, and canonical/invalid relative paths.

The audit found that the original JSON Schema path regex was looser than the Python canonical-path rule for trailing separators and whitespace-containing paths. Both schemas now use a deliberately conservative path alphabet (ASCII letters/digits, underscore, dot, slash, hyphen), reject trailing/repeated separators, and reject `.`/`..` path components. This is a v1 contract tightening before production adoption; filenames with spaces are intentionally unsupported. Lexical schema validation still does not replace resolved filesystem containment or symlink/race-safe opening in a future supervisor.

The conformance vectors cover JSON-representable values. Python-only non-finite floats are tested separately and rejected by the direct validator; they are not valid JSON values. The suite is still model-free and does not prove independent-language or deployed-runtime interoperability.

## D0-38 schema mutation and error-path audit

`tests/test_schema_mutation.py` adds deterministic mutations for required-field deletion, unknown fields at top-level and nested objects, invalid `message_type` values, recursive direct-Python containers, and canonical serializer failure handling. For JSON-representable mutations, JSON Schema and public-validator acceptance are compared. The public validator now converts recursion/type/value failures from malformed direct-Python objects into `IPCContractError(PROTOCOL_SCHEMA_INVALID:$)` rather than leaking implementation exceptions. These tests do not make arbitrary Python objects valid protocol values and do not replace JSONL parsing for untrusted bytes.

Phase 0 remains **OPEN / HOLD**. D0-401–430 verified one real Kokoro CPU load and English synthesis path; a later native-BF16 Qwen3-TTS VoiceDesign run verified one profile-backed English CPU WAV. Chatterbox and Qwen CustomVoice preset, broader language/voice coverage, production-grade process supervision/sandboxing, and external agent-runtime integration remain unverified.

## D0-39 — JSONL end-to-end matrix

`tests/test_jsonl_e2e_matrix.py` tests the public request/result pipeline from JSONL framing through parsing and contract validation, including failure-code classification, correlation IDs, canonical serialization round-trips, and multilingual UTF-8 payloads. Run with `python -m pytest -q`. This is model-free local test coverage, not production IPC or TTS verification.


## D0-40 documentation-to-code drift audit

The dependency description above distinguishes the standard-library contract helpers in `contracts.py` from `ipc_contract.py`, which imports the pinned `jsonschema==4.26.0` package. The SHA-256 manifest covers `FINAL_TEST_EVIDENCE_REPORT.md` as well as source, tests, fixtures, schemas, configuration, README, and dependency pins; the manifest itself and ZIP container are excluded. The evidence report is chronological: older test counts describe their named historical task, while the latest section records the newest verification.

The harness remains a local model-free reference implementation. It does not implement a production IPC supervisor, worker lifecycle, process isolation, filesystem containment at file-open time, or actual TTS inference.

## D0-41 — clean-archive reproducibility audit

The D0-41 check extracted the distributed ZIP into a new temporary directory and ran the complete suite from that extracted tree, not from the original source directory. The archive's SHA-256 manifest passed before tests; the suite passed **208 tests** in the clean extraction. Python was 3.13.5, with the pinned `pytest==9.0.2` and `jsonschema==4.26.0` already available in the execution environment. This verifies clean extraction and working-directory independence in that environment; it does **not** prove dependency installation from an empty offline environment or cross-platform reproducibility.

To repeat in an environment with package access, extract the ZIP into a directory and run the commands from that extraction directory (the ZIP contains the harness files at its root): install `requirements-dev.txt`, run `sha256sum -c SHA256SUMS`, then `python -m pytest -q`. The manifest intentionally excludes itself and the enclosing ZIP; the ZIP is verified separately.

## D0-43 — packaging failure-mode and atomicity audit

The packager now uses a unique temporary sibling for each ZIP build and only replaces the existing release after the staged archive passes its CRC check. A failed write preserves a prior output archive and removes its own staging file. The CLI preflights obvious invalid output locations before regenerating the source manifest. Regression tests cover simulated write failure, malformed ZIP input, source-tree immutability except for the regenerated manifest, and invalid output parents. These checks do not simulate power loss, filesystem corruption, concurrent processes racing on the same destination, or every platform's atomic-rename semantics.

### Archive integrity and extraction-safety checks

`python scripts/build_package.py --check-reproducible` validates the generated ZIP before publication and verifies the extracted SHA-256 manifest. The verifier rejects malformed/non-hex digests, unsafe or duplicate/case-colliding paths, ZIP duplicate members, symlink/special-file metadata, encrypted members, unsupported compression methods, cache/temp files, more than 1,000 members, and declared uncompressed payloads above 100 MiB. ZIP member metadata is preflighted before extraction into a private temporary directory. These limits protect this small harness distribution; they are not a general-purpose untrusted-archive extraction service.

## D0-45 model-free runtime worker boundary

`runtime_worker.py` runs one **trusted argv command** without a shell, sends exactly one validated request over stdin, drains stdout/stderr concurrently with byte limits, applies a wall-clock deadline, supports cooperative cancellation via `threading.Event`, requires a zero exit code, and validates exactly one terminal JSONL result against request/job correlation IDs. The child environment is deliberately reduced to a minimal PATH and UTF-8 setting (plus `SYSTEMROOT` on Windows).

Example API (inside a Python integration):

```python
from runtime_worker import run_worker
outcome = run_worker(["/absolute/path/to/worker", "--stdio-jsonl"], request, timeout_seconds=30)
print(outcome.result["status"])
```

The executable and arguments must be selected by trusted application code, never assembled from untrusted request text. This is **not** an OS sandbox: it currently kills the direct child, not a guaranteed whole process tree; CPU/RAM limits, network isolation, secure file-descriptor handling, output-file containment, and cross-platform process-group termination remain future work.

## D0-46 worker lifecycle race and I/O cleanup audit

The model-free worker regression suite now checks a 100,000-character valid request (writer must not deadlock), early child exit, exact stdout byte-limit acceptance and one-byte-under rejection, zero-byte stderr limit, cancellation observed before exit, success after the child has already exited, and named reader/writer thread cleanup. These tests define supervisor-level behavior only; they do not test process-tree cancellation or OS resource isolation.

## D0-47 process-tree cancellation capability gate

`runtime_worker.py` starts POSIX workers in a new session and sends termination signals to the worker process group on timeout, cancellation, output overflow, or when a descendant keeps inherited stdout/stderr pipes open after the direct worker exits. This covers descendants that remain in the process group; it is not a sandbox against a process that deliberately creates a new session or otherwise escapes the group.

On Windows, the supervisor requests `taskkill /T /F` as a best-effort tree cleanup and falls back to killing the direct child if that command is unavailable or fails. The Windows path has **not** been tested in Windows CI and must not be treated as verified. OS-level CPU/RAM/network isolation remains out of scope.


## D0-48 descendant escape policy

POSIX process-group cleanup only covers descendants that remain in the worker's managed process group. A descendant that deliberately calls `setsid()` can escape that group; this harness is **not a security sandbox** and does not claim containment against hostile worker code. If an escaped descendant keeps inherited stdout/stderr descriptors open, the supervisor's bounded cleanup attempts may end in `WORKER_IO_THREAD_STUCK`. This error is a cleanup failure signal, not proof that the escaped process was killed. The POSIX regression test creates such a descendant and explicitly kills it in test cleanup so no process is intentionally left running.

Production deployments requiring hostile-code containment must use an OS-level boundary such as a Linux cgroup/container with appropriate permissions and network/filesystem policy, or a Windows Job Object configured for kill-on-close, and must test that boundary on each target platform. This task adds no such sandbox.

## D0-49 — OS isolation capability contract

See [`OS_ISOLATION_CAPABILITY_CONTRACT.md`](OS_ISOLATION_CAPABILITY_CONTRACT.md) for the platform capability contract, minimum policy profile, Linux/Windows/macOS deployment acceptance matrix, and fail-closed release gate. This is design documentation only: no OS sandbox or resource/network/filesystem enforcement is implemented. Linux cgroup/container and Windows Job Object options are candidates, not verified support. The plain process-group worker remains best-effort cleanup and must not be presented as a sandbox.

## D0-50 platform-neutral isolation provider interface

`isolation_provider.py` defines the future provider protocol, opaque job handle, capability report, production policy profile, and fail-closed capability negotiation. The default gate requires explicit, verified process-tree, CPU/time, memory, filesystem, network, least-privilege, cleanup, and bounded-observability capabilities for the exact target platform. Unknown or false capabilities block the gate; secrets in worker environment are prohibited by the contract.

This is **interface and model-free unit-test coverage only**. No platform provider is implemented, no OS isolation is enforced, and test-fixture evidence is not production attestation. Do not call this harness sandboxed or production-isolated.

## D0-51 — provider conformance and evidence records

`provider_conformance.py` defines a model-free conformance runner for a **trusted provider implementation supplied by deployment code**. It validates the capability gate, launches one caller-supplied trusted probe, checks lifecycle/wait/inspection/containment/exit status, attempts cleanup, and emits a JSON evidence record. The record shape is defined in `schemas/provider-conformance-evidence-v1.schema.json` (JSON Schema Draft 2020-12).

Example integration outline:

```python
from provider_conformance import run_provider_conformance

record = run_provider_conformance(
    trusted_provider,
    target_platform="linux-x86_64",
    probe_argv=["/absolute/path/to/trusted-probe", "--self-test"],
    cwd="/approved/test/workdir",
    env={"PATH": "/usr/bin:/bin"},
    limits={"cpu_seconds": 5, "memory_bytes": 268435456},
)
print(record.to_json())
```

Only use a harmless probe executable and arguments selected by trusted deployment code. Evidence records are diagnostic reports, **not signed attestations**; a fake/test provider can produce a structurally valid record and this does not prove OS containment. The suite deliberately has no concrete Linux/Windows/macOS provider and does not launch real TTS models.

## Evidence semantics and tamper checks (D0-52)

`provider_conformance.py` now validates cross-field consistency before returning a report: duplicate check IDs, provider metadata mismatches, gate/status contradictions, missing denial reasons, and overall PASS claims contradicted by individual checks are rejected. `parse_evidence_json()` rejects duplicate JSON object keys before semantic validation. `evidence_sha256()` hashes canonical JSON; `verify_evidence_sha256()` detects changes only when the expected digest is obtained from a separately trusted channel. A plain digest is not a signature, identity proof, or authenticated attestation.


## Evidence provenance envelope (D0-53)

`evidence_provenance.py` and `schemas/evidence-provenance-envelope-v1.schema.json` define a model-free provenance envelope for evidence source/tool version and invocation ID, provider identity claims, test environment and timezone-aware timestamps, evidence digest, artifact SHA-256 values, trust level, verification state, limitations, and optional signature metadata. The semantic validator rejects self-asserted `independently_verified` and `cryptographically_authenticated` levels unless the caller supplies `verifier_evidence=True` from a separately trusted verifier. Never set this argument from envelope contents.

Trust levels are not interchangeable: `self_reported` is an assertion, `locally_measured` is a local observation, `independently_verified` requires independent verification evidence, and `cryptographically_authenticated` requires a signature that a trusted verifier actually checked. SHA-256 alone proves neither source identity nor authenticity; even an artifact hash is meaningful only relative to bytes actually hashed and a trusted comparison point. Do not include tokens, passwords, private keys, or other secret material in provenance envelopes.

No signing or verification implementation is provided. Before adding signatures, approve the signing identity, algorithm, canonicalization, key custody, verifier trust roots, key rotation/revocation, trusted timestamping, signature scope, and verification/rejection policy. This envelope is a design/validation contract, not authenticated attestation. Phase 0 remains OPEN / HOLD.

## Provenance adversarial parsing and parity audit (D0-54)

`validate_provenance_envelope()` now applies the published Draft 2020-12 JSON Schema before semantic trust checks and fails closed if schema validation itself cannot run. Semantic checks remain stricter than schema structure for safe artifact paths, timestamp ordering by actual timezone-aware instants, and trust-boundary claims. `parse_provenance_json()` rejects duplicate keys at any depth, non-standard constants (`NaN`/`Infinity`), invalid UTF-8, non-object roots, excessive input size (default 1 MiB), malformed/deeply nested JSON, and schema/semantic failures. This is a model-free defensive parser, not a signature verifier; the 1 MiB default is configurable and callers should keep an appropriately small bound for their workload.

## Evidence bundle cross-file integrity (D0-55)

`evidence_bundle.py` defines a model-free bundle manifest and verifier. The manifest inventories every regular payload file plus the provenance envelope, recording each relative path, byte length, and SHA-256. The envelope separately lists the payload artifact hashes **excluding itself and the manifest**; the manifest records the envelope hash. This avoids circular self-hashing while checking both sides of the relationship. The verifier rejects missing/extra files, symlinks, unsafe or duplicate paths, changed bytes/lengths, malformed/duplicate-key manifests, schema violations, envelope hash disagreement, and envelope artifact inventories that do not exactly match the bundle payload.

### Reproducible verification procedure

1. Place final payload files in a new, private bundle directory; do not include credentials, private keys, or transient files.
2. Compute SHA-256 from the actual payload bytes and put those values in the envelope's `artifacts`, using safe relative paths. Keep the envelope untrusted (`self_reported` / `unverified`) unless an external verifier independently establishes a stronger state.
3. Serialize the envelope using `canonical_provenance_json()` and write it as `provenance-envelope.json`.
4. Call `build_evidence_bundle_manifest(bundle_root)` and write the returned object to `evidence-bundle-manifest-v1.json` using `canonical_bundle_json()`.
5. Run `verify_evidence_bundle(bundle_root)`. An empty error list means local byte inventory and cross-file consistency passed, not that the author is authentic.
6. For an independent check, transfer the bundle and obtain the manifest digest through a separate trusted channel; recompute it on the receiving system and then run the verifier. Without that independently trusted digest or a future approved signature system, an attacker able to rewrite both payload and manifest can produce a self-consistent forged bundle.
7. Repeat verification after transfer/extraction. Preserve the verifier version and invocation output separately; do not place a digest of the manifest inside that same manifest.

The bundle manifest is unsigned. SHA-256 detects changed bytes only when the expected digest is trusted independently; it does not authenticate the manifest author or establish provider identity. Digital signatures, trust roots, timestamping, and key lifecycle remain deferred. Phase 0 remains OPEN / HOLD.

## D0-57 stable audit diagnostics

Audit report `errors` is an array of structured diagnostics. Each entry has a stable `code`, `category`, `severity`, concise `message`, actionable `remediation`, and original `raw_message`. Consumers should branch on `code`, not on prose. Existing codes are permanent API identifiers: never renumber or reuse them; add a new code for a new failure class. Unmapped failures use `BUNDLE_VERIFICATION_FAILED_UNCLASSIFIED` and remain errors (fail-closed). A structured diagnostic does not authenticate the evidence source; report PASS still means local consistency only.

## D0-58 diagnostic coverage matrix and golden corpus

`AUDIT_DIAGNOSTIC_COVERAGE_MATRIX.md` maps each configured verifier-message prefix to its stable diagnostic code. `tests/fixtures/audit-diagnostics-v1.json` is the versioned golden corpus; tests compare the complete structured output and enforce that every configured prefix and public code has corpus coverage. The corpus detects mapping drift, but it cannot anticipate every future verifier message; unknown messages deliberately use `BUNDLE_VERIFICATION_FAILED_UNCLASSIFIED` until triaged.

Run the focused regression set with:

```bash
python -m pytest -q tests/test_audit_diagnostics.py tests/test_audit_diagnostic_golden_corpus.py tests/test_evidence_bundle_cli.py
```

## D0-59 diagnostic precedence and shadowing

Diagnostic classification is ordered: the first matching rule in `audit_diagnostics._RULES` wins. Regression tests fail if needles for different stable codes have a literal substring shadowing relationship, and exercise every ordered pair of rules with synthetic combined messages to protect deterministic precedence. If a future rule intentionally overlaps another, document the exception and add a targeted regression test rather than relying on accidental order.

## D0-60 CLI exit codes and audit-report consistency

The evidence-bundle CLI uses this public outcome contract:

- **Exit `0`**: a JSON audit report is emitted with `status: PASS`, `error_count: 0`, and an empty `errors` array.
- **Exit `1`**: a JSON audit report is emitted with `status: FAIL`, `error_count` equal to the number of structured diagnostic objects, and at least one error.
- **Exit `2`**: a CLI usage or report-output failure occurred. The CLI writes a human-readable message to stderr and does not emit a success-shaped JSON report. If the requested report file cannot be written, no JSON report is guaranteed.

`ERROR` is reserved by the report schema for future operational-reporting evolution; this CLI version does not emit an `ERROR` report. `report_exit_code()` rejects status/count/cardinality drift before output, and tests cover PASS, single/multiple-error FAIL reports, usage errors, report-write errors, and deliberately inconsistent report objects. A `PASS` still means local evidence-bundle consistency only, not cryptographic authenticity or successful TTS inference.


### Audit report consumer compatibility

The report consumer contract is documented in `AUDIT_REPORT_CONSUMER_COMPATIBILITY.md`. Consumers must check `audit_report_schema_version` (`1.0` supported), validate the report schema, and branch on stable `errors[].code` identifiers rather than prose. Unknown diagnostic codes must be handled generically; breaking structural changes require a new schema version. The reference implementation is `audit_report_consumer.py`, with `parse_audit_report_json()` for untrusted serialized input (5 MiB maximum, 10,000 diagnostics maximum, 100-level JSON nesting maximum, strict UTF-8, duplicate-key and non-finite-number rejection) and the golden fixture `tests/fixtures/audit-report-consumer-v1.json`.



### Audit report consumer validation-cost bound

The reference consumer stops after observing 101 JSON Schema errors and rejects reports that exceed its 100-error validation cap. This prevents unbounded error-list materialization/sorting; it is not a substitute for process-level CPU or memory isolation. Consumer failures expose stable `AuditReportContractError.code` values (for example `AUDIT_REPORT_MALFORMED_JSON`, `AUDIT_REPORT_UNSUPPORTED_VERSION`, and `AUDIT_REPORT_SCHEMA_VIOLATION`) so integrations do not need to parse message prose. The supported taxonomy and mutation coverage are documented in `AUDIT_REPORT_CONSUMER_COMPATIBILITY.md` and `tests/test_audit_report_consumer_taxonomy.py`.


### Cross-entry audit report invariants and integration simulation

The reference consumer enforces `error_count == len(errors)`, requires at least one core `SEE_ERRORS` check for `FAIL`, and requires diagnostics for `ERROR`. `consume_audit_report_json()` simulates a downstream consumer after strict parsing and validation, mapping PASS/FAIL/ERROR to 0/1/2 and grouping diagnostics by stable code. This is a local model-free simulation, not evidence of target-agent integration. See `tests/test_audit_report_consumer_integration.py`.

### D0-67 verifier CLI to consumer CLI end-to-end contract

`scripts/consume_audit_report.py` is a runnable reference consumer for reports emitted by `scripts/verify_evidence_bundle.py`. It reads a bounded JSON payload from stdin (default) or a report file, applies the same strict parser/schema/invariant checks as the library consumer, and writes a compact normalized result containing status, mapped exit code, error count, and diagnostic groups. Exit `0` means a validated PASS report, `1` means a validated FAIL report, and `2` means the report could not safely be consumed or an input/CLI error occurred. Consumer errors go to stderr as stable codes and do not emit a success-shaped JSON result. The end-to-end tests launch both CLIs as subprocesses and verify that producer and consumer exit statuses agree for PASS/FAIL reports; they also cover malformed input, file-vs-stdin parity, usage errors, and path-safe I/O failures. This is local CLI integration evidence, not target-agent integration.

### D0-68 CLI output atomicity and input parity

The verifier writes `--json-report` through a same-directory temporary file and atomic replacement. A failed replacement preserves an existing report and cleans up its temporary file. Output paths are checked against the verified bundle after canonicalizing the parent directory; final-component symlinks are replaced rather than followed, and parent symlinks cannot bypass bundle containment. The consumer's stdin and file modes must return the same stable error and exit status for malformed JSON, invalid UTF-8, and oversized input. See `tests/test_d0_68_cli_output_atomicity.py` for subprocess and failure-path regression tests.

D0-68 verification evidence: the exact distributable ZIP was freshly extracted and the full 391-test suite passed across seven non-overlapping groups (split execution was used because monolithic runs exceeded this environment's execution window). The final external discovery ledger records the package hash and verification checkpoint. This is local contract/CLI evidence only; real model inference and external agent integration remain unverified.

### D0-69 report destination races and atomic-failure fault injection

The verifier's report writer is exercised under deterministic race/fault injection: a final-component symlink is inserted immediately before `os.replace`, a parent alias is switched after destination resolution, and temporary-file creation, data write, `fsync`, and replacement failures are injected. The expected contract is that replacement does not follow a final-component symlink, the already-resolved parent is used after an alias swap, an existing report remains unchanged until successful atomic replacement, and staged temporary files are cleaned after failures. These are regression tests of local path/rename behavior; they do not claim protection against every hostile filesystem mutation, power-loss mode, network filesystem, or platform-specific rename semantic. See `tests/test_d0_69_report_race_faults.py`.

## Directory-FD anchored report writes (D0-70)

On POSIX platforms exposing `dir_fd` support for `open`, `unlink`, and atomic replacement, the evidence-bundle verifier opens the resolved report parent directory and creates, fsyncs, replaces, and cleans its staging file relative to that open directory descriptor. If an attacker renames that directory and installs a different directory or symlink at its former pathname after the descriptor is opened, the in-flight write remains anchored to the originally opened directory. The final report component is replaced as a directory entry rather than followed as a symlink.

Platforms without those capabilities use a documented same-directory path-based fallback. That fallback retains atomic replacement and cleanup behavior but does **not** claim resistance to parent-path replacement races. These guarantees are filesystem/platform dependent and do not prove crash durability, defend against every concurrent filesystem adversary, or establish production sandboxing.

### D0-71 through D0-80 report-writer contract audit

The focused regression matrix now checks directory-FD capability detection and rejection of unsupported runtimes, report-path containment, directory-open flags, exclusive staging creation with restrictive permissions, descriptor cleanup on replacement failure, fallback preservation/cleanup, exact UTF-8 JSON byte handling, zero-length atomic payload handling, parent-directory open failures, and documentation/contract drift. Platform-specific directory-FD cases are skipped when the runtime genuinely lacks the required primitives; monkeypatched capability tests explicitly pin the selected path so the tests exercise the intended branch. These checks establish local regression behavior only and do not prove all-platform filesystem semantics or production security.

D0-71..D0-80 batch verification: the final package was clean-extracted and verified with **414 passing tests** in six non-overlapping groups. Reproducible archive construction, manifest/CRC checks, schema/fixture parsing, Python compilation, and archive hygiene checks are recorded in `FINAL_TEST_EVIDENCE_REPORT.md`. Phase 0 remains OPEN / HOLD because this batch does not implement or verify real TTS inference, target-agent integration, cryptographic authenticity, or a production OS sandbox.

### D0-81 through D0-90 directory identity and atomic-writer hardening

- The POSIX writer now records the parent directory's device/inode before opening it and compares that identity with `fstat()` on the opened directory descriptor. If the directory entry is replaced between the identity check and open, the write fails closed before creating a stage file.
- Regression coverage exercises concurrent whole-file replacement, restrictive file mode, destination symlink replacement semantics, staging-name collisions and exhaustion, injected write failures, same-directory `dir_fd` replacement, directory destinations, and repeated payload round trips.
- The inode check narrows a specific pre-open replacement race; it is not a general defense against every hostile filesystem, privileged attacker, mount namespace change, network filesystem, or crash/power-loss scenario. Unsupported runtimes still use the documented path-based fallback with weaker race guarantees.

### D0-91 through D0-100 — report-writer integration and boundary contracts

The next report-writer batch adds regression checks for relative destination anchoring, parent-symlink containment, creation of missing parent directories, private permissions when replacing an existing broad-mode report, preservation of the previous report after an `fsync` failure, fallback descriptor cleanup if stream wrapping fails, fallback final-symlink semantics, CLI rejection of report paths inside the bundle, byte-identical stdout/file report serialization, and clean CLI failure behavior. These tests validate the local implementation and subprocess contract only; they do not establish cross-platform equivalence or production sandboxing. See `tests/test_d0_91_100_report_writer_contract.py`.

D0-91..D0-100 final verification: the distributable archive was freshly extracted and all tests passed in six non-overlapping groups: contracts/audit/docs **120 passed**; evidence bundle/provenance/schema **61 passed**; IPC/isolation/JSONL/fuzz/provider/runtime **175 passed**; report-writer regressions **51 passed**; verifier/consumer CLI **16 passed**; packaging **11 passed**. Aggregate: **434 passed**. Archive reproducibility, manifest/CRC, schema/fixture parsing, Python compilation, and archive-hygiene checks are recorded in `FINAL_TEST_EVIDENCE_REPORT.md`. Phase 0 remains OPEN / HOLD for real TTS inference, target-agent integration, cryptographic authenticity, and production OS sandbox evidence.

## D0-101..D0-130 — Model-independent synthesis orchestration

`voiceover_pipeline.py` adds an orchestration layer that can call an injected **real** TTS adapter, validate WAV bytes, split long text into bounded chunks, assemble compatible PCM WAV chunks, and write a SHA-256 audio manifest. It deliberately does not fake or claim an implementation of Qwen3-TTS, Chatterbox, or Kokoro. The adapter must actually run inference and expose `engine_id`, `supported_languages`, and `synthesize_wav(...)`.

Minimal integration outline:

```python
from voiceover_pipeline import PipelineRequest, run_pipeline

request = PipelineRequest(
    request_id="job_001", text="Hello world.", language="en", voice_id="voice_a"
)
result = run_pipeline(request, [your_real_adapter], "./output")
print(result.output_path, result.sha256, result.manifest_path)
```

The pipeline is model-independent and uses Python's standard library. It does not download models, discover voice catalogues, normalize loudness, remove silence, generate background music, create voiceovers by itself, or sandbox provider code. Adapter implementations are trusted application code and must enforce their own model/runtime constraints. The WAV assembler requires every chunk to use the same channel count, sample width, and sample rate; it does not resample or crossfade. The audio and manifest are individually atomically replaced, not committed as a single filesystem transaction. Run real inference and agent integration tests before treating any engine as supported in production.

## D0-131..D0-160 — optional real-engine adapters (inference not yet verified)

`tts_engine_adapters.py` adds lazy adapters for Qwen3-TTS, Chatterbox TTS, and Kokoro, along with an honest local dependency/cache probe (`scripts/probe_tts_engines.py`). The adapters call the upstream model APIs when the relevant optional dependencies and model weights are available. Imports do not load weights; probing does not download models. The Qwen language map is deliberately limited to its documented ten languages. Unsupported options (such as engine speed/seed where not wired) fail closed rather than being silently ignored. Kokoro language pipelines are cached per language; WAV serialization validates finite numeric audio and sample-rate bounds.

The 30 adapter contract tests use model-free fake objects. They are not proof of actual inference, audio quality, GPU behavior, package-version compatibility, or target-agent integration. Run `python scripts/probe_tts_engines.py --pretty` to inspect the local optional-dependency state. See `OPTIONAL_TTS_ENGINES.md` for setup boundaries and limitations. Phase 0 remains **OPEN / HOLD** pending real model inference and deployment verification.

## D0-191..D0-220 — PCM audio QA and real-inference acceptance gate

The audio inspector reports objective PCM/WAV properties only; it cannot prove pronunciation, intelligibility, emotion, translation accuracy, or subjective voice quality:

```bash
python scripts/inspect_voiceover_audio.py ./voiceover-output/voiceover.wav --pretty
```

It validates the WAV header and PCM frame count, then reports duration, SHA-256, peak, RMS, clipping-sample ratio, silent-frame ratio and warnings. It supports mono/stereo uncompressed PCM at 8/16/24/32-bit widths and sample rates from 8 kHz to 384 kHz. Inspection is byte-bounded and decodes samples incrementally.

Run one **real** inference attempt and verify the produced artifact plus its pipeline manifest:

```bash
python scripts/real_inference_smoke.py \
  --request request.json \
  --output-dir ./voiceover-output \
  --engine kokoro \
  --timeout-seconds 900 \
  --min-duration 0.05 \
  --max-duration 600 \
  --max-silence-ratio 0.98 \
  --max-clipping-ratio 0.01 \
  --report ./voiceover-output/inference-smoke-report.json --pretty
```

Exit codes: `0` = generated audio passed objective acceptance checks; `2` = request/artifact/quality failure; `3` = inference blocked (for example, no compatible optional engine package). A `PASS` requires a successful worker result, safe output path, valid decoded WAV, matching SHA-256/size, matching manifest identity/hash/size/metadata, plausible duration, and configured silence/clipping thresholds. A package being installed is **not** proof of inference; only a successful actual synthesis with a verified artifact sets `inference_verified=true`.

The smoke report is atomically written. A report path that collides with the audio output is rejected so the report cannot overwrite the generated audio. The runner and quality gate are not an OS sandbox, and signal metrics do not replace listening tests or human evaluation.

## TTS engine environment readiness (D0-221–D0-250)

The core package intentionally does not install optional neural engines. To inspect this machine without downloading weights or executing package installation:

```bash
python scripts/diagnose_tts_environment.py --pretty
python scripts/diagnose_tts_environment.py --engine kokoro --output-dir ./output --pretty
python scripts/diagnose_tts_environment.py --engine qwen3_tts --strict-engine-ready
```

The diagnostic reports Python/platform details, PyTorch device visibility, required distribution versions and missing dependencies for Kokoro, Chatterbox, and Qwen3-TTS, eSpeak/ffmpeg binaries, a bounded Hugging Face cache scan, and optional output disk capacity. `--write-json PATH` writes the report atomically. An install plan is printed only as a proposal; no installation is performed. Verify current upstream Python, OS, CPU/GPU, model size, and licensing requirements before using it.

Environment readiness is not inference verification. Only a real generated WAV independently inspected by `scripts/real_inference_smoke.py` can qualify as inference evidence.

### Request envelope compatibility note

`run_voiceover.py` accepts both the public version-1 `synthesis.request` envelope and legacy flat pipeline requests. For envelope requests, nested language/voice/speed/seed options are mapped explicitly and `deadline_ms` bounds the worker timeout. Reference audio is currently rejected explicitly rather than ignored; end-to-end reference-audio support is not yet implemented.

## D0-281–D0-310 — runtime discovery and install preflight

Added `tts_runtime_preflight.py`, `scripts/preflight_tts_install.py`, `schemas/tts-runtime-preflight-v1.schema.json`, and `tests/test_tts_runtime_preflight.py`. The preflight discovers known Python 3.10–3.12 interpreters without invoking a shell, probes module availability in isolated mode, checks approved PyPI/Hugging Face HTTPS endpoints with short timeouts, and inventories local wheelhouse files without executing them. It does not install packages or download model weights. Wheelhouse inventory is deliberately not described as compatibility validation: Python/ABI/platform tags, transitive closure, and wheel trust must still be verified before offline installation.

Run `python scripts/preflight_tts_install.py --engine kokoro --pretty --report ./preflight.json`. Use `--skip-network` for offline diagnostic mode, `--wheelhouse PATH` to inventory local wheels, or repeat `--python-candidate PATH` to probe a specific interpreter. Exit code 0 means declared engine prerequisites are present, 2 means the preflight found missing prerequisites or an unverified wheelhouse, and 3 means no supported interpreter or network readiness. These codes do not indicate that model inference works.

Historical D0-251–D0-280 environment snapshot: only Python 3.13.5 was then detected (outside this project's conservative 3.10–3.12 install policy), and DNS lookups to PyPI/Hugging Face failed. That diagnostic returned `NO_SUPPORTED_INTERPRETER`, `network_ready=false`, and `inference_verified=false`; no install or model download was attempted. This historical status is superseded by the fresh D0-401–D0-430 snapshot below.

## D0-251–D0-280 — explicit engine setup

The new `scripts/setup_tts_engine.py` prepares an isolated optional-engine environment. It is **plan-only by default** and will not run pip unless `--install` is explicitly supplied. It supports a local wheelhouse and `--no-index` for offline package installation, installs the declared required runtime distribution set, runs `pip check` and probes all declared required modules after installation, bounds command time/log output, and redacts common credential-like values from captured logs. It does not download model weights or mark inference verified.

Plan an install without changing the machine:

```bash
python scripts/setup_tts_engine.py --engine kokoro --environment .venvs/kokoro --python python3.12 --pretty
```

Explicitly opt in to package installation only after reviewing upstream requirements:

```bash
python scripts/setup_tts_engine.py --engine kokoro --environment .venvs/kokoro --python python3.12 --install --timeout-seconds 1800 --report kokoro-setup-report.json --pretty
```

Offline package installation requires a prepared wheelhouse containing the engine and all compatible dependencies:

```bash
python scripts/setup_tts_engine.py --engine kokoro --environment .venvs/kokoro --python python3.12 --install --wheelhouse ./wheelhouse --no-index
```

The current setup policy accepts Python 3.10–3.12 for the install attempt; this is a project guardrail, not a guarantee of upstream compatibility. A package-ready result means only that installation, `pip check`, and module discovery passed. Run `scripts/real_inference_smoke.py` with a compatible request in the selected venv to verify actual speech output. Network access to PyPI and Hugging Face was unavailable during D0-251–D0-280 verification, so no engine was installed and real inference remains blocked.

## D0-311–D0-340: real offline speech baseline (not neural inference)

This batch adds `scripts/offline_speech_probe.py`, a bounded diagnostic that can invoke a locally installed `espeak-ng` or `espeak` executable to create an actual WAV without internet access. It validates the output with the dependency-free PCM inspector before atomically publishing the audio, and can emit a separate JSON report:

```bash
python scripts/offline_speech_probe.py \
  --text "This is a local speech test." \
  --output ./output/offline-baseline.wav \
  --report ./output/offline-baseline-report.json --pretty
```

Use `--text-file PATH` for longer text, `--language en` (or a supported eSpeak language code), `--speed 165`, `--timeout 30`, and `--overwrite` only when replacement is intended. The tool does not use a shell, refuses to overwrite by default, validates non-silent PCM WAV output, and never places the transcript in the report. It uses atomic report writes and rejects report/audio path collisions.

**Interpretation:** a successful eSpeak probe confirms only that this machine can produce non-silent local system-TTS audio and that the WAV passes objective signal checks. eSpeak is a formant/system TTS baseline, not a neural engine. `neural_engine=false` and `inference_verified=false` remain fixed even when `speech_output_verified=true`. This baseline alone does not prove neural TTS; later real CPU WAV smokes verify one Kokoro English preset and one Qwen3-TTS VoiceDesign profile. Chatterbox, Qwen CustomVoice preset, subjective pronunciation/naturalness, and broad language coverage remain unverified.

## D0-371–400: Neural TTS Artifact Readiness

The harness includes `tts_artifact_readiness.py` and `scripts/inspect_tts_artifacts.py` for deterministic, non-installing local model-artifact checks. The initial D0-371–400 ledger listed a Kokoro ONNX/binary pair; the D0-401–430 adapter-source audit found that pair does not match this project's `KPipeline` adapter and corrected the inventory to Kokoro's `.pth` checkpoint and `.pt` voice layout, plus the required Qwen3-TTS and Chatterbox multilingual files. The inspector never downloads, installs, loads a model, or marks inference verified.

Model roots may be supplied with `--model-root` or `VOICEOVER_MODEL_ROOT` / `TTS_MODEL_ROOT`. If none is supplied, the inspector discovers the effective Hugging Face Hub cache (`HF_HUB_CACHE`, then `HF_HOME/hub`, then `XDG_CACHE_HOME/huggingface/hub`, then `~/.cache/huggingface/hub` when present). An explicit root is never silently replaced by another path. Symlink targets escaping the selected root are rejected; internal Hugging Face cache file links may be read safely. Version 2 reports each required-file group and, with `--hash-files`, hashes matched files only below the configured per-file byte limit. The compatibility-default v1 output shape is unchanged.

This is intentionally separate from package/dependency detection: runtime readiness, package/import readiness, artifact presence, model loading, real audio inference, and audio quality are distinct evidence gates. See [Offline Installation and Neural TTS Readiness](OFFLINE_INSTALL_AND_READINESS.md) for staged wheel/model guidance, expected statuses, privacy notes, and official model-layout sources.

## D0-401–430 — adapter-accurate artifact readiness and offline gate guide

This batch corrects the v2 artifact catalogue from the files actually used by the adapters: Kokoro `config.json`, `kokoro-v1_0.pth`, and `voices/*.pt`; Qwen3-TTS model/tokenizer files including the nested speech tokenizer; and Chatterbox multilingual checkpoints. Directory readiness now requires every declared file group, so a merely nonempty or incompatible model folder is not marked ready. Internal Hugging Face cache file symlinks are accepted only when resolved targets remain within the configured model root; external links remain unsafe. Optional v2 hashes identify the matched required files and are bounded per file. A separate isolated Kokoro environment and one real CPU smoke were used for final verification; the model weights are not included in this source package. See `OFFLINE_INSTALL_AND_READINESS.md` for the complete gate sequence, [D0-401–D0-430 task ledger](D0_401_430_TASK_LEDGER.md), and [test/inference evidence](D0_401_430_TEST_EVIDENCE.md).


## D0-401–D0-430 current environment snapshot

Fresh checks on 2026-10-10 found system Python 3.12.3, 8 CPU cores, about 20 GiB available RAM, no detected NVIDIA GPU, and 54 GiB free disk after the isolated engine setup. PyPI and Hugging Face had returned HTTP 200 in a bounded preflight. At the initial snapshot the expected caches and Kokoro packages were absent; a separate isolated environment then installed Kokoro 0.9.4, PyTorch 2.14.1, NumPy 2.5.3, SoundFile 0.14.0, Transformers 5.19.0, and Hugging Face Hub 2.2.0. The real Kokoro model was loaded from the effective app-scoped XDG/Hugging Face cache. The CPU-only synthetic English request with voice `af_heart` produced a 24 kHz mono PCM WAV of 4.225 seconds. All seven smoke checks passed: worker success, audio hash/size, manifest identity/metadata, duration match/range, decoded PCM frames, silence threshold, and clipping threshold. Audio SHA-256: `9d328112dd41f42c1d859c99ab2fcaf845646193e0f2096b3b09242cf843bf39`. The 327,212,226-byte checkpoint was present; v2 hashing skipped it under the 64 MiB cap while hashing the small config and voice files. A later D0-431–460 follow-up also verified one Qwen3-TTS VoiceDesign English CPU profile in the pinned environment using native BF16 weights. These verify one Kokoro preset and one prompt-designed Qwen profile, not subjective speech quality or broad language coverage. Chatterbox and Qwen CustomVoice preset remain unverified and are not exposed by the installed Skill; Phase 0 remains **OPEN / HOLD** for the other acceptance and product checks.


## D0-431–D0-460 — Installable Skill and plugin packages

The source Skill at `skills/voiceover-skill/` contains the platform-neutral workflow, reference documentation, a validated v2 sample request, and a generated icon. `scripts/package_voiceover_skill.py` creates four separate distributions outside the source tree: a standalone Agent Skill ZIP, a Claude Code Plugin ZIP, a MiniMax Code dual-layout ZIP for 0.3.x and 0.4.0+, and a native MiniMax Marketplace submission ZIP. The Code 0.3.x portable `plugin.json` intentionally contains only `$schema` and `name`, matching its closed schema. The Marketplace ZIP excludes the Code/Claude manifests so it remains in the documented native submission format. All packages exclude engine runtimes and model weights.

Build the Skill/plugin ZIPs and require byte-identical repeat builds:

```bash
python scripts/package_voiceover_skill.py --output-dir /path/to/voiceover_skill_distribution --check-reproducible
```

Build the reproducible source-project archive separately:

```bash
python scripts/build_package.py --output /path/to/voiceover_skill_distribution/voiceover_skill_source.zip --check-reproducible
```

The full source regression run for the verified-only follow-up passed **932 tests**, with **2 skipped** because eSpeak is not installed; the duplicate-ZIP-entry test emitted one expected Python warning. The Agent Skill validator passed. The updated four packages and source archive are rebuilt and clean-extraction-verified as recorded in the D0-461–470 follow-up evidence and release manifest. Direct Windows and macOS execution was not available, so those hosts are documented but not claimed as tested.

The first Qwen VoiceDesign CPU attempt used the default FP32 loader and was stopped by the unchanged 10-GiB process-tree RSS guard (`RESOURCE_LIMIT_EXCEEDED`, exit 137), with no WAV. The adapter was then changed to load the pinned checkpoint's native BF16 dtype on CPU; a profile-backed run completed under the same configured two-thread, 300-second, 10-GiB guard and passed all seven smoke checks. Its WAV is 24-kHz mono PCM16, 3.2 seconds, zero clipping, no inspection warnings, SHA-256 `a998c90bc521e1bf9bfcbf72fbf0c96d97a13c482cbd315ad03bc920dbdc2b73`; see `research/d0_431_460/qwen_voice_design_bf16_cpu_smoke_report.json`, `research/d0_431_460/qwen_voice_design_bf16_audio_inspection.json`, and the WAV under `research/d0_431_460/qwen_voice_design_bf16_smoke_output/`. The guard did not trigger, but the report did not retain a measured peak RSS, so no exact peak is claimed. Only Kokoro preset and Qwen text-designed VoiceDesign are exposed in the installable Skill; Chatterbox and Qwen CustomVoice preset remain unverified. Phase 0 remains **OPEN / HOLD** for broader acceptance and subjective review. The distribution contains no Android APK; it is a local Python-based desktop workflow.

### D0-461–D0-470 verified-only follow-up

The native-BF16 Qwen sample and the runtime/CLI gates that withhold unverified modes are recorded in the [task ledger](D0_461_470_TASK_LEDGER.md) and [bilingual evidence report](D0_461_470_TEST_EVIDENCE.md). The final package files and integrity results are listed in the companion release manifest.
