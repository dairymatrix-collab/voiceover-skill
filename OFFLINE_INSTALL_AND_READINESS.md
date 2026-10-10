# Offline Installation and Neural TTS Readiness

This guide separates **runtime preparation**, **package presence**, **model artifacts**, **imports**, **model loading**, **synthesis**, and **audio inspection**. The installed Skill exposes only two profile-backed routes that have passed real WAV smoke acceptance: Kokoro `preset` and Qwen3-TTS `voice_design` (custom voice design from a saved text prompt). Chatterbox/reference cloning and Qwen CustomVoice preset remain unverified and are not exposed by the Skill setup/download/profile/synthesis CLIs. Model files are not bundled.

This project does not install anything by running a read-only preflight. All paths below are examples; use an engine Python executable compatible with the target OS, architecture, Python ABI, and upstream version. The project setup policy currently permits Python 3.10–3.12; that is not a promise that every upstream engine release or platform supports every version in that range.

## Readiness gates

| Gate | What it establishes | What it does not establish |
|---|---|---|
| Runtime preflight | A supported interpreter is discoverable; declared packages/modules and selected diagnostics are reported | Package install, usable GPU, weights, model load, synthesis |
| Package setup/import | Engine dependencies install and the package can be imported in that interpreter | Complete/correct weights, model load or audio output |
| Artifact inspection | Expected nonempty adapter-specific files are inside the selected model root | Weight integrity/authenticity, license compliance, compatibility, RAM/VRAM sufficiency or successful model load |
| Model-load attempt | The real smoke request reaches the engine's real model loader | Successful synthesis or acceptable audio |
| Real inference gate | The real worker generates WAV and the file/manifest meet configured objective checks | Pronunciation, intelligibility, speaker identity, naturalness or subjective quality |
| Audio inspection/listening | Objective WAV metrics and, when performed, human review | General quality for every language, prompt, voice or device |

`inference_verified` remains false until the real inference smoke gate passes against a real model and its generated output. Artifact readiness, package presence, mocked tests, or eSpeak output do not satisfy that gate.

## 1. Check the target runtime without changing it

Run only the engine diagnostic for a supported Skill route, using the intended engine interpreter:

```text
python scripts/preflight_tts_install.py --engine kokoro --skip-network --pretty
python scripts/preflight_tts_install.py --engine qwen3_tts --skip-network --pretty
```

For Qwen VoiceDesign artifact detail, add `--model-variant voice_design` to the relevant artifact/preflight command. This preflight is read-only; `--skip-network` also skips its bounded package-index/model-hub reachability probes. A proposed install plan or wheelhouse inventory is not an installation.

## 2. Prepare an engine environment or an offline wheelhouse

First review the selected route's current upstream Python/platform requirements and license. Any offline wheelhouse must match the target OS, CPU architecture, Python minor/ABI, and accelerator stack. A list of wheel filenames does not prove compatibility or dependency closure. Do not install arbitrary wheels based only on filenames.

On an authorized online staging machine, create and review a fully pinned, target-specific lock containing the full runtime dependency closure. A reviewed lock and wheelhouse are external artifacts; neither is shipped by this project. Verify transferred files against recorded hashes. Use one isolated environment per engine when dependency sets conflict.

An explicit offline install template for the reviewed Kokoro lock is:

```text
python scripts/setup_tts_engine.py --engine kokoro --environment .venvs/kokoro --python python --install --wheelhouse ./wheelhouse --no-index --timeout-seconds 1800 --pretty
```

For the audited Qwen CPU setup, use the explicit `--cpu-only` plan/install flow in `skills/voiceover-skill/references/api_reference.md`. On this Linux x86_64 host, installing unpinned `torch` from the default PyPI index selected a CUDA-enabled wheel and NVIDIA runtime libraries despite no available GPU. The isolated test venv occupied 5.9 GiB; `torch.cuda.is_available()` was false. Do not assume generic package-index installation is a compact CPU profile.

Setup CLI support is deliberately limited to `kokoro` and `qwen3_tts`; Chatterbox is retained only in historical audit material, not as an installable Skill route. `--install` changes the selected environment and is opt-in. Package/import verification never loads model weights.

## 3. Stage complete supported model assets

