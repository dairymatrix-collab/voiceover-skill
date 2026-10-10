# D0-431–D0-460 Test and Runtime Evidence

Date: 2026-10-10. This report supplements `FINAL_TEST_EVIDENCE_REPORT.md` and the active task ledger. It distinguishes package readiness, local artifact presence, real inference, and audio verification.

## Implementation evidence

- Replaced the Agent Skill template with complete, executable local-workflow instructions; added exact profile/API commands, platform compatibility guidance, a v2 Qwen VoiceDesign request template, and a generated PNG icon.
- Implemented the bounded, revision-pinned model acquisition CLI and catalog, profile prompt-file support, Qwen VoiceDesign artifact selection, and profile-backed smoke routing. Model data remains outside all source/Skill/plugin archives.
- Split MiniMax distribution formats after auditing the official submission guide: the MiniMax Code archive contains only its 0.3.x/0.4.0+ dual layouts; the separate Marketplace submission archive contains the native `.minimax-plugin/plugin.json` and referenced Skill, without root `plugin.json` or `.claude-plugin/plugin.json`.
- The MiniMax Code 0.3.x portable manifest has exactly the two properties permitted by its closed Agent Plugins 1.0 schema: `$schema` and `name`. The separate Claude Code ZIP uses the official directory-path form for its `skills` field.

## Regression and Skill validation

- Complete source suite: `/workspace/voiceover_test_venv/bin/python -m pytest -q` — **925 passed, 2 skipped, 0 failed**. The skips are eSpeak synthesis checks because eSpeak is not installed. One expected Python warning is emitted by the ZIP duplicate-entry rejection test.
- Focused packaging regression file: `tests/test_voiceover_skill_packaging.py` — **3 passed**. It checks the v2 example schema, no template placeholders, all four archive types, package reproducibility, ASCII paths, regular/non-executable files, no model/native binary files, and separation of the MiniMax Code and Marketplace manifests.
- Official Agent Skill validator: `quick_validate.py skills/voiceover-skill` — **PASS**.
- All four Skill/plugin package targets built with `--check-reproducible`; byte-identical repeated builds, structural checks, and ZIP CRC checks passed.
- Marketplace ZIP static audit — **PASS**: native manifest at ZIP root; 57 files, 550,239 uncompressed bytes; no wrapper, Unicode paths, case collisions, duplicate JSON keys, BOMs, symlinks, executable-bit-dependent files, foreign Code/Claude manifests, model weights, or native binaries. Skill frontmatter and manifest references match.
- A standalone Skill ZIP was extracted under a path containing spaces and non-ASCII characters. From that extraction, runner help, profile listing in a non-ASCII store path, resource preflight, and v2 request-schema validation passed. Final source-archive clean-extraction verification is recorded after release packaging below.

## Qwen3-TTS VoiceDesign CPU readiness and smoke result

- Isolated Python 3.12.3 setup report: `research/d0_431_460/qwen_setup_cpu_report.json`, status `PACKAGE_READY`. It records Qwen TTS 0.1.1, Transformers 4.57.3, and Torch/Torchaudio 2.6.0 CPU builds with the declared runtime dependencies. This is package readiness only.
- Bounded download report: `research/d0_431_460/qwen_voice_design_download_report.json`, status `DOWNLOADED`; repository `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign`, immutable revision `5ecdb67327fd37bb2e042aab12ff7391903235d3`, 11 allowlisted files and 4,520,159,099 bytes. Hugging Face Hub download integrity is recorded; the report explicitly says full-file hashes were not recomputed locally.
- Local artifact audit: `research/d0_431_460/qwen_voice_design_artifact_report.json`, status `ARTIFACTS_READY`, all nine required file groups satisfied. Artifact presence does not prove model loading.
- One real profile-backed, CPU-only smoke was attempted with two CPU threads, a 300-second deadline, the 14-GiB RAM preflight, and the unchanged 10-GiB process-tree RSS cap. It returned `RESOURCE_LIMIT_EXCEEDED`; worker exit code 137. The output directory contains no WAV/partial audio, and the report keeps `inference_verified=false`. The cap was not raised and no retry was made. See `research/d0_431_460/qwen_voice_design_cpu_smoke_report.json` and `research/d0_431_460/qwen_voice_design_cpu_smoke_evidence.md`.
- Existing Kokoro CPU inference evidence remains valid for its one English profile. This Qwen attempt does not change the project-wide inference claim; Phase 0 remains **OPEN / HOLD**.

## हिन्दी सारांश

- पूरा regression suite: **925 पास, 2 स्किप, 0 फ़ेल**; स्किप eSpeak executable अनुपस्थित होने के कारण हैं। Agent Skill validator और चारों reproducible package builds पास हुए।
- MiniMax Code का 0.3.x/0.4.0+ dual-layout ZIP और Marketplace submission ZIP अलग रखे गए हैं। Submission ZIP में केवल native `.minimax-plugin` manifest है; Code/Claude के वैकल्पिक manifests उसमें शामिल नहीं हैं।
- Qwen CPU dependencies और pinned VoiceDesign files तैयार हैं, लेकिन वास्तविक inference 10-GiB process-tree RSS सीमा पर रुक गया। WAV नहीं बना; इसलिए Qwen के लिए `inference_verified=false` ही है और Phase 0 **OPEN / HOLD** है।
- Android APK नहीं बनाया गया: परियोजना Python desktop workflow है; उपलब्ध कार्य-ट्री/टूलचेन में वास्तविक Android Gradle/SDK build setup नहीं है।

## Final source ZIP extraction

The source ZIP was extracted into a fresh directory containing spaces and non-ASCII characters. Its 246 ZIP members passed CRC, safe-path, and duplicate-name checks; all 245 SHA256SUMS entries verified. Python compilation passed for 162 files. The extracted tree then passed the complete suite (**925 passed, 2 skipped**), the Agent Skill validator, runner/profile CLI checks, a Qwen resource preflight, and the read-only VoiceDesign artifact check (`ARTIFACTS_READY`, no missing required files, `inference_verified=false`). The final rebuild and repeat check after ledger closure are included in the companion release manifest. Exact final ZIP digests are recorded there to avoid a self-referential hash inside the source archive.
