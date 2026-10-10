# Optional TTS engines: integration and verification status

The core harness deliberately does not install or download model dependencies. The optional adapters in `tts_engine_adapters.py` lazily integrate with the public Python APIs for Qwen3-TTS, Chatterbox TTS, and Kokoro. Install the engine and its model/runtime dependencies in a separate, appropriately sized environment; do not assume CPU, RAM, GPU VRAM, system phonemizers, or model cache availability.

## Local capability probe

```bash
python scripts/probe_tts_engines.py --pretty
```

This reports package presence and a conservative Qwen model-cache directory check. It does **not** load model weights, prove the model is complete, download anything, or mark inference verified. `inference_verified` remains false by design until an actual generated audio artifact is independently checked.

## Adapter overview

- `Qwen3TTSAdapter`: supports the documented CustomVoice and VoiceDesign generation methods. The language map is intentionally limited to the ten documented languages. Voice cloning is fail-closed in this adapter because the reference-audio/clone-prompt flow needs a separate, explicit configuration. Speed and seed options are rejected rather than silently ignored.
- `ChatterboxAdapter`: supports the package's multilingual or English model loaders. `voice_id="default"` uses the model's default voice; another `voice_id` is treated as a reference-audio path and must exist. The adapter rejects speed/seed options that are not wired to the engine. `device="auto"` selects CUDA, MPS, or CPU based on local PyTorch visibility.
- `KokoroAdapter`: lazily caches one `KPipeline` per supported language code and concatenates generated audio segments. Voice IDs must be valid for the selected Kokoro model/language. Seed is rejected because no deterministic seed contract is implemented here.

The adapter API and audio serialization are covered by model-free tests using fake in-process model objects. Those tests verify adapter boundaries, not acoustic quality or compatibility with every release of the upstream packages. Actual inference requires installing dependencies and model weights and running a smoke test in the target environment. Upstream APIs can change; pin tested engine versions before production use.

## Security and production caveats

Model loading can download weights depending on upstream settings and cache state. Run it only in a trusted environment with deliberate network, disk, and memory policy. These adapters do not sandbox provider code, authenticate downloaded weights, provide signed provenance, normalize loudness, crossfade chunks, or resample mismatched audio. The orchestration pipeline requires compatible PCM WAV chunks. Phase 0 remains **OPEN / HOLD** until real inference, target-agent integration, sandboxing, and integrity/provenance controls are verified.

## Upstream API references consulted

- Qwen3-TTS official repository: https://github.com/QwenLM/Qwen3-TTS
- Chatterbox official repository: https://github.com/resemble-ai/chatterbox
- Kokoro official repository: https://github.com/hexgrad/kokoro

## D0-221–D0-250: dependency and hardware readiness report

Run the new read-only diagnostic before choosing an engine:

```bash
python scripts/diagnose_tts_environment.py --pretty
python scripts/diagnose_tts_environment.py --engine kokoro --output-dir ./output --pretty
python scripts/diagnose_tts_environment.py --engine kokoro --strict-engine-ready
```

The report captures the Python version, architecture, PyTorch version and visible compute device, optional engine distribution versions, missing prerequisites, ffmpeg/eSpeak executable paths, an estimate of system memory, available output-disk space when requested, and a bounded Hugging Face cache scan. `--write-json PATH` saves the report using a temporary file and atomic replacement. `--strict-engine-ready` exits with code 2 if the selected engine's declared distributions are missing.

An `install_plan` is informational only. It returns argument arrays for creating a dedicated virtual environment and installing the selected top-level package; it does not invoke pip. Review the upstream repository's current supported Python versions, operating-system wheels, GPU requirements, and model licensing before running any installation command. The plan is intentionally not version-pinned because upstream compatibility must be confirmed for the target machine before a reproducible production lock can be responsibly created.

`inference_verified` always remains `false` in this diagnostic. Package presence, a cache directory, or a successful diagnostic is not evidence that weights load or that speech is generated. Use `scripts/real_inference_smoke.py` after installation and require a real, independently validated audio file.

### Public request envelope compatibility

The runner now normalizes the documented `synthesis.request` envelope (`engine_id`, nested `options`, and `deadline_ms`) into the internal `PipelineRequest` fields and respects the request deadline as an upper bound on the CLI timeout. Legacy flat requests remain supported. Non-null `reference_audio` is rejected with a structured `REFERENCE_AUDIO_NOT_SUPPORTED` error until safe path resolution and the complete reference-audio adapter flow are implemented; it is never silently ignored.


## D0-281–D0-310: interpreter and install preflight

Before attempting an engine install, run:

