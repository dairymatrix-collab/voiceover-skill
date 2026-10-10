# D0-431–D0-460 external source notes

**Checked:** 2026-10-10. These are public-source observations, not model-runtime proof. Seven candidate-level reports are preserved under `research/d0_431_460/raw/`.

## Candidate shortlist and source-backed selection

Only three audited variants meet the specific **natural-language description → new speaker identity without reference audio** criterion: MOSS-VoiceGenerator, Qwen3-TTS-12Hz-1.7B-VoiceDesign, and VoxCPM2. The preliminary choice for the first local CPU trial is **MOSS-VoiceGenerator** because its model card demonstrates the exact text-plus-instruction workflow, explicitly chooses CPU when CUDA is unavailable, selects eager attention on CPU, matches Python 3.12, and its main checkpoint file is the smallest of the three eligible models. This is only a test-first decision: published sources do not establish latency or peak RAM on this 8-core/23-GiB CPU computer.

VoxCPM2 has the strongest task-specific human-listening evidence among these three in the inspected reports: its authors' blind listening table reports voice-design N-MOS 4.48±0.04 and I-MOS 4.50±0.03, with the highest I-MOS among four systems in that table. The same paper reports runtime only on an RTX 4090, about 8 GB VRAM and RTF 0.30 for the PyTorch path. Its official Python runtime requires CUDA ≥12.0; a third-party CPU port does not demonstrate the natural-language voice-design interface. This is not a universal leaderboard rank or proof that VoxCPM2 cannot run on CPU.

Qwen's exact 12Hz-1.7B VoiceDesign API is directly documented and its report provides InstructTTSEval instruction-following scores, but the official examples load to `cuda:0`; no comparable listener/arena rank or CPU specification for the exact local checkpoint was found. InstructTTSEval APS/DSD/RP values must not be described as human-preference/naturalness scores.

## MOSS checkpoint and custom-code review boundary

The official Hub API returns model revision `97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4`, last modified 2026-02-11, public and ungated, with Apache-2.0 metadata, 2,114,118,656 BF16 parameters, and 4,239,701,563 bytes total repository storage. The main `model.safetensors` file is 4,228,278,872 bytes; the API's LFS SHA-256 is `dbe345257ff9f6cc84195bed830a268b39d5e0b728ff3ba90e715150a49b16d4`. The model card calls the model 1.7B; the API parameter count differs and the reason was not found.

The official model card describes Chinese and English text-to-speech from a natural-language instruction without reference audio, with voice characteristics, emotion, speed and pitch. Its CPU branch sets `device='cpu'`, `dtype=torch.float32`, and `attn_implementation='eager'`; the documented output sampling rate is obtained from model configuration. It uses Transformers `AutoProcessor` and `AutoModel` with `trust_remote_code=True`. Hub config maps `AutoConfig` to `configuration_moss_tts.MossTTSDelayConfig` and `AutoModel` to `modeling_moss_tts.MossTTSDelayModel`.

The top of the pinned model/processor source files was inspected. The model implementation begins with PyTorch/Transformers/tqdm imports; the processor begins with OS/path/regex, torchaudio, PyTorch and Transformers imports, and its loader requests a separate `OpenMOSS-Team/MOSS-Audio-Tokenizer` model. Raw-source page extraction truncated both larger Python files, so this is **not a complete security review**. Before executing remote model code, download and inspect all custom Python source at the exact revision, record local SHA-256 hashes, and use an isolated environment. The Hub's safety metadata for the safetensors weight file does not certify the Python files.

Model and repository sources:
- MOSS official repo: https://github.com/OpenMOSS/MOSS-TTS
- MOSS VoiceGenerator model card: https://github.com/OpenMOSS/MOSS-TTS/blob/main/docs/moss_voice_generator_model_card.md
- Exact checkpoint Hub API: https://huggingface.co/api/models/OpenMOSS-Team/MOSS-VoiceGenerator
- Exact checkpoint tree: https://huggingface.co/api/models/OpenMOSS-Team/MOSS-VoiceGenerator/tree/main?recursive=true&expand=true
- Pinned MOSS config: https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/raw/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4/config.json
- Pinned MOSS model implementation: https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/raw/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4/modeling_moss_tts.py
- Pinned MOSS processor: https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/raw/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4/processing_moss_tts.py
- MOSS technical report: https://arxiv.org/html/2603.28086v1

## Benchmark distinctions

