# D0-401–D0-430 External Source Notes — TTS Artifact Layouts

**Checked:** 2026-10-10. These notes constrain the artifact inventory for the existing adapter implementations; they do not claim that the local runtime has downloaded or loaded any model.

## Official source evidence

### Kokoro (`KPipeline` adapter)

- [Official Hexgrad Kokoro README](https://github.com/hexgrad/kokoro) documents `KPipeline(lang_code=...)`, `pipeline(text, voice='af_heart')`, and writing generated 24 kHz audio.
- [Official `kokoro/model.py`](https://raw.githubusercontent.com/hexgrad/kokoro/main/kokoro/model.py) declares the default Hugging Face model filename `kokoro-v1_0.pth`; `KModel` also downloads/loads `config.json`.
- [Official `kokoro/pipeline.py`](https://raw.githubusercontent.com/hexgrad/kokoro/main/kokoro/pipeline.py) loads requested voice tensors from `voices/{voice}.pt` and passes them to the model.
- [Official Kokoro model repository tree](https://huggingface.co/api/models/hexgrad/Kokoro-82M/tree/main) lists `config.json`, `kokoro-v1_0.pth`, and the `voices/` directory. Individual voice entries are `.pt` files, including `voices/af_heart.pt`.
- **Decision:** the previous `kokoro-v1.0.onnx` + `voices-v1.0.bin` inventory targets a different ONNX implementation and is not compatible with this project's `KPipeline` adapter. Correct the new v2 inventory to require the official `.pth` checkpoint, config, and at least one `.pt` voice file; do not silently treat ONNX-only files as ready.

### Qwen3-TTS (`Qwen3TTSModel` adapter)

- [Official Qwen3-TTS README](https://github.com/QwenLM/Qwen3-TTS) documents downloading each model locally and loading either a Hub model ID or a local directory with `Qwen3TTSModel.from_pretrained`.
- [Official Qwen3-TTS model tree](https://huggingface.co/api/models/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice/tree/main?recursive=true) lists `config.json`, `model.safetensors`, `generation_config.json`, `tokenizer_config.json`, `vocab.json`, `merges.txt`, `preprocessor_config.json`, plus `speech_tokenizer/config.json`, `speech_tokenizer/model.safetensors`, and `speech_tokenizer/preprocessor_config.json`.
- [Official Qwen3-TTS loader source](https://raw.githubusercontent.com/QwenLM/Qwen3-TTS/main/qwen_tts/inference/qwen3_tts_model.py) loads both model and processor from the supplied directory.
- **Decision:** a nonempty directory or one arbitrary file does not establish artifact readiness. v2 should require the core config/weights/tokenizer metadata and nested speech-tokenizer config/weights.

### Chatterbox (multilingual adapter default)

- [Official Chatterbox README](https://github.com/resemble-ai/chatterbox) documents `ChatterboxMultilingualTTS.from_pretrained(device=...)` and its default multilingual use.
- [Official multilingual loader source](https://raw.githubusercontent.com/resemble-ai/chatterbox/master/src/chatterbox/mtl_tts.py) defaults to `t3_mtl23ls_v2.safetensors`; `from_local` loads `ve.pt`, `s3gen.pt`, `grapheme_mtl_merged_expanded_v1.json`, and the configured T3 checkpoint. `from_pretrained` downloads those files from `ResembleAI/chatterbox` into a Hugging Face cache snapshot.
- [Official Chatterbox English loader source](https://raw.githubusercontent.com/resemble-ai/chatterbox/master/src/chatterbox/tts.py) uses a different set: `ve.safetensors`, `t3_cfg.safetensors`, `s3gen.safetensors`, and `tokenizer.json` (with optional `conds.pt`).
- [Official Chatterbox model repository tree](https://huggingface.co/api/models/ResembleAI/chatterbox/tree/main?recursive=true) lists multilingual checkpoints and English checkpoints, including both `.pt` and `.safetensors` variants.
- **Decision:** the existing `ChatterboxAdapter` defaults to multilingual mode, so v2 checks the multilingual default loader's required files. The checker remains a bounded, symlink-aware inventory, not a checkpoint loader. `inference_verified` stays false until the separate real-inference smoke gate succeeds.

## Scope / evidence limits

- These are upstream layouts as observed on the check date; model repositories can change. Recheck after changing an adapter, model variant, or revision.
- Artifact presence, filenames, nonzero size, and optional hashes do **not** prove checkpoint integrity, license suitability, sufficient RAM/VRAM, compatibility, successful model loading, speech quality, or inference.
- No package, model weight, or voice file was downloaded during this source check.


## Kokoro CPU-smoke feasibility sources

- [Official Kokoro model card](https://huggingface.co/hexgrad/Kokoro-82M) describes an 82-million-parameter model and states the weights are Apache-licensed. It documents a `KPipeline(lang_code='a')` example using `af_heart`; the card also identifies CC BY 3.0/4.0 audio included in the training data, so the model is not being redistributed with this source package and any redistribution/use should retain/review applicable upstream notices.
- [Official Kokoro `pyproject.toml`](https://raw.githubusercontent.com/hexgrad/kokoro/main/pyproject.toml) reports package version 0.9.4, `requires-python >=3.10,<3.14`, an Apache Software License classifier, and dependencies on Hugging Face Hub, Loguru, Misaki, NumPy, PyTorch, and Transformers.
- [Official `KPipeline` source](https://raw.githubusercontent.com/hexgrad/kokoro/main/kokoro/pipeline.py) auto-selects CUDA if visible and otherwise selects CPU; it downloads a requested voice from the model repository when not already cached. [Official Kokoro README/model usage](https://github.com/hexgrad/kokoro) shows `pip install kokoro>=0.9.2 soundfile` and an `espeak-ng` package for its example path.
- **Feasibility decision:** Python 3.12.3 is inside both project policy and upstream range; the current computer has 8 CPUs, about 13 GiB available RAM, no detected NVIDIA GPU, and 63 GiB free disk. A short CPU test with the default synthetic `af_heart` voice and a non-sensitive generic sentence is reasonable after the bounded preflight confirmed PyPI and Hugging Face endpoints reachable. This is an isolated smoke attempt, not a guarantee of stability on every OS/device or a license/legal opinion.


## Installed Kokoro CPU runtime and verified smoke evidence

- The isolated verification environment used Python 3.12.3 and the installed Kokoro 0.9.4 package. `torch` 2.14.1 reported `torch.cuda.is_available() == False`; synthesis ran on CPU. The environment also reported NumPy 2.5.3, SoundFile 0.14.0, Transformers 5.19.0, and Hugging Face Hub 2.2.0.
- The selected cached checkpoint was the official `hexgrad/Kokoro-82M` snapshot inspected through the Hugging Face Hub cache. The main `kokoro-v1_0.pth` file measured 327,212,226 bytes; the selected `voices/af_heart.pt` measured 523,425 bytes. The artifact checker found all three required groups (`config.json`, model checkpoint, at least one `voices/*.pt`).
- One generic English request using `af_heart` produced a 24 kHz mono PCM WAV on CPU. The project's seven real-smoke checks passed, and a separate audio inspection found 4.225 seconds, non-silent frames, zero clipping ratio, and no warnings. Audio SHA-256: `9d328112dd41f42c1d859c99ab2fcaf845646193e0f2096b3b09242cf843bf39`.
- This observed run is a single-engine/single-profile proof, not a ranking, human quality evaluation, broad multilingual claim, Qwen3-TTS/Chatterbox result, or offline guarantee. The source package does not include model weights. The model-card/source references above are the provenance for the asset layout and license; this note records the local runtime observation, not a license interpretation.
