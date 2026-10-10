# Voiceover Skill downloadable artifacts

These are the reproducibly built Skill/plugin ZIPs and the accepted Qwen3-TTS VoiceDesign sample evidence included in this repository. Package ZIPs contain Skill/plugin source and documentation; **they do not contain TTS model weights or an engine runtime**. Verify copied files against this directory's SHA-256 values; the repository-root `SHA256SUMS` also covers committed files (but not itself or an archive container).

## Artifacts

| File | Purpose | Size (bytes) | SHA-256 |
|---|---|---:|---|
| [`voiceover-agent-skill.zip`](voiceover-agent-skill.zip) | Standalone Agent Skill with bundled backend | 116,806 | `083d6c27cd3a96cd9185a16fd160617a66a7181f9885372c3c098f84c213cd91` |
| [`voiceover-claude-code-plugin.zip`](voiceover-claude-code-plugin.zip) | Claude Code Plugin layout | 307,313 | `236069c7ace7e811994729009716619a8c2f75992aed10687cf4daa7bea2883a` |
| [`voiceover-minimax-code-dual-plugin.zip`](voiceover-minimax-code-dual-plugin.zip) | MiniMax Code 0.3.x / 0.4.0+ dual compatibility layout | 423,420 | `db9dedd5cb1936f8ecf902d7213c3c97aebd63495be1e23b9bdffc7d24bda963` |
| [`voiceover-minimax-marketplace-plugin.zip`](voiceover-minimax-marketplace-plugin.zip) | Native MiniMax Marketplace submission layout | 307,601 | `4b17aaabf250735c4a6c6b76f5a54d27fad731ad44f85a59bfa60a6d3904bd20` |
| [`qwen_voice_design_verified_sample.wav`](qwen_voice_design_verified_sample.wav) | One accepted English Qwen3-TTS VoiceDesign CPU sample | 153,644 | `a998c90bc521e1bf9bfcbf72fbf0c96d97a13c482cbd315ad03bc920dbdc2b73` |
| [`qwen_voice_design_verified_sample_report.json`](qwen_voice_design_verified_sample_report.json) | Real inference smoke report (`PASS`, `inference_verified=true`) | 1,649 | `ca929803bea7ff4514b7ed58653c0fc61b765499490188d09152e79b70793e0a` |
| [`qwen_voice_design_verified_sample_inspection.json`](qwen_voice_design_verified_sample_inspection.json) | Independent WAV inspection report (`ok=true`) | 557 | `479ff84f09e70ce6e0378b3b8ec4393c542f5532328ad99aaa4638cd7a38d62d` |

The WAV is 24-kHz mono PCM16, 3.2 seconds, with zero clipping and no inspection warnings. These objective checks do not establish subjective intelligibility, naturalness, pronunciation, broad language support, speaker identity, or other-host performance. No measured peak RSS was retained.

## Rebuild the install packages

From the repository root, build all four packages and require byte-identical repeated builds:

```bash
python scripts/package_voiceover_skill.py --output-dir ../voiceover_skill_distribution --check-reproducible
```

The output directory must be outside the source tree. The source archive can be rebuilt separately with `scripts/build_package.py --output <path-outside-repository> --check-reproducible`; that command prints the source ZIP hash. The source archive is intentionally not listed in this artifact table.
