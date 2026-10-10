# D0-281–D0-310 Task Ledger

Batch objective: improve the path from setup tooling to a real engine by making the runtime blockers observable, deterministic, and safe. Source of truth for this batch is this package root. PASS means code/tests verified; BLOCKED means the actual environment prevents the desired external action. No model inference is claimed.

| Task | Work item | Status | Evidence / notes |
|---|---|---|---|
| D0-281 | Re-inspect previous batch's installation and inference blockers | PASS | Only Python 3.13.5 is on PATH; current policy accepts 3.10–3.12. |
| D0-282 | Confirm package-index reachability independently | PASS | Bounded HTTPS probes to PyPI and Hugging Face return DNS resolution failures. |
| D0-283 | Define a read-only runtime preflight contract | PASS | `tts_runtime_preflight.py`; explicit diagnostic-only flags. |
| D0-284 | Keep install, model download, and inference states separate | PASS | All report booleans are hard-coded false in diagnostic results. |
| D0-285 | Bound interpreter discovery and process calls | PASS | 8-second default, 1–30 second validated range, no shell. |
| D0-286 | Discover Python 3.10, 3.11, and 3.12 candidates on PATH | PASS | Deterministic candidate list and canonical-path deduplication. |
| D0-287 | Probe candidate interpreters in isolated mode | PASS | `-I -c` probe reports version, architecture, modules. |
| D0-288 | Add common POSIX and Windows candidate paths | PASS | Platform-specific candidate paths; missing paths ignored. |
| D0-289 | Rank supported interpreters before unsupported candidates | PASS | Stable preference for policy-supported version and newest version. |
| D0-290 | Report no-supported-interpreter state honestly | PASS | `NO_SUPPORTED_INTERPRETER` when no 3.10–3.12 runtime is found. |
| D0-291 | Add bounded PyPI HTTPS reachability probe | PASS | Short timeout; no package index content is read or logged. |
| D0-292 | Add bounded Hugging Face HTTPS reachability probe | PASS | Only approved HTTPS hosts are accepted. |
| D0-293 | Distinguish HTTP response from network/DNS failure | PASS | 4xx/5xx indicates reachable endpoint; DNS/timeout reported separately. |
| D0-294 | Prevent arbitrary URL probing via CLI-facing helper | PASS | URL allowlist is enforced in `probe_network`. |
| D0-295 | Avoid logging response bodies or credential-like data | PASS | Network result records status/error class only. |
| D0-296 | Add local wheelhouse inventory | PASS | Finds wheel filenames without importing or executing wheel code. |
| D0-297 | Bound wheelhouse inventory work | PASS | Maximum file count configurable within validated limits. |
| D0-298 | Ignore symlinked files and directories in wheelhouse scan | PASS | Symlink entries are not treated as installable wheels. |
| D0-299 | Normalize wheel distribution names for inventory | PASS | Basic filename-derived package-name normalization. |
| D0-300 | Explicitly warn that inventory is not compatibility validation | PASS | Wheel tags, transitive closure, and trust remain unchecked. |
| D0-301 | Combine interpreter, engine module, network, and wheelhouse facts | PASS | `collect_preflight()` returns one JSON-safe report. |
| D0-302 | Add `preflight_tts_install.py` CLI | PASS | Engine required; network skip, wheelhouse, extra interpreter, report, pretty options. |
| D0-303 | Add atomic JSON report writing | PASS | Same-directory temporary file, fsync, atomic replace, cleanup. |
| D0-304 | Add runtime preflight Draft 2020-12 JSON Schema | PASS | Schema checked against live diagnostic report. |
| D0-305 | Add CLI exit-code classification | PASS | 0 prerequisites present, 2 missing/partial prerequisites, 3 runtime/network blocked. |
| D0-306 | Add input-validation and error-path tests | PASS | Invalid candidate, timeout, URL, wheelhouse limits, and subprocess errors covered. |
| D0-307 | Add network and wheelhouse behavior tests | PASS | Reachable, HTTP error, DNS-like error, inventory, empty, missing, truncation. |
| D0-308 | Add no-false-inference schema tests | PASS | Schema rejects `inference_verified=true` in diagnostic output. |
| D0-309 | Update README and optional-engine guide | PASS | Usage, limitations, and current blockers documented. |
| D0-310 | Build and verify fresh release archive and full test groups | PASS | Fresh extraction verified; 724 tests passed in disjoint groups; ZIP/manifest/schema/compile/reproducibility checks passed. |

## Final fresh-extraction verification

- Total: **724 passed** across nine non-overlapping groups: audio/adapters/pipeline/preflight 151; audit/contracts/docs 66; evidence/schema 61; evidence CLI 10; runtime worker + IPC 101; JSONL + report-consumer E2E 84; isolation/protocol/provider 50; report-writer/packaging 62 (one expected duplicate-entry warning); setup/request mapping/environment/runtime preflight 139.
- The test suite was collected from the final ZIP extraction: **724 tests collected**. The monolithic suite was not used as a pass claim; all disjoint groups passed separately.
- Real smoke test: `BLOCKED / PREFERRED_ENGINE_UNAVAILABLE`, exit 3, no output directory/audio, `inference_verified=false`.

## Batch verdict

- Runtime preflight and its targeted tests: PASS.
- Current environment readiness for actual installation: BLOCKED (no Python 3.10–3.12 found; PyPI/Hugging Face DNS unavailable).
- Package installation: NOT ATTEMPTED (no compatible interpreter/network; no install side effects).
- Model download: NOT ATTEMPTED.
- Real audio generation: BLOCKED / NOT VERIFIED.
- Phase 0 remains OPEN / HOLD.