```bash
python scripts/preflight_tts_install.py --engine kokoro --pretty --report ./preflight.json
python scripts/preflight_tts_install.py --engine chatterbox --skip-network --wheelhouse ./wheelhouse --pretty
python scripts/preflight_tts_install.py --engine qwen3_tts --python-candidate /path/to/python3.12 --pretty
```

The preflight is read-only. It discovers supported Python interpreters, reports optional module availability, performs bounded HTTPS reachability checks, and inventories wheelhouse filenames. A wheelhouse inventory is **not** a compatibility or trust audit: check wheel tags, dependency closure, provenance, and upstream engine support before installation. Current environment result: no Python 3.10–3.12 executable discovered; PyPI and Hugging Face DNS resolution failed. Therefore no installation or model download was attempted and actual inference remains blocked.

## Offline system-TTS baseline (D0-311–D0-340)

If internet access and neural-model packages are unavailable but `espeak-ng` or `espeak` is installed, run `scripts/offline_speech_probe.py` to create a real WAV and validate its signal metrics. This is a diagnostic baseline only; it does not satisfy neural TTS inference acceptance. The report explicitly records `neural_engine=false` and `inference_verified=false`.

## Python runtime acquisition diagnostic (D0-341–D0-370)

`scripts/probe_python_runtime_acquisition.py` is a read-only, offline-only diagnostic for environments where the active Python is outside the project policy. It checks whether `uv` is present, inventories its cache at a high level, and can run `uv python install 3.12/3.11/3.10 --offline`. It never treats that probe as proof of installation and never downloads anything. A cache miss is reported explicitly as `OFFLINE_CACHE_MISS`.

In the current environment, `uv` is available but the requested CPython 3.12.12 archive was not present in the local cache; network connectivity is disabled. Therefore the supported interpreter remains unavailable and neural inference remains blocked.

### Artifact readiness gate (D0-371–400)

Before attempting neural inference, use `scripts/inspect_tts_artifacts.py` to establish whether the expected local model assets exist. A report of `ARTIFACTS_READY` is only an artifact-presence result; it is **not** model-load or inference proof. The actual inference gate remains closed until a real engine generates validated WAV audio.

Current upstream references checked for this batch indicate Kokoro packaging currently targets Python 3.11–3.12, Qwen3-TTS recommends an isolated Python 3.12 environment and supports local model directories, and Qwen3-TTS documentation explicitly describes manually downloading weights when runtime downloads are undesirable. These upstream constraints are external evidence and do not override this harness's own runtime/inference gates.


## Adapter-accurate artifact readiness and offline staging (D0-401–D0-430)

The artifact inventory is now checked against the model files consumed by the current adapters. For Kokoro `KPipeline`, the required assets are `config.json`, `kokoro-v1_0.pth`, and at least one `voices/*.pt`; the ONNX/binary pair mentioned by the previous inventory was incompatible and is no longer considered ready. Qwen3-TTS checks the main checkpoint/config/tokenizer plus the nested `speech_tokenizer` config, weights, and preprocessor metadata. Chatterbox checks the current multilingual adapter default (`ve.pt`, `s3gen.pt`, `grapheme_mtl_merged_expanded_v1.json`, and `t3_mtl23ls_v2.safetensors`). These names are version-sensitive; recheck upstream if the adapter or model variant changes.

Use schema v2 to see required groups and optionally hash each matched small file, subject to the configured byte limit:

```text
python scripts/inspect_tts_artifacts.py --engine kokoro --schema-version 2 --model-root ./staged-models --hash-files --report ./reports/kokoro-artifacts.json --pretty
```

A report path must be outside the inspected model root. Exit 0 means the declared required artifact groups are present and nonempty; exit 3 means readiness is not established; exit 2 means an invocation, path-safety, or report-writing error. These exits do not prove model load or synthesis. For offline wheelhouse preparation, model staging, install-preflight codes, privacy notes, and the complete gate sequence, follow [`OFFLINE_INSTALL_AND_READINESS.md`](OFFLINE_INSTALL_AND_READINESS.md).

Source layout evidence is recorded in [`D0_401_430_EXTERNAL_SOURCE_NOTES.md`](D0_401_430_EXTERNAL_SOURCE_NOTES.md), with upstream links to the [Kokoro loader](https://raw.githubusercontent.com/hexgrad/kokoro/main/kokoro/model.py), [Qwen model tree](https://huggingface.co/api/models/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice/tree/main?recursive=true), and [Chatterbox multilingual loader](https://raw.githubusercontent.com/resemble-ai/chatterbox/master/src/chatterbox/mtl_tts.py). Artifact presence and hashes remain separate from real model-load, inference, and audio-quality verification.