Use the pinned allowlisted acquisition CLI in the Skill API reference, or transfer complete official snapshots after reviewing their source and license. A model folder is useful only when its full configuration, tokenizer, checkpoint, and voice/tokenizer files are present.

| Verified route | Required local files checked by v2 | Accepted folder candidates under `--model-root` |
|---|---|---|
| Kokoro `KPipeline` preset | `config.json`; `kokoro-v1_0.pth`; at least one `voices/*.pt` | `Kokoro-82M`, `models/Kokoro-82M`, or Hugging Face cache entry `models--hexgrad--Kokoro-82M` |
| Qwen3-TTS VoiceDesign | Root `config.json`, `generation_config.json`, `model.safetensors`, `preprocessor_config.json`, `tokenizer_config.json`, `vocab.json`, `merges.txt`; nested `speech_tokenizer/config.json`, `speech_tokenizer/configuration.json`, `speech_tokenizer/model.safetensors`, and `speech_tokenizer/preprocessor_config.json` | `Qwen3-TTS-12Hz-1.7B-VoiceDesign`, `models/Qwen3-TTS-12Hz-1.7B-VoiceDesign`, or `models--Qwen--Qwen3-TTS-12Hz-1.7B-VoiceDesign` |

These are the checked layouts for the routes exposed here, not every upstream variant. The Kokoro ONNX pair (`kokoro-v1.0.onnx` plus `voices-v1.0.bin`) does **not** satisfy this `KPipeline` adapter's `.pth`/`.pt` layout. The Qwen VoiceDesign loader uses an immutable, audited snapshot and local-only Hub mode during profile synthesis.

A Hugging Face cache root may contain snapshot files as symlinks into its own `blobs/` directory. The inspector accepts file symlinks only when resolved targets remain inside the supplied model root, and it does not recurse through directory symlinks. Set `--model-root` to a directory containing the accepted cache entry—not to an individual snapshot whose blob targets lie outside the selected root.

The inspector's `--model-root` is not the runtime model-cache setting. When no explicit root or `VOICEOVER_MODEL_ROOT` / `TTS_MODEL_ROOT` is set, inspection discovers the effective Hugging Face Hub cache (`HF_HUB_CACHE`, then `HF_HOME/hub`, then `XDG_CACHE_HOME/huggingface/hub`, then `~/.cache/huggingface/hub`). An explicit `--model-root` is strict: if it is missing, inspection reports that path instead of silently selecting another configured cache. This adapter constructs upstream Kokoro `KPipeline`, which can lazily download model/voice files if they are not cached. For genuinely offline synthesis, stage the complete upstream cache and set `HF_HUB_CACHE`, `HF_HOME`, or `XDG_CACHE_HOME` to the correct cache base. `--skip-network` only skips preflight reachability probes; it does not disable downloads from a later Kokoro inference request. The Qwen profile adapter explicitly runs local-only.