MOSS's paper reports English/Chinese InstructTTSEval instruction-following accuracy and a separate blind pairwise listening study of 100 instruction–speech pairs; its model card mentions 160 internal samples. This study is not a public Arena ranking, and exact win percentages were not available in the extracted paper text. Qwen's report's Table 8 evaluates APS/DSD/RP instruction-following. VoxCPM2's Table 14 reports N-MOS and I-MOS from its authors' subjective voice-design test. These are different tests/dimensions and cannot be collapsed into one universal quality ranking.

- Qwen official implementation: https://github.com/QwenLM/Qwen3-TTS
- Qwen technical report: https://arxiv.org/html/2601.15621v1
- VoxCPM2 technical report: https://arxiv.org/html/2606.06928v1

## Candidate exclusions

Chatterbox Turbo (350M), CosyVoice3-0.5B-2512, Fish Audio S1 Mini (0.5B), and IndexTTS-2 did not meet the description-only new-speaker requirement in their documented local variants. Fish S1 Mini is gated and has non-commercial/CC-BY-NC-SA license restrictions; its provider-voice rank is not a rank of local text-designed voices. IndexTTS-2's text prompts control emotion rather than speaker identity; its upstream Python constraint is `<3.12` and its license is conditional. Full individual sources and caveats are in the raw audit JSON files.


## Resource correction: MOSS-Audio-Tokenizer is a second large model (2026-10-10)

