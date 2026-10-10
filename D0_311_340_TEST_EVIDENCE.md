# D0-311–D0-340 Test Evidence Report

## Outcome

- New offline eSpeak probe: **7 focused tests passed** before schema test addition; after schema addition, new-probe + schema + documentation group: **18 passed**.
- Full source suite: **732 tests collected** and all 732 passed when run in bounded, non-overlapping groups. A single monolithic pytest process did not exit within the command timeout; it was not counted as a successful full-suite invocation. Each group was subsequently rerun individually and exited successfully.
- Package build: **PASS**. 100 SHA256 manifest entries; 101 ZIP members including the manifest; no duplicate paths; ZIP CRC pass; extracted manifest pass; two reproducible builds were byte-identical.
- Final archive SHA-256 is recorded in the external release note; it is not embedded in the package report to avoid a self-referential build hash.

## Real offline speech artifact

- Tool: local `espeak` system/formant TTS, invoked without a shell.
- Output: `voiceover_offline_baseline.wav`.
- Format: mono PCM, 16-bit, 22050 Hz.
- Duration: 5.926485261 seconds.
- Size: 261402 bytes.
- Peak normalized: 0.843226417; RMS normalized: 0.091866443; clipping ratio 0; all-silent false; warnings empty.
- WAV SHA-256: `7699335a0d8a54f3e87727a99c074bf94db27ca496785ec51723ff79c310a707`.
- Report: `voiceover_offline_baseline_report.json`.

## Critical interpretation

This run proves only that the installed local eSpeak system-TTS executable produced a valid, non-silent PCM WAV and that the audio inspector accepted it. It does not verify spoken-word intelligibility, pronunciation, semantic accuracy, or subjective quality. It is not a neural engine. The report correctly preserves `neural_engine=false` and `inference_verified=false`, while `speech_output_verified=true` records the actual local WAV result.

## Neural TTS blockers

- Runtime has Python 3.13.5 only; the project's current installation policy allows Python 3.10–3.12.
- No local wheelhouse was found.
- Approved PyPI and Hugging Face probes failed at DNS resolution in this environment.
- Kokoro, Chatterbox, and Qwen3-TTS packages/weights are not installed/verified; no neural inference was run.

## Test groups

| Group | Result |
|---|---:|
| Audio quality + offline probe | 60 passed |
| TTS adapters, environment, runtime preflight | 114 passed |
| Engine setup, request mapping, pipeline, runner | 124 passed |
| Audit diagnostics and report consumer | 111 passed |
| IPC, JSONL E2E, protocol fuzz, worker, schema | 173 passed |
| Evidence bundle/provenance/provider/isolation | 78 passed |
| Atomicity/report writer hardening | 51 passed |
| Packaging script | 11 passed (one expected duplicate-ZIP-name warning from its negative test) |
| CLI consumer E2E and documentation | 10 passed |
| **Total** | **732 passed** |

The counts above are the successful individual group runs; the standalone schema/documentation spot-check was an additional overlapping run and is not added to the total.
