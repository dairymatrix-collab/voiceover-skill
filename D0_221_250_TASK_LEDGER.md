# D0-221–D0-250 Task Ledger — TTS Environment Readiness

Batch intent: reduce the real-inference dependency blocker without silently installing packages, downloading model weights, or misreporting model-free tests as acoustic inference.

| Task | Implementation / acceptance condition | Status |
|---|---|---|
| D0-221 | Add read-only environment diagnostic core | PASS — covered by 32 environment tests |
| D0-222 | Define engine-specific setup metadata for Kokoro, Chatterbox, Qwen3-TTS | PASS — environment diagnostic tests |
| D0-223 | Enumerate engine distribution prerequisites | PASS — environment diagnostic tests |
| D0-224 | Ensure report JSON serialization is strict | PASS — environment diagnostic tests |
| D0-225 | Report missing distribution list per engine | PASS — environment diagnostic tests |
| D0-226 | Caveat Python-version compatibility rather than guarantee it | PASS — environment diagnostic tests |
| D0-227 | Install plan explicitly marks execution false | PASS — environment diagnostic tests |
| D0-228 | Include isolated virtual environment plan | PASS — environment diagnostic tests |
| D0-229 | Reject unknown engine IDs | PASS — environment diagnostic tests |
| D0-230 | Add bounded Hugging Face cache scan metadata | PASS — environment diagnostic tests |
| D0-231 | Probe ffmpeg and eSpeak executables | PASS — environment diagnostic tests |
| D0-232 | Report PyTorch CPU/CUDA/MPS state | PASS — environment diagnostic tests |
| D0-233 | Optionally inspect output disk space | PASS — environment diagnostic tests |
| D0-234 | Convert disk inspection errors into report checks | PASS — environment diagnostic tests |
| D0-235 | Make module probing robust to import errors | PASS — environment diagnostic tests |
| D0-236 | Skip symlink files during cache size scan | PASS — environment diagnostic tests |
| D0-237 | Report Python executable and architecture | PASS — environment diagnostic tests |
| D0-238 | Preserve correct Qwen package distribution name | PASS — environment diagnostic tests |
| D0-239 | Add CLI smoke test for JSON report | PASS — environment diagnostic tests |
| D0-240 | Add selected-engine install-plan output | PASS — environment diagnostic tests |
| D0-241 | Add strict missing-dependency exit contract | PASS — environment diagnostic tests |
| D0-242 | Add atomic JSON file output | PASS — environment diagnostic tests |
| D0-243 | Reject non-finite JSON numbers | PASS — environment diagnostic tests |
| D0-244 | Cache check reports directory presence only | PASS — environment diagnostic tests |
| D0-245 | Warn that upstream compatibility must be reviewed | PASS — environment diagnostic tests |
| D0-246 | Never mark inference verified from diagnostics | PASS — environment diagnostic tests |
| D0-247 | Report physical-memory estimate conservatively | PASS — environment diagnostic tests |
| D0-248 | Report unwritable output path structurally | PASS — environment diagnostic tests |
| D0-249 | Keep install commands as argv arrays, not shell strings | PASS — environment diagnostic tests |
| D0-250 | End-to-end CLI confirms setup plan has no install side effect | PASS — environment diagnostic tests |

## Evidence rule

A `PASS` on these tests means the diagnostic/setup-planning code behaved as specified. It does **not** mean any neural engine was installed, model weights were downloaded, or speech inference succeeded. Real inference remains blocked until a target engine is installed in a compatible environment and the smoke script validates an actual generated audio file.


## Batch result

All 30 numbered tasks are implemented. The environment test module contains 32 passing tests, including two schema conformance checks. Additional regression suites were run separately: adapter tests 30 passed, pipeline tests 30 passed, and preflight/runner tests 39 passed. The real TTS engine packages are still missing in the tested runtime, so actual audio generation remains BLOCKED.

## Critical integration correction discovered during real smoke testing

The first smoke attempt exposed a request-contract mismatch: the public schema uses `engine_id` plus nested `options`, while the internal pipeline expects flat `language` and `voice_id` fields. `scripts/run_voiceover.py` now explicitly normalizes the public envelope, validates version/IDs/engine/options/deadline, maps the selected engine, and caps worker timeout by `deadline_ms`. Legacy flat requests still work. Non-null reference audio fails closed until its safe end-to-end implementation exists. The added `tests/test_request_mapping.py` contains 18 passing cases, and the smoke test now reaches the expected dependency status (`PREFERRED_ENGINE_UNAVAILABLE`) instead of `INVALID_REQUEST_JSON`.

## Final fresh-extraction verification

The final package's tests were run in non-overlapping groups against a fresh extraction, all successful: core audio/adapters/pipeline 112; audit/contracts/docs 120; evidence/schema 61; evidence CLI 10; IPC 84; JSONL consumer E2E 30; isolation/protocol/provider/runtime 67; report-writer/packaging 62 (one expected duplicate-ZIP-entry warning); environment diagnostics 32; request mapping 18; preflight/runner 39. **Total: 635 passed.** The real-inference smoke check remains BLOCKED because the selected Kokoro engine package is missing; no WAV was generated.