The MOSS VoiceGenerator processor loads a separate `OpenMOSS-Team/MOSS-Audio-Tokenizer` checkpoint. The official Hugging Face model API reports revision `3cd226ba2947efa357ef453bcad111b6eafba782`, Apache-2.0 license, 1,774,566,400 F32 parameters, and 7,100,864,789 bytes of repository storage. The model card documents `AutoModel.from_pretrained(..., trust_remote_code=True)` and describes a 24 kHz audio model. The file tree identifies two `model-0000*-of-00002.safetensors` shards; shard 1 alone is 4,998,259,168 bytes. Sources: [Hugging Face model API](https://huggingface.co/api/models/OpenMOSS-Team/MOSS-Audio-Tokenizer), [official model card](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer), [official file tree](https://huggingface.co/api/models/OpenMOSS-Team/MOSS-Audio-Tokenizer/tree/main?recursive=true&expand=true).

The current environment snapshot has 23 GiB total RAM, about 20 GiB available, 54 GiB free disk, Python 3.12.3, and no NVIDIA GPU. The MOSS VoiceGenerator and tokenizer parameter counts imply a combined CPU float32 parameter lower bound of 15,554,740,224 bytes (15.55 decimal GB), before framework overhead, buffers, temporary copies, and inference activations. Their model files alone require approximately 11.33 decimal GB on disk, before caches/temporary download space. This is not an observed peak-RAM measurement; it is a risk estimate. **Do not run/download/load MOSS on this host without a verified safe loading strategy and explicit resource gate.** Reconsider MOSS as a default custom-voice backend; keep the already verified Kokoro baseline for preset-voice synthesis and evaluate smaller custom-design candidates (including Qwen3-TTS) under conservative limits. No MOSS weights have been downloaded and no MOSS inference has been attempted.


## Qwen VoiceDesign full model-plus-tokenizer resource check (2026-10-10)

The exact `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign` Hub API reports revision `5ecdb67327fd37bb2e042aab12ff7391903235d3`, Apache-2.0, 1,916,676,352 BF16 parameters, and total repository storage 4,515,695,644 bytes. The same repository contains the nested `speech_tokenizer/model.safetensors` (682,293,092 bytes; 170,557,441 F32 parameters), so this particular model card's total storage already includes its codec; it is not another hidden 7-GB model. Official examples still load on `cuda:0`; no official CPU minimum-memory or CPU performance guarantee was found. Sources: [Qwen model API](https://huggingface.co/api/models/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign), [Qwen file tree](https://huggingface.co/api/models/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign/tree/main?recursive=true&expand=true), [Qwen tokenizer model card](https://huggingface.co/Qwen/Qwen3-TTS-Tokenizer-12Hz).

From those parameter counts, a conservative all-FP32 parameter payload is 8,348,935,172 bytes (8.35 decimal GB), versus 15.55 GB for the MOSS-plus-audio-tokenizer stack. If the main model remains BF16 while the codec is F32, the parameter payload is 4,515,582,468 bytes, close to its published 4.516-GB model repository. This is arithmetic, not a measured peak-RAM result. Qwen is therefore the lower-memory candidate to test next, subject to strict runtime memory/thread/time gates; CPU inference is still **unverified** and model download is not proof of CPU suitability.


## Qwen loader/control and package metadata

The official Qwen repository's `qwen-tts` package declares version 0.1.1 and supports Python >=3.9, including 3.12. Its declared dependencies pin Transformers 4.57.3 and Accelerate 1.12.0 and include Gradio, librosa, torchaudio, soundfile, sox, onnxruntime, and einops. The official `Qwen3TTSModel.from_pretrained()` forwards keyword arguments directly to Transformers `AutoModel.from_pretrained`; therefore `device_map="cpu"` is technically passed through, but the official model card example uses `device_map="cuda:0"`, BF16 and FlashAttention. This code path does **not** establish supported or performant CPU inference. The `generate_voice_design()` API accepts a natural-language `instruct` and generation parameters including `top_k`, `top_p`, `temperature`, `repetition_penalty`, `max_new_tokens`, plus sub-talker sampling controls. Only a conservative allowlist should be exposed in the Skill, with per-model validation. Sources: [official Qwen pyproject](https://raw.githubusercontent.com/QwenLM/Qwen3-TTS/main/pyproject.toml), [official Qwen model loader](https://raw.githubusercontent.com/QwenLM/Qwen3-TTS/main/qwen_tts/inference/qwen3_tts_model.py), [official Qwen VoiceDesign card](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign).


## Chatterbox controls and resource options (official source; pin release before integration)

The official multilingual loader's `generate()` currently exposes `audio_prompt_path`, `exaggeration`, `cfg_weight`, `temperature`, `repetition_penalty`, `min_p`, and `top_p`, plus `language_id`; the English loader exposes corresponding expressive/sampling controls. This differs from the existing project adapter, which currently passes only a reference path and language, so it must not claim these controls work until they are safely mapped and tested against a pinned package/revision. The official README also describes Chatterbox-Nano (110M) as CPU-oriented and reports 3x real-time on 8 CPU cores, but this is a vendor claim for its documented reference-audio/voice-cloning workflow, not text-only speaker design and not independently tested here. The fetched raw-source URLs point at a moving branch; pin a release/commit and review it before executing/installing. Sources: [multilingual loader](https://raw.githubusercontent.com/resemble-ai/chatterbox/master/src/chatterbox/mtl_tts.py), [English loader](https://raw.githubusercontent.com/resemble-ai/chatterbox/master/src/chatterbox/tts.py), [official repository and README](https://github.com/resemble-ai/chatterbox).


## Fresh CPU resource gate snapshot (2026-10-10)

A new read-only check reports 8 logical CPUs (Intel Xeon 2.50 GHz), 23 GiB total RAM, 20 GiB currently available, no swap, and 54 GiB free disk. The existing isolated Torch build reports `2.14.1+cu130`, CPU capability AVX512, and the BF16 CPU-kernel probe is false; no CUDA device had been found in the earlier bounded hardware probe. This makes an explicit FP32 Qwen CPU trial more conservative than assuming BF16 acceleration. The planned trial is conditional on at least 14 GiB free RAM at launch, a 10 GiB process-tree RSS ceiling, 2 CPU threads, one active TTS job, and a 300-second smoke deadline. These are protective thresholds, not a guarantee the model will fit or finish; if the 10-GiB monitor terminates it, report `BLOCKED/RESOURCE_LIMIT` and keep Kokoro as the verified route. No Qwen weights have been downloaded yet.


## MiniMax M3 clarification and official compatibility boundary (2026-10-10)

- User clarified that “M3” means **MiniMax M3**.
- MiniMax’s official model page describes M3 as a coding/agentic model with tool invocation and documents access through MiniMax Code integration / API: https://www.minimax.io/models/text/m3 . The official text-generation docs identify MiniMax-M3 as an agentic/tool-use model and say MiniMax supports both Anthropic-style and OpenAI-style request formats: https://platform.minimax.io/docs/guides/text-generation .
- The official M3 GitHub README reports approximately 428B total parameters and 23B activated parameters and lists large-model inference frameworks; it does not define an Agent Skills importer: https://github.com/MiniMax-AI/MiniMax-M3 .
- MiniMax’s Plugin submission documentation specifies `.minimax-plugin/plugin.json` at ZIP root, Skill content under `skills/<name>/SKILL.md`, relative bundled paths, and explicit interpreters for portable scripts. It describes Desktop (MiniMax Code) and Cloud (MiniMax Agent) delivery targets through the plugin review/publishing workflow: https://agent.minimax.io/docs/code/agents/plugin-submission .
- **Implementation decision:** target the MiniMax Plugin host format and refer to M3 as a model that can power that host, not as a standalone Skill runtime. Do not bundle M3 weights or credentials. A raw M3 API call alone does not execute this package’s local voiceover backend. Before claiming cloud execution, verify MiniMax Agent’s actual Python runtime/dependencies and file permissions. Platform reference: `skills/voiceover-skill/references/platform-compatibility.md`.

## Chatterbox 0.1.7 official release source audit (2026-10-10)

- PyPI official release JSON reported `chatterbox-tts==0.1.7`, MIT license, `Requires-Python >=3.10`; its official 84,802-byte source tarball SHA-256 was checked before any source was read: `ed8afae83819b40a25927c2ef3bcc67f928bdfcf434c1376c972e6039252a187`. Archived at `research/d0_431_460/chatterbox_0.1.7_audit/chatterbox_tts-0.1.7.tar.gz`; extracted source files were read only and never executed.
- Release package metadata pins `torch==2.6.0`, `torchaudio==2.6.0`, `transformers==5.2.0`, `diffusers==0.29.0`, `safetensors==0.5.3`, `conformer==0.3.2`, `pykakasi==2.3.0`, `gradio==6.8.0`, and other dependencies. Its README says development/testing used Python 3.11/Debian 11. No install or model download was performed.
- The pinned multilingual `generate()` API accepts `text, language_id, audio_prompt_path, exaggeration, cfg_weight, temperature, repetition_penalty, min_p, top_p`; the English API accepts `text, repetition_penalty, min_p, top_p, audio_prompt_path, exaggeration, cfg_weight, temperature`. Static source is under `research/d0_431_460/chatterbox_0.1.7_audit/src/chatterbox/`.
- **Important runtime caveat:** the inspected `from_pretrained()` loaders download the model from an unpinned `main` revision. A production/offline-safe integration must select/pin the exact model revision and use explicit cache/local-only behavior rather than blindly invoking this default loader.


## Pinned Qwen loader audit and profile-model revisions (2026-10-10)

The official PyPI `qwen-tts==0.1.1` sdist was downloaded only for static inspection after verifying its 114,131-byte size and SHA-256 `afba5fa235806a6883f46a389e67540b46f8a55da457216bf1d7342903814780`; archive and extracted text files are preserved under `research/d0_431_460/qwen_tts_0.1.1_audit/`. The official `Qwen3TTSModel.from_pretrained()` forwards its keyword arguments to Transformers `AutoModel.from_pretrained()`, but separately calls `AutoProcessor.from_pretrained(path)` without forwarding a revision or `local_files_only` flag. Therefore profile mode first resolves the exact pinned snapshot with Hugging Face Hub `local_files_only=True`, then passes that local directory to Qwen; inference itself cannot trigger a checkpoint download. The audited `generate_voice_design()` and `generate_custom_voice()` accept `**kwargs` and document `top_k`, `top_p`, `temperature`, `repetition_penalty`, and `max_new_tokens`; those are the validated options exposed by `voice_controls.py`.

The VoiceDesign checkpoint is pinned to `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign@5ecdb67327fd37bb2e042aab12ff7391903235d3` (Apache-2.0, about 4.516 GB repository storage including nested speech tokenizer). The CustomVoice/preset checkpoint is pinned to `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice@0c0e3051f131929182e2c023b9537f8b1c68adfe` (Apache-2.0, about 4.605 GB). Official Hub API sources: [VoiceDesign metadata](https://huggingface.co/api/models/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign), [CustomVoice metadata](https://huggingface.co/api/models/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice), [Qwen package release](https://pypi.org/pypi/qwen-tts/0.1.1/json).

The official Chatterbox Hub API reports `ResembleAI/chatterbox@5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18` (MIT) and retains the exact V2 files expected by the audited 0.1.7 loader. Profile mode now pins this commit, downloads no weights during synthesis, and calls the package's `from_local()` against the local snapshot; the V2 file allowlist follows the 0.1.7 loader. The current model card calls V3 the newest general-purpose checkpoint, but this profile adapter deliberately selects the V2 filenames compatible with the audited 0.1.7 API. Sources: [model metadata](https://huggingface.co/api/models/ResembleAI/chatterbox), [official model card](https://huggingface.co/ResembleAI/chatterbox).

No Qwen or Chatterbox package/model was installed or downloaded as part of this static audit. The code paths are unit-tested with fakes; real inference remains pending resource preflight and a bounded runtime trial.


## Native plugin compatibility layouts and bounded model catalog evidence (checked 2026-10-10)

### MiniMax Code 0.3.x and 0.4.0+

- MiniMax's official Code plugin compatibility document in `MiniMax-AI/MiniMax-Code-Plugins` says the portable Agent Plugins 1.0 layout is what mcode 0.3.x reads; mcode 0.4.0+ still accepts it but prefers the Claude-compatible layout. A bundle targeting both must ship both layouts in parallel. The 0.3.x manifest is root `plugin.json` with `$schema` `https://agent-plugins.org/schemas/1.0.0/plugin.schema.json`, and Skills live under `skills/<name>/SKILL.md`. The 0.4.0+ manifest is `.claude-plugin/plugin.json`; its `skills` field uses `./skills/SKILL.md`, and the package also includes a byte-identical `skills/<plugin-name>/SKILL.md` for the older runtime/validator. Source: https://raw.githubusercontent.com/MiniMax-AI/MiniMax-Code-Plugins/main/docs/plugin-compatibility.md .
- The separate official third-party MiniMax Agent Plugin submission guide requires `.minimax-plugin/plugin.json` directly at ZIP root, no wrapper directory, and `skills/<skill-name>/SKILL.md` referenced by its manifest. It rejects symlinks/hardlinks, non-ASCII paths, secrets, install lifecycle scripts, native binaries, and executable-bit-dependent files; portable scripts should be invoked via an explicit interpreter. It also says packages in other plugin formats must first be converted to the documented format. Therefore, keep the MiniMax Code 0.3/0.4 compatibility ZIP separate from the Marketplace submission ZIP; the latter contains only the native `.minimax-plugin` manifest and its referenced Skill files. No Hooks are needed. Source: https://agent.minimax.io/docs/code/agents/plugin-submission .
- The portable root manifest schema requires only `$schema` and `name`; additional properties are closed. Source: https://agent-plugins.org/schemas/1.0.0/plugin.schema.json .

### Fixed model acquisition catalog

- Qwen VoiceDesign is pinned to `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign` revision `5ecdb67327fd37bb2e042aab12ff7391903235d3`. The exact Hub tree reports `model.safetensors` 3,833,402,552 bytes and `speech_tokenizer/model.safetensors` 682,293,092 bytes; required configs/tokenizer files are small. Files/tree: https://huggingface.co/api/models/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign/tree/5ecdb67327fd37bb2e042aab12ff7391903235d3?recursive=true&expand=true . Main checkpoint API: https://huggingface.co/api/models/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign .
- Chatterbox is pinned to `ResembleAI/chatterbox` revision `5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18`. The package's local loader requires `ve.pt`, `t3_mtl23ls_v2.safetensors`, `s3gen.pt`, and `grapheme_mtl_merged_expanded_v1.json`; its existing allowlist also includes optional `conds.pt` and `Cangjie5_TC.json`. Those six files total about 3.209 GB by audited Hub sizes, versus the repository's much larger 23.65-GB total containing unused model variants. Tree: https://huggingface.co/api/models/ResembleAI/chatterbox/tree/5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18?recursive=true&expand=true .
- Kokoro `hexgrad/Kokoro-82M` API reports Apache-2.0, current revision `f3ff3571791e39611d31c381e3a41a3af07b4987`, and repository storage 1,234,555,949 bytes. Source: https://huggingface.co/api/models/hexgrad/Kokoro-82M . The local Kokoro adapter resolves the Hub `main` ref; any explicit acquisition must compare resolved snapshot commit to the pinned revision before declaring it ready.
- Hub model presence is not CPU-inference proof. Qwen's bounded download catalog will keep a fixed allowlist and an absolute size cap; local loading remains pinned and offline-only. The fixed catalog is evidence-backed but still subject to fresh runtime preflight, partial-download verification, and the real smoke test.


### Manifest schema details used by the generated packages (2026-10-10)

- The official MiniMax submission guide's JSON example uses `schemaVersion`, `name`, `displayName`, `version`, `description`, string `author`, package-relative `icon`, `category`, up to three `exampleQueries`, and capability arrays `apps`, `mcpServers`, and `skills`. For this Skill-only package, `apps` and `mcpServers` are empty and `skills` points at `skills/voiceover-skill/SKILL.md`; the guide's available category list includes `Productivity`. Source: https://agent.minimax.io/docs/code/agents/plugin-submission .
- The official Claude Code manifest reference states that `skills` paths are directories relative to the plugin root, and the manifest belongs at `.claude-plugin/plugin.json`. This is distinct from MiniMax Code 0.4's documented `./skills/SKILL.md` file-path form, so the project emits a separate Claude Code ZIP rather than claiming one manifest is valid for both. Source: https://code.claude.com/docs/en/plugins/manifest-reference .
