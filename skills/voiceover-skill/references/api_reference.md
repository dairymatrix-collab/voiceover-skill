# Voiceover Backend API Reference

The installed Skill exposes only profile modes that have passed real WAV smoke acceptance: Kokoro `preset` and Qwen3-TTS `voice_design`. All profile-backed runs use a killable subprocess, a single-job lock, per-engine resource preflight, bounded CPU threads/chunking, local profile storage, and structured JSON. Model weights are not bundled.

## Verified runtime modes and evidence

| Engine | Profile mode | Real inference evidence | Controls |
|---|---|---|---|
| `kokoro` | `preset` | One English CPU profile (`af_heart`) produced a WAV that passed seven objective smoke checks. | `speed`: 0.5–2.0; only the default 1.0 was used in the real smoke. |
| `qwen3_tts` | `voice_design` | One English prompt-designed profile produced a 3.2-second CPU WAV that passed seven smoke checks and independent WAV inspection. The CPU adapter loads the pinned VoiceDesign checkpoint in its saved BF16 dtype. | `top_k`, `top_p`, `temperature`, `repetition_penalty`, `max_new_tokens`; the real smoke used defaults. |

These are bounded path checks on the current host, not guarantees of subjective naturalness, pronunciation, speaker identity, all languages/settings, long-run stability, or performance on another computer. Qwen CustomVoice preset, Chatterbox preset/reference cloning, and direct v1 Qwen synthesis remain unavailable in the Skill runtime until separately accepted WAV smokes pass. Their research/adapter code is not a supported user route.

## Runtime and resource preflight

Use Python 3.10–3.12 in a dedicated environment. Install backend helper dependencies with:

```text
python -m pip install -r "<SKILL_DIR>/backend/requirements-skill.txt"
```

Run a read-only resource check before package setup, model download, or inference:

```text
python3 "<SKILL_DIR>/backend/scripts/preflight_tts_resources.py" --engine qwen3_tts --pretty
python3 "<SKILL_DIR>/backend/scripts/preflight_tts_resources.py" --engine kokoro --pretty
```

The Qwen CPU policy used for the accepted sample required at least a 14-GiB available-RAM preflight, two CPU threads, a fixed 10-GiB process-tree RSS guard, and a 300-second deadline. Do not raise any limit. A completed run did not trigger the guard; the smoke report does not include a measured peak RSS, so do not invent or infer an exact peak value.

## Setup and artifact readiness

For Qwen CPU setup, choose a new or empty destination. Without `--install`, the command is plan-only. Install only after the user requested or authorized package acquisition:

```text
python3 "<SKILL_DIR>/backend/scripts/setup_tts_engine.py" --engine qwen3_tts --environment "<NEW_ENV>" --python "<PYTHON_3_12>" --install --cpu-only --report "<REPORT_DIR>/qwen-setup.json" --pretty
```

Read-only interpreter/runtime and pinned artifact checks:

```text
python3 "<SKILL_DIR>/backend/scripts/diagnose_tts_environment.py" --pretty
python3 "<SKILL_DIR>/backend/scripts/preflight_tts_install.py" --engine qwen3_tts --skip-network --include-artifacts --model-variant voice_design --pretty
```

Add `--model-root "<HF_HUB_CACHE>"` when the model cache is not discovered automatically. A passing artifact report means only that required files were found; it does not load weights or establish inference.

## Explicit model acquisition

Show the read-only plan first. Qwen VoiceDesign uses the audited immutable revision. Download only after authorization for the multi-gigabyte acquisition and a fresh resource preflight:

```text
python3 "<SKILL_DIR>/backend/scripts/download_tts_model.py" --engine qwen3_tts --variant voice_design --plan-only --pretty
python3 "<SKILL_DIR>/backend/scripts/download_tts_model.py" --engine qwen3_tts --variant voice_design --download --python "<ENGINE_PYTHON>" --timeout-seconds 1800 --report "<REPORT_DIR>/qwen-download.json" --pretty
```

The downloader enforces its pinned revision, file allowlist, byte/disk/RAM gates, single-job lock, local cache containment, and finite timeout. A successful download is artifact evidence, not inference evidence. Do not resume partial files or bypass limits manually. Kokoro's verified preset has a separate pinned catalog entry; use the same plan-first and resource-gated flow when its local checkpoint is absent:

```text
python3 "<SKILL_DIR>/backend/scripts/download_tts_model.py" --engine kokoro --variant preset --plan-only --pretty
python3 "<SKILL_DIR>/backend/scripts/download_tts_model.py" --engine kokoro --variant preset --download --python "<ENGINE_PYTHON>" --timeout-seconds 1800 --report "<REPORT_DIR>/kokoro-download.json" --pretty
```

## Create and reuse verified profiles

Create Qwen VoiceDesign from a private UTF-8 prompt file. The CLI reads at most 1,600 characters, rejects symlink/non-file inputs, and does not echo the prompt in the create response:

```text
python3 "<SKILL_DIR>/backend/scripts/voice_profiles.py" --store "<PROFILE_STORE>" create --profile-id qwen-en-design --name "English narrator" --engine qwen3_tts --mode voice_design --language en --voice-description-file "<PROMPT_FILE>"
```

Create the verified Kokoro English preset:

```text
python3 "<SKILL_DIR>/backend/scripts/voice_profiles.py" --store "<PROFILE_STORE>" create --profile-id kokoro-en --name "Kokoro narrator" --engine kokoro --mode preset --language en --voice-id af_heart --control speed=1.0
```

