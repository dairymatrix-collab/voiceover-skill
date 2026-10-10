# D0-311–D0-340 Task Ledger

Batch goal: establish a real, offline, auditable speech-output baseline without misrepresenting it as Kokoro, Chatterbox, or Qwen3-TTS inference.

| Task | Item | Status | Evidence |
|---:|---|---|---|
| D0-311 | Inspect final package and runtime blockers | PASS | Python 3.13.5 only; no supported 3.10–3.12 interpreter found |
| D0-312 | Recheck approved network endpoints | BLOCKED | PyPI/Hugging Face DNS probes fail in this environment |
| D0-313 | Check local wheelhouse | BLOCKED | No project wheelhouse available |
| D0-314 | Check local speech binaries | PASS | `/usr/bin/espeak` and FFmpeg present |
| D0-315 | Define offline baseline scope and limitation | PASS | Explicitly non-neural and diagnostic-only |
| D0-316 | Add bounded eSpeak subprocess invocation | PASS | argv list, shell disabled, timeout |
| D0-317 | Validate text type, NUL, blank text, length | PASS | Regression tests |
| D0-318 | Validate supported language codes | PASS | Regression tests |
| D0-319 | Validate speed range and boolean rejection | PASS | Regression tests |
| D0-320 | Validate timeout range | PASS | Regression tests |
| D0-321 | Validate output extension | PASS | CLI/library validation |
| D0-322 | Refuse symlink output | PASS | Regression test |
| D0-323 | Refuse existing output by default | PASS | Regression test |
| D0-324 | Protect against late output-path collision | PASS | Atomic hard-link publication when overwrite is false |
| D0-325 | Generate to temporary WAV first | PASS | Final path published only after audio inspection |
| D0-326 | Bound generated audio size | PASS | 50 MB limit |
| D0-327 | Validate PCM WAV using existing inspector | PASS | Real WAV inspected |
| D0-328 | Reject silent output | PASS | RMS/peak/all-silent checks |
| D0-329 | Compute SHA-256 | PASS | Report digest matches artifact |
| D0-330 | Report true audio format/duration/levels | PASS | WAV metrics in output report |
| D0-331 | Keep neural inference claim false | PASS | `inference_verified=false` invariant |
| D0-332 | Mark system TTS distinctly | PASS | `engine_id=espeak_offline`, `neural_engine=false` |
| D0-333 | Keep transcript out of report | PASS | CLI regression test |
| D0-334 | Add atomic JSON report writing | PASS | Temporary file + fsync + replace |
| D0-335 | Prevent report/audio path collision | PASS | Regression test |
| D0-336 | Add machine-readable JSON schema | PASS | Schema validation included in suite |
| D0-337 | Add CLI integration test | PASS | Actual eSpeak invocation when available |
| D0-338 | Generate a real local speech WAV | PASS | 22050 Hz mono PCM, 5.926 s, non-silent |
| D0-339 | Run focused regression tests | PASS | 7 passed |
| D0-340 | Keep neural TTS acceptance status honest | PASS / OPEN | Neural engine still blocked by runtime/network/dependency constraints |

## Batch outcome

The local eSpeak baseline successfully generated and validated `/mnt/data/voiceover_offline_baseline.wav` during this environment run. SHA-256: `7699335a0d8a54f3e87727a99c074bf94db27ca496785ec51723ff79c310a707`. This proves only real offline system-TTS output, not neural TTS model inference. The target neural inference remains BLOCKED.
