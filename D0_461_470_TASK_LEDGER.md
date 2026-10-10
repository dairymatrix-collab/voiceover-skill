# D0-461–D0-470 Task Ledger

**Date:** 2026-10-10  
**Follow-up to:** D0-431–D0-460  
**Objective:** Test whether a lighter/safe CPU loading policy can produce a real prompt-designed Qwen voice under the existing resource guard, then remove unverified synthesis paths from the installable Skill surface.

| Task | Work | Status | Evidence |
|---:|---|---|---|
| 461 | Investigate the earlier Qwen VoiceDesign FP32 load failure and inspect pinned checkpoint dtype/loading options without relaxing the RSS/RAM/thread/time policy | VERIFIED | Prior smoke report: `research/d0_431_460/qwen_voice_design_cpu_smoke_report.json`; audited installed loader/checkpoint metadata; unchanged 10-GiB process-tree RSS cap |
| 462 | Add CPU-native BF16 loading for the pinned VoiceDesign profile adapter and protect its local-only revision/file allowlist with regression tests | VERIFIED | `tts_engine_adapters.py`; `tests/test_tts_engine_adapters.py`; focused adapter tests pass |
| 463 | Run one real profile-backed Qwen VoiceDesign CPU synthesis using the existing two-thread/300-second/10-GiB policy | VERIFIED | `research/d0_431_460/qwen_voice_design_bf16_cpu_smoke_report.json`: `PASS`, worker exit 0, `inference_verified=true`; no resource limit was raised |
| 464 | Independently decode and inspect the produced WAV; verify its digest and objective audio properties | VERIFIED | `research/d0_431_460/qwen_voice_design_bf16_audio_inspection.json`; SHA-256 `a998c90bc521e1bf9bfcbf72fbf0c96d97a13c482cbd315ad03bc920dbdc2b73`; 24-kHz mono PCM16, 3.2 s, zero clipping, no warnings |
| 465 | Restrict public runtime routing to Kokoro preset and Qwen VoiceDesign; keep v1 synthesis Kokoro-only and v2 engine IDs to those verified routes | VERIFIED | `scripts/run_voiceover.py`; `voice_controls.py`; `tts_engine_adapters.py`; v2 request schema; request/adapter tests |
| 466 | Restrict profile creation CLI to verified mode pairs and label old unsupported stored profiles as not synthesis-supported | VERIFIED | `scripts/voice_profiles.py`; `tests/test_voice_profile_cli.py`; `PROFILE_MODE_NOT_VERIFIED`/runtime rejection tests |
| 467 | Restrict public engine setup and model-download commands to Kokoro preset and Qwen VoiceDesign, including the hidden downloader worker boundary | VERIFIED | `scripts/setup_tts_engine.py`; `scripts/download_tts_model.py`; `tests/test_engine_setup.py`; `tests/test_tts_model_download.py` |
| 468 | Rewrite the Skill/API/offline-readiness guidance to state the accepted paths, exact fixed resource thresholds, evidence limits, and withheld modes | VERIFIED | `skills/voiceover-skill/SKILL.md`, `skills/voiceover-skill/references/api_reference.md`, `OFFLINE_INSTALL_AND_READINESS.md`, `README.md`, `CUSTOM_VOICE_MODEL_SELECTION.md` |
| 469 | Run focused and complete regressions, documentation contracts, and official Skill validation | VERIFIED | Focused verified-only suite: 164 passed; docs/package contracts: 10 passed; full suite: **932 passed, 2 skipped, 0 failed**; Skill validator PASS |
| 470 | Rebuild four installable packages and reproducible source archive, then clean-extract and verify the exact release | VERIFIED | Four package ZIPs and source ZIP pass byte-identical reproducibility and CRC checks. Fresh source extraction: 252 members, 251 manifest entries, 162 Python files compile, 20 schemas, 932 passed/2 skipped; Skill validator, non-ASCII profile store, verified-only CLIs, and package rebuild from extracted source pass. Exact hashes are in `D0_461_470_RELEASE_MANIFEST.md`. |

## Status and scope

- The earlier FP32 Qwen attempt remains accurately recorded as `RESOURCE_LIMIT_EXCEEDED` with no WAV. A later native-BF16 attempt did produce an accepted WAV under the unchanged policy; the 10-GiB guard was not raised.
- The accepted Qwen evidence is one English prompt-designed profile only. It does not prove subjective naturalness, pronunciation, speaker identity, all controls/languages, or another host's resource profile. The report did not record measured peak RSS; do not state an exact peak.
- The installed Skill runtime/profile/setup/download surface exposes only `kokoro/preset` and `qwen3_tts/voice_design`. Chatterbox/reference cloning and Qwen CustomVoice preset remain unverified and are not selectable there. Older profile storage compatibility remains, but the runner rejects unsupported profile modes.
- Phase 0 remains **OPEN / HOLD** for broader language/voice, subjective listening, external host/runtime, and production-supervision validation.
- No Android APK was produced: the Python project still has no Android manifest, Gradle project/wrapper, SDK, or Android build tools.

## हिन्दी सारांश

- पहले का FP32 Qwen प्रयास 10-GiB RSS guard पर रुका था; सीमा नहीं बढ़ाई गई। Native-BF16 CPU load के साथ एक बाद का वास्तविक prompt-profile inference पास हुआ और WAV स्वतंत्र रूप से जाँची गई।
- स्वीकृत WAV: 24 kHz, mono, PCM16, 3.2 सेकंड, 153,644 bytes; सातों objective checks PASS, clipping शून्य, warnings नहीं; SHA-256 ledger में दर्ज है। रिपोर्ट में exact peak RSS नहीं है।
- Installed Skill, profile CLI, setup और downloader अब केवल `kokoro/preset` और `qwen3_tts/voice_design` दिखाते/चलाते हैं। Chatterbox reference clone और Qwen CustomVoice preset वास्तविक WAV acceptance तक unsupported हैं।
- पूरा suite **932 पास, 2 स्किप, 0 फ़ेल**; दोनों skips eSpeak अनुपस्थित होने से हैं। चारों Skill/plugin ZIP और source ZIP reproducible; final source extraction, manifest hashes, compilation, Skill validator और verified-only CLI checks पास हुए।
- Phase 0 अभी **OPEN / HOLD** है; Android APK के लिए toolchain उपलब्ध नहीं।
