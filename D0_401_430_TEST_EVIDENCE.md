# D0-401–D0-430 Test and Inference Evidence

## Full source test suite

All **44 test modules** ran in three disjoint groups after the fixes:

| Group | Test modules | Result |
|---|---:|---|
| 1 | 15 | 221 passed |
| 2 | 15 | 275 passed, 2 skipped, 1 expected duplicate-ZIP-entry warning |
| 3 | 14 | 311 passed |
| **Total** | **44** | **807 passed, 2 skipped, 0 failed** |

The two skips are actual eSpeak synthesis tests because no `espeak-ng`/`espeak` executable is installed. Offline output-collision and symlink safety tests still ran and passed. The duplicate ZIP warning is emitted by the archive-rejection test fixture and is expected.

Focused verification also completed: virtualenv/runtime preflight group **60 passed**; cache, artifact-v1/v2, runtime-preflight-v1/v2, interpreter-venv, and documentation group **123 passed**; offline-speech-probe tests **6 passed, 2 skipped**.

## Kokoro model and runtime

A dedicated Python 3.12.3 virtual environment contained Kokoro 0.9.4, PyTorch 2.14.1, NumPy 2.5.3, SoundFile 0.14.0, Transformers 5.19.0, and Hugging Face Hub 2.2.0. The host had 8 CPU cores and no detected NVIDIA GPU. This was an isolated environment; the project package does not bundle these runtime distributions or model weights.

The local-only artifact-v2 inspection returned `ARTIFACTS_READY` for Kokoro and found `config.json`, `kokoro-v1_0.pth` (327,212,226 bytes), and a voice tensor (523,425 bytes). Config and voice hashes completed; the checkpoint hash was skipped because it is larger than the 64 MiB per-file limit. This inspection is artifact presence evidence only, not proof of model loading.

The runtime install preflight used the explicit isolated Kokoro interpreter with network probes skipped and returned exit 0: `ENGINE_PREREQUISITES_PRESENT`. Its nested artifact report was `ARTIFACTS_READY`. This preflight does not load a model or synthesize audio.

## Real inference and independent audio inspection

A generic, synthetic English request ran through the project's actual voiceover worker and the real cached Kokoro checkpoint on CPU using voice `af_heart`. The real-inference smoke returned `PASS`, worker return code 0, and `inference_verified=true`. All seven checks passed: audio integrity, manifest integrity, duration match/range, non-silence threshold, clipping threshold, and WAV decode/frame count. The evidence JSON is `D0_401_430_KOKORO_SMOKE_REPORT.json`.

A separate invocation of `scripts/inspect_voiceover_audio.py` independently decoded the output: mono 16-bit PCM WAV, 24,000 Hz, 101,400 frames, 4.225 seconds, 202,844 bytes, not silent, clipping ratio 0.0, no warnings. SHA-256: `9d328112dd41f42c1d859c99ab2fcaf845646193e0f2096b3b09242cf843bf39`. The path-redacted inspection JSON is `D0_401_430_KOKORO_AUDIO_INSPECTION.json`. The sample WAV is kept separately from the source package.

The first worker smoke exposed TTS-library progress contaminating the one-line JSON IPC response. The worker now redirects that output to stderr; a regression test covers it, and the real smoke passed on retry. The offline system-TTS probe also had a validation-order defect: when eSpeak was absent it returned `BLOCKED` before rejecting an existing or symlink output. Validation now occurs first, and the tests pass.

## Evidence limits

This confirms one local Kokoro CPU English path only. It does not establish subjective naturalness, pronunciation, broad language or voice support, Qwen3-TTS/Chatterbox inference, or offline operation. The model and voice weights are not included in the package. Prompt-based custom-voice design remains a separate follow-on feature under model evaluation.

## Release package checks

The deterministic archive build, manifest/CRC verification, reproducibility, fresh extraction, and extracted-suite results are recorded here after the release archive has been built.


### Reproducible archive and fresh-extraction verification

The final release archive is built after this evidence is included. The standard-library packager verifies ZIP metadata/CRC and the extracted `SHA256SUMS` manifest. The last two reproducibility builds were byte-identical and contained 126 manifest entries (127 ZIP members). A clean extraction compiled 78 Python files, validated all 16 JSON schemas, and reran all 44 test modules in three disjoint groups: 221, 275 (plus the same two eSpeak skips), and 311 passed. **Extracted total: 807 passed, 2 skipped, 0 failed.** The enclosing archive SHA-256 is recorded outside the package to avoid embedding a self-referential build hash.