Official layouts: [Kokoro model card](https://huggingface.co/hexgrad/Kokoro-82M), [Kokoro model source](https://raw.githubusercontent.com/hexgrad/kokoro/main/kokoro/model.py), [Qwen3-TTS VoiceDesign model card](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign), [Qwen3-TTS repository](https://github.com/QwenLM/Qwen3-TTS), [Qwen VoiceDesign pinned file tree](https://huggingface.co/api/models/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign/tree/5ecdb67327fd37bb2e042aab12ff7391903235d3?recursive=true&expand=true), and [Qwen3-TTS tokenizer model card](https://huggingface.co/Qwen/Qwen3-TTS-Tokenizer-12Hz).

## 4. Inspect local artifacts (no install, download or model load)

Use schema v2 for adapter-specific required-file groups and optional bounded hashes:

```text
python scripts/inspect_tts_artifacts.py --engine kokoro --schema-version 2 --model-root ./staged-models --hash-files --report ./reports/kokoro-artifacts.json --pretty
python scripts/inspect_tts_artifacts.py --engine qwen3_tts --schema-version 2 --model-variant voice_design --model-root ./staged-models --report ./reports/qwen-voice-design-artifacts.json --pretty
```

Keep the report directory **outside** the inspected model root. A v2 report identifies which file groups matched. With `--hash-files`, only matched required files below the configured per-file cap are SHA-256 hashed; larger weights are reported `SKIPPED_SIZE_LIMIT`, never as a partial digest. Hashes are fingerprints, not authenticity signatures. Legacy v1 JSON remains the default for compatibility; choose schema v2 for corrected group details.

The install preflight can include the same report:

```text
python scripts/preflight_tts_install.py --engine qwen3_tts --skip-network --include-artifacts --model-variant voice_design --model-root ./staged-models --report ./reports/qwen-preflight.json --pretty
```

Artifact CLI exit codes: **0** = required local files are present; **3** = readiness was not established; **2** = invalid/unsafe/unwritable arguments or report path. Inspect the JSON status and group details, not just the code. No artifact result proves model loading or synthesis.

## 5. Install, acquire, then perform a real smoke

A Qwen CPU setup command is plan-only unless `--install` is present; model acquisition is separately plan-only unless `--download` is present. Use only the official fixed repositories/revisions, file allowlists, fresh resource preflight, single-job lock, and finite timeout in the installed Skill API reference. The VoiceDesign snapshot is roughly 4.5 GB. Do not manually resume, move, or bypass partially downloaded files.

The Qwen CPU path retains its fixed policy: at least a 14-GiB available-RAM preflight, two CPU threads, a monitored process-tree RSS limit of 10 GiB, and the finite 300-second real-smoke deadline. Do not increase those limits. The adapter requests the saved BF16 dtype for the Qwen VoiceDesign main checkpoint on CPU; it does not change the checkpoint or relax the resource guard.

Package imports check import-time dependency compatibility only. Run a real profile-backed smoke with an actual v2 request and saved profile. For example:

```text
python scripts/real_inference_smoke.py --request ./qwen-voice-design-request.json --profile-store ./voice-profiles --engine qwen3_tts --output-dir ./voiceover-output --timeout-seconds 300 --report ./reports/qwen-smoke.json --pretty
```

A pass requires the real worker to generate audio and the output/manifest to pass configured decode, digest/size, duration, silence, and clipping checks. On failure, preserve the structured report and keep `inference_verified=false`; do not claim success from package import or artifact presence.

## Verified CPU inference evidence (2026-10-10)

- **Kokoro preset:** one English request using the `af_heart` voice, Kokoro 0.9.4, PyTorch 2.14.1, and Python 3.12.3 completed on CPU with a real cached checkpoint. The 24-kHz mono PCM WAV was 4.225 seconds; seven objective checks passed. This does not establish subjective voice quality, offline synthesis, or other languages/voices.
- **Qwen VoiceDesign:** one local English prompt-profile request completed on CPU in the isolated pinned Qwen environment with native BF16 main-checkpoint loading. It produced a 24-kHz mono PCM16 WAV, 3.2 seconds, 153,644 bytes, no clipping, no warnings; the real smoke passed all seven objective checks, and an independent WAV inspection confirmed the same SHA-256 `a998c90bc521e1bf9bfcbf72fbf0c96d97a13c482cbd315ad03bc920dbdc2b73`. The fixed guard did not trigger, but the report did not retain a measured peak RSS, so no exact peak is claimed. Earlier default FP32 loading was stopped by the same 10-GiB guard and produced no WAV; BF16 was added without raising limits. See `research/d0_431_460/qwen_voice_design_bf16_cpu_smoke_report.json`, `research/d0_431_460/qwen_voice_design_bf16_audio_inspection.json`, the audio file in `research/d0_431_460/qwen_voice_design_bf16_smoke_output/`, and `CUSTOM_VOICE_MODEL_SELECTION.md`.

These are objective path checks, not subjective listening, intelligibility, pronunciation, speaker identity, broad language coverage, or long-run stability. Chatterbox/reference cloning and Qwen CustomVoice preset are not verified and remain unavailable through the installed Skill. Phase 0 stays **OPEN / HOLD** for broader acceptance and external host/runtime checks.

## Privacy and scope

Artifact reports contain resolved model-root and matched paths that can disclose local usernames or directory layout; review/redact before sharing. Optional SHA-256 values can fingerprint local model files. Reports do not include transcript/audio content or copy weights. Read-only commands do not install packages or download model files. Explicit setup/download actions are separate, gated, and require authorization. Human listening is needed for linguistic and perceptual review; objective WAV metrics cannot establish subjective quality.
