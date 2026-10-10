# D0-401–D0-430 Task Ledger

## Mission
Complete the existing neural-TTS artifact/readiness batch, verify one real neural synthesis path, harden preflight/path handling, and release the updated source package without overstating what the checks prove.

| Task | Work | Status | Evidence |
|---:|---|---|---|
| 401 | Re-validate the supplied package archive and extract a clean working copy | VERIFIED | ZIP integrity, member inventory, SHA-256 manifest |
| 402 | Re-read continuation instructions, prior ledgers, and package contracts | VERIFIED | Uploaded continuation note; D0-371–400 ledger |
| 403 | Snapshot current Python, CPU, RAM, disk, GPU, and model-cache state | VERIFIED | Read-only environment probes |
| 404 | Review artifact, preflight, setup, pipeline, adapter, CLI, and schema boundaries | VERIFIED | Source review; existing focused tests |
| 405 | Verify Kokoro `KPipeline` checkpoint/config/voice layout from official sources | VERIFIED | `D0_401_430_EXTERNAL_SOURCE_NOTES.md` |
| 406 | Verify Qwen3-TTS model/tokenizer and nested speech-tokenizer assets | VERIFIED | Official repository and checkpoint-tree notes |
| 407 | Verify Chatterbox multilingual loader files separately from English loader files | VERIFIED | Official loader and checkpoint-tree notes |
| 408 | Record model-layout corrections and source/evidence limits | VERIFIED | `D0_401_430_EXTERNAL_SOURCE_NOTES.md` |
| 409 | Replace incompatible Kokoro ONNX inventory with `.pth`/`.pt` adapter layout | VERIFIED | `tts_artifact_readiness.py`; v1/v2 tests |
| 410 | Make Qwen3-TTS and Chatterbox required artifact groups adapter-accurate | VERIFIED | Artifact catalog; schema and regression tests |
| 411 | Require every declared file group; classify incomplete model directories honestly | VERIFIED | `ARTIFACTS_INCOMPLETE` coverage |
| 412 | Support bounded traversal of internal Hugging Face snapshot/blob links | VERIFIED | Descriptor-anchored scanner tests |
| 413 | Keep fallback traversal symlink-safe, deterministic, and bounded | VERIFIED | Portable scanner tests |
| 414 | Report encountered symlinks, matched asset paths, and candidate issues accurately | VERIFIED | Artifact-v2 tests and schemas |
| 415 | Add size-bounded SHA-256 for matched directory assets and race detection | VERIFIED | Hash-limit and mutation-race tests |
| 416 | Synchronize artifact-v2 and nested runtime-preflight-v2 schemas | VERIFIED | JSON Schema and runtime integration tests |
| 417 | Expose artifact aliases/options, atomic reports, and honest CLI exit codes | VERIFIED | Inspector/preflight CLI tests |
| 418 | Resolve the effective Hugging Face cache from supported environment variables | VERIFIED | `cache_paths.py`; `test_hf_cache_detection.py` |
| 419 | Reuse cache resolution in artifact readiness, diagnostics, and Qwen cache probes | VERIFIED | Cache detection and environment/adapter tests |
| 420 | Make explicit model-root selection strict instead of silently falling through | VERIFIED | Missing-explicit-root and configured-cache precedence tests |
| 421 | Preserve virtual-environment executable paths when probing symlinked Python | VERIFIED | `tts_runtime_preflight.py` |
| 422 | Add a regression that verifies the active venv's installed modules are observed | VERIFIED | `test_interpreter_venv_resolution.py` |
| 423 | Select the isolated Kokoro interpreter in artifact-enabled runtime preflight | VERIFIED | Exit 0; `ENGINE_PREREQUISITES_PRESENT`; `ARTIFACTS_READY` |
| 424 | Protect worker JSON IPC from TTS-library progress written to stdout | VERIFIED | Worker redirects library stdout; protocol regression test |
| 425 | Document offline install, cache resolution, asset layouts, and distinct readiness gates | VERIFIED | `OFFLINE_INSTALL_AND_READINESS.md`; README contract tests |
| 426 | Declare NumPy/SoundFile test dependencies and update stale environment claims | VERIFIED | `requirements-dev.txt`; README/docs tests |
| 427 | Reject unsafe offline-speech output paths before returning missing-engine status | VERIFIED | Existing-file/symlink tests; targeted suite 6 passed, 2 environment skips |
| 428 | Run every source test module in three disjoint groups after fixes | VERIFIED | 44 modules; 807 passed, 2 skipped, 0 failed |
| 429 | Load Kokoro weights and synthesize one CPU-only synthetic English sample | VERIFIED | `D0_401_430_KOKORO_SMOKE_REPORT.json`; `inference_verified=true` |
| 430 | Independently inspect audio and verify reproducible release archive/fresh extraction | VERIFIED | `D0_401_430_KOKORO_AUDIO_INSPECTION.json`; final release evidence outside ZIP |

## Scope and limits

- The real-inference claim applies to one Kokoro 0.9.4 English CPU profile (`af_heart`) only. Qwen3-TTS and Chatterbox inference remain unverified.
- No subjective listening, pronunciation, intelligibility, or quality ranking is claimed by the objective WAV checks.
- The offline eSpeak executable is absent, so its two real-synthesis tests skip; path-safety tests pass even without eSpeak.
- No Android source tree, Gradle project/wrapper, Android SDK, or Android build tools were present. A genuine APK is therefore not produced; no placeholder APK is substituted.
- Prompt-based custom-voice design is a separate follow-on scope. Model selection and integration are tracked after this batch; this ledger does not claim that feature exists.

## Completion
Exactly 30 tasks (D0-401–D0-430) are recorded above. Full test, smoke, independent-audio, reproducible-archive, and fresh-extraction results are summarized in `D0_401_430_TEST_EVIDENCE.md` and `FINAL_TEST_EVIDENCE_REPORT.md`.
