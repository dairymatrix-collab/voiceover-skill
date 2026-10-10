# D0-161..D0-190 Task Ledger — Readiness and Bounded Runner

This ledger distinguishes model-free code verification from actual model inference. Task status PASS means the listed local acceptance check was implemented and exercised in the current source tree; it does not mean a real TTS model has generated audio.

| Task | Implementation / acceptance check | Evidence | Status |
|---|---|---|---|
| D0-161 | Add versioned preflight report structure | `test_preflight_schema_and_engine_count` | PASS |
| D0-162 | Probe output directory write access without leaving a temp file | `test_preflight_write_check_creates_parent`; local smoke | PASS |
| D0-163 | Report Python and JSON runtime readiness | `test_preflight_reports_runtime_version`, `test_preflight_report_is_json_serializable` | PASS |
| D0-164 | Report optional FFmpeg capability without requiring it for WAV | Local preflight output and stable check ID | PASS |
| D0-165 | Detect PyTorch CPU/GPU capability conservatively | Local preflight output reported CPU; `require_gpu` path implemented | PASS |
| D0-166 | Enumerate all three optional engine probes | `test_preflight_schema_and_engine_count` | PASS |
| D0-167 | Never infer inference success from package presence | `test_preflight_never_claims_inference`; probe CLI tests | PASS |
| D0-168 | Validate an explicitly requested engine ID | unknown/missing/present engine tests | PASS |
| D0-169 | Expose machine-readable preflight JSON | `test_cli_preflight_json_contract` | PASS |
| D0-170 | Require worker input to be a JSON object | `test_worker_does_not_emit_traceback_on_bad_input` | PASS |
| D0-171 | Require explicit output directory in worker payload | `test_worker_requires_output_directory` | PASS |
| D0-172 | Validate request file existence/UTF-8/JSON | `test_runner_invalid_request_file_is_structured` | PASS |
| D0-173 | Bound the worker wall-clock time | timeout execution wrapper + injected timeout test | PASS |
| D0-174 | Return stable `INFERENCE_TIMEOUT` result | `test_runner_timeout_is_reported_without_traceback` | PASS |
| D0-175 | Launch worker using argv array, never shell interpolation | code inspection; `test_output_request_path_not_used_as_subprocess_command` | PASS |
| D0-176 | Pin worker entry point to package-relative script | `WORKER = ROOT / scripts / voiceover_worker.py`; CLI smoke | PASS |
| D0-177 | Resolve output directory before sending it to worker | runner implementation; valid-request integration test | PASS |
| D0-178 | Detect invalid worker stdout protocol | `test_runner_invalid_worker_stdout_is_protocol_error` | PASS |
| D0-179 | Preserve worker return code and valid structured result | `test_runner_valid_worker_stdout_is_forwarded` | PASS |
| D0-180 | Avoid exposing worker tracebacks for malformed input | worker structured-error test | PASS |
| D0-181 | Reject malformed JSON at worker boundary | `test_worker_invalid_json_is_structured` | PASS |
| D0-182 | Reject requests that omit output directory at worker boundary | `test_worker_requires_output_directory` | PASS |
| D0-183 | Delegate synthesis to validated pipeline + real adapter registry | code path integration; existing pipeline/adapter tests | PASS — boundary only |
| D0-184 | Fail without fabricated audio when engines are unavailable | `test_real_run_fails_cleanly_when_engines_missing`; local probe | PASS — dependency failure path |
| D0-185 | Keep probe output honest for Qwen3-TTS, Chatterbox, Kokoro | three engine probe tests | PASS |
| D0-186 | Enforce `--require-any-package` exit semantics | `test_probe_require_any_package_exit_contract` | PASS |
| D0-187 | Treat command-like request text as data, not shell syntax | `test_output_request_path_not_used_as_subprocess_command` | PASS |
| D0-188 | Document setup, commands, inherited environment and sandbox limits | README D0-161..D0-190 section | PASS |
| D0-189 | Include new source and regression tests in deterministic package | reproducibility build and extracted manifest check | PASS |
| D0-190 | Fresh extraction, SHA256SUMS, CRC, compilation and regression groups | see final evidence checkpoint appended after release verification | PASS |

## Execution result

Focused tests completed: `PYTHONPATH=. pytest -q -p no:cacheprovider tests/test_voiceover_preflight_runner.py tests/test_tts_engine_adapters.py tests/test_voiceover_pipeline.py` — **99 passed in 15.63s**.

Local readiness result: `BLOCKED_DEPENDENCIES`; the three optional TTS packages are absent. `inference_verified` remains false for each engine. No model download or real inference was attempted in this batch.


### Exact package checkpoint

- Reproducible ZIP build passed twice byte-for-byte. SHA-256 at the first packaged checkpoint: `da9cb0a76b5276b0986d57b02037998652a8656a7f7380a7074c01f127ef7260` (the release hash is recalculated after this ledger/report update).
- Fresh extraction passed manifest verification, ZIP CRC, no duplicate ZIP names, and Python compilation.
- Non-overlapping groups from the fresh extraction passed all **533 tests**: preflight + adapters + pipeline **99**; audit/contracts/docs **120**; evidence/provenance/schema **61**; evidence CLI **10**; IPC **84**; isolation **16**; JSONL E2E **24**; protocol fuzz **17**; provider conformance **17**; runtime worker **17**; report-writer regressions **51**; CLI consumer E2E **6**; packaging **11**.
- A single monolithic `pytest -q` run hit the execution time limit at about 67%; no monolithic-pass claim is made. Every test file was covered by the separate completed groups listed above.
- Actual Qwen3-TTS, Chatterbox, and Kokoro inference remains **NOT TESTED / BLOCKED_DEPENDENCIES**. Phase 0 remains **OPEN / HOLD**.