The Skill CLI rejects unverified creation modes. `list` shows profile metadata without voice prompts or paths; `show <PROFILE_ID>` intentionally reveals the selected prompt; `update-controls <PROFILE_ID> --control key=value` validates before mutation; `delete <PROFILE_ID>` removes only the selected profile. Older unverified profiles may remain visible with `synthesis_supported: false`, but the synthesis runner will not execute them. The store writes atomically and rejects unsafe paths.

## Version-2 synthesis request

The v2 request is profile-backed and accepts only `qwen3_tts` or `kokoro`. It does not accept inline prompts, reference-audio paths, arbitrary filesystem paths, or unknown fields. Required fields are `protocol_version=2`, `message_type="synthesis.request"`, safe `request_id`/`job_id`, supported `engine_id`, narration `text`, `voice_profile_id`, WAV output options, and `deadline_ms` (1–3,600,000). Optional fields are `trace_id`, `options.output_name` (ASCII-safe `.wav` name), and `options.chunk_chars` (100–1,200).

Use `templates/qwen-voice-design-request-v2.json` as a complete request example. Replace the sample narration and profile/request IDs, save as UTF-8 JSON, and validate against `backend/schemas/synthesis-request-v2.schema.json`.

Run with the engine-specific Python executable and the exact store used to create the profile:

```text
python3 "<SKILL_DIR>/backend/scripts/run_voiceover.py" --request "<REQUEST_JSON>" --profile-store "<PROFILE_STORE>" --output-dir "<OUTPUT_DIR>" --timeout-seconds 300
```

Legacy v1 synthesis remains available only for the verified Kokoro path. Direct v1 Qwen and unverified engine/mode combinations fail closed with `ENGINE_PATH_NOT_VERIFIED` or `VOICE_MODE_UNSUPPORTED`. The runner emits one structured JSON result. Audio must remain inside the requested output directory; the manifest records file metadata and digest, not the voice prompt.

## Verify output

Inspect an existing PCM WAV:

```text
python3 "<SKILL_DIR>/backend/scripts/inspect_voiceover_audio.py" "<OUTPUT_DIR>/voiceover.wav" --pretty
```

For a bounded end-to-end smoke that requires actual model inference and checks the WAV plus manifest:

```text
python3 "<SKILL_DIR>/backend/scripts/real_inference_smoke.py" --request "<REQUEST_JSON>" --profile-store "<PROFILE_STORE>" --engine qwen3_tts --output-dir "<OUTPUT_DIR>" --timeout-seconds 300 --report "<REPORT_DIR>/smoke.json" --pretty
```

A smoke `PASS` confirms the worker succeeded and the actual WAV passed the configured decode, integrity, manifest, duration, silence, and clipping checks. It does not prove linguistic accuracy, subjective quality, a particular speaker identity, long-run stability, or performance on another machine. `inference_verified` stays false on any failure.

## Stable failure signals

| Error/status | Meaning and next step |
|---|---|
| `RESOURCE_PREFLIGHT_BLOCKED` / `BLOCKED` | RAM, disk, CPU, or monitoring prerequisite failed; stop and report the reason. Never override thresholds. |
| `RESOURCE_LIMIT_EXCEEDED` | The monitored process tree crossed the fixed engine RSS limit and was terminated. Do not raise the cap or auto-retry. |
| `ENGINE_JOB_ALREADY_RUNNING` | Another TTS job owns the single-job lock; wait for it to finish, then retry only if still requested. |
| `ENGINE_PATH_NOT_VERIFIED` / `PROFILE_MODE_NOT_VERIFIED` | The requested route is intentionally withheld until a real WAV smoke passes. |
| `ENGINE_DEPENDENCY_MISSING` | The selected engine interpreter lacks a required package; inspect the report and use only its isolated environment. |
| `ENGINE_MODEL_ARTIFACT_MISSING` | Required local snapshot/files are unavailable; use only the pinned, bounded acquisition flow. |
| `ENGINE_MODEL_LOAD_FAILED` / `ENGINE_INFERENCE_FAILED` | The actual engine failed; preserve the redacted report and do not claim audio success. |
| `INFERENCE_TIMEOUT` | Deadline elapsed and the worker was stopped; use a suitable host without relaxing the configured cap. |
| `VOICE_CONTROL_UNSUPPORTED` / `VOICE_CONTROL_OUT_OF_RANGE` | The control is invalid for the selected engine/mode; use the documented allowlist. |
| `VOICE_DESCRIPTION_FILE_TOO_LARGE` | Prompt exceeds 1,600 characters; shorten the user-approved prompt. |
| `AUDIO_ACCEPTANCE_FAILED` | A WAV/manifest acceptance check failed; do not deliver the failed file as verified. |

## Host command notation

`<SKILL_DIR>`, `<NEW_ENV>`, `<PYTHON_3_12>`, `<ENGINE_PYTHON>`, `<PROFILE_STORE>`, `<PROMPT_FILE>`, `<REQUEST_JSON>`, `<OUTPUT_DIR>`, and `<REPORT_DIR>` denote actual paths chosen by the agent; replace each with a quoted path. On Windows, use the available Python launcher (`py -3`) and Windows paths. Always invoke `.py` files through Python; the package does not rely on executable bits. Refer to `platform-compatibility.md` before claiming a host can import or run this package natively.
