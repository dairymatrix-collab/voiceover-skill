# D0-191–D0-220 Task Ledger — Audio QA and Real-Inference Gate

**Batch status: PARTIAL / BLOCKED at D0-220.** The acceptance tooling is implemented and tested, but this environment has none of the optional TTS packages installed. No real speech output was generated, and the batch is not marked fully complete for actual inference.

| Task | Acceptance criterion | Verification evidence | Status |
|---|---|---|---|
| D0-191 | Versioned objective audio-quality report and stable errors | report structure and JSON serialization tests | PASS |
| D0-192 | Parse PCM WAV and reject invalid headers/data | invalid WAV, empty payload and truncated-data contracts | PASS |
| D0-193 | Accept mono and stereo PCM only | parametrized channel tests | PASS |
| D0-194 | Support 8/16/24/32-bit PCM sample widths | parametrized sample-width tests | PASS |
| D0-195 | Bound supported sample rates to 8–384 kHz | common-rate tests and validation | PASS |
| D0-196 | Bound inspection by payload and declared PCM size | max-bytes tests and header size guard | PASS |
| D0-197 | Decode PCM incrementally without a second full sample list | `_iter_pcm` implementation and width tests | PASS |
| D0-198 | Report normalized peak and RMS | non-silent signal metric tests | PASS |
| D0-199 | Report clipping-sample ratio and warning | clipping fixture test | PASS |
| D0-200 | Report silent-frame ratio | silent and mixed-signal tests | PASS |
| D0-201 | Flag all-silent, near-silent and very-low-RMS audio | warning generation tests | PASS |
| D0-202 | Provide JSON audio-inspection CLI | CLI success/error tests | PASS |
| D0-203 | Define and validate audio-quality JSON schema | `jsonschema.validate` test and schema check | PASS |
| D0-204 | Provide a real-inference smoke CLI with configurable gates | CLI help and smoke evaluator tests | PASS |
| D0-205 | Reject malformed/non-object request JSON | runner contract suite and smoke request validation | PASS |
| D0-206 | Launch worker without shell interpolation | fixed runner path and argv-list subprocess code | PASS |
| D0-207 | Apply bounded timeout and structured timeout result | inherited runner timeout tests and smoke timeout handling | PASS |
| D0-208 | Distinguish missing engine dependencies from synthesis failures | missing-engine result classified BLOCKED | PASS |
| D0-209 | Reject generated audio outside the expected output directory | output containment regression test | PASS |
| D0-210 | Verify audio SHA-256 and byte size against worker result | integrity success and mismatch tests | PASS |
| D0-211 | Require a safe, present pipeline manifest | manifest path and absence checks | PASS |
| D0-212 | Cross-check manifest request/engine identity, digest, size, rate, frames and duration | manifest verification code and successful fixture reports | PASS |
| D0-213 | Enforce minimum/maximum generated-audio duration | short/long duration gate tests | PASS |
| D0-214 | Compare decoded WAV duration with pipeline duration | duration consistency check in evaluator | PASS |
| D0-215 | Enforce configurable silent-frame ratio | silence gate test | PASS |
| D0-216 | Enforce configurable clipping-sample ratio | clipping gate test | PASS |
| D0-217 | Write reports atomically and leave no staging file | atomic writer tests | PASS |
| D0-218 | Prevent report path from overwriting the generated audio | collision injection test | PASS |
| D0-219 | Define and validate smoke-report JSON schema | success/failure schema tests | PASS |
| D0-220 | Execute real inference and inspect generated audio in this environment | actual attempt returned `NO_COMPATIBLE_ENGINE`; all three optional packages absent | BLOCKED |

## Verification checkpoint

- Audio-QA tests after manifest checks: **52 passed**.
- Combined focused suite after final manifest checks: **151 passed**.
- Fresh-extracted package regression groups all completed: **585 passed** (151 audio/preflight/adapters/pipeline; 120 audit/contracts/docs; 61 evidence/schema; 10 evidence CLI; 84 IPC; 30 JSONL/consumer E2E; 67 isolation/protocol/provider/runtime; 62 report-writer/packaging).
- Release archive checks: 80 ZIP members; 0 duplicate names; CRC PASS; 79/79 SHA256SUMS entries verified; 54 Python files compiled; both new JSON schemas pass Draft 2020-12 schema checks; reproducible build PASS with byte-identical outputs.
- Local actual-inference attempt: `BLOCKED`, exit code `3`, error `NO_COMPATIBLE_ENGINE`; `inference_verified=false`; no audio artifact produced.
- Objective signal metrics cannot establish pronunciation, intelligibility, prosody, translation correctness or subjective quality. Listening/human review remains a separate acceptance stage.
- Phase 0 remains **OPEN / HOLD** until a supported environment installs/pins at least one engine, runs real synthesis, verifies its generated WAV/manifest and receives a human listening check.
