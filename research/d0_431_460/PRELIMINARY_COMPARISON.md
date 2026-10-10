# Custom-voice model evaluation — preliminary only

**Research cutoff:** 2026-10-10. Static repository/model-card and benchmark review only; no packages or weights were installed/downloaded as part of this audit. Six of seven candidate audits are complete. Do not treat this as the final model selection.

| Exact candidate | Text-only voice design? | Footprint evidence | Language evidence | License / CPU evidence |
|---|---|---|---|---|
| Chatterbox Turbo | No; official Turbo path uses reference audio; reaction tags are not speaker design | Turbo checkpoint displayed as 1.92 GB (rounded; exact bytes not published in the fetched page) | English-only Turbo variant | MIT. GPU-focused claims; no CPU benchmark or Python 3.12 confirmation found |
| Fun-CosyVoice3-0.5B-2512 | No description-only speaker creation found; documented instruct examples also supply a reference WAV | Hub reports 11,767,984,206 bytes repository storage, not a minimal deployable model size | Nine listed languages plus Chinese dialects | Apache-2.0 metadata. Official setup is Python 3.10; no CPU minimum/performance or Python 3.12 confirmation found |
| OpenAudio S1 Mini | No local description-only speaker creation documented; style markers and cloning are distinct | 0.5B; gated file listing did not expose checkpoint byte sizes | 13 listed languages | S1 Mini card says CC-BY-NC-SA-4.0/non-commercial; current repo-wide license also imposes restrictions. Provider Arena rank 60 does not measure local text-designed voices |
| MOSS-VoiceGenerator | Yes; instruction-based voice/style design without reference audio | `model.safetensors` is 4,228,278,872 bytes; 1.7B card label conflicts with API-reported 2,114,118,656 parameters | English and Chinese | Apache-2.0. CPU code path exists, but no measured speed or peak memory evidence |
| Qwen3-TTS-12Hz-1.7B-VoiceDesign | Yes; official API accepts text, language, and a natural-language voice instruction; reference-audio cloning is a different Base checkpoint | Official checkpoint files total 4,515,695,644 bytes for the model and speech tokenizer | 10 official languages | Code and model card metadata state Apache-2.0. Official examples are GPU-oriented; CPU viability/performance is not established |
| VoxCPM2 | Yes; official model card documents parenthesized natural-language description at the start of the text; reference-audio cloning is a separate mode | Official file tree lists model and AudioVAE weights totaling 4,957,031,714 bytes (additional runtime assets excluded) | 30 listed languages plus nine Chinese dialects | Apache-2.0. Official Python path documents CUDA 12+; a third-party C++ port advertises CPU, but its voice-design path and CPU memory/speed are not established |

### Early ranking caveat

A smaller parameter count does not necessarily satisfy description-only design. The completed audits found no comparable public human-preference/arena rank for the exact Qwen or MOSS checkpoints; instruction-following scores are not naturalness ranks. A VoxCPM2 author technical report presents a blind listening experiment and higher task-specific N-MOS/I-MOS than the other three reported systems in its controllable voice-design table, but that is an author-reported task result, not an independent universal leaderboard. The Chatterbox leaderboard entry identifies the family as “Chatterbox,” not Turbo, so its rank cannot be attributed to Turbo. CosyVoice3 did not appear in the checked Voice Arena roster. OpenAudio S1 Mini's provider-voice rank is not a rank of local description-only voice design. No “best-ranked” claim is justified yet.

### Remaining work

The official-source audit is still running for IndexTTS-2. Once all seven are compared, choose the best fit for **text-only voice design + practical local CPU testability + language/license fit**, then attempt a bounded isolated inference. Full per-candidate source reports are preserved under `raw/`.
