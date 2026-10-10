---
name: voiceover-skill
description: Create and verify local WAV voiceovers using a Kokoro preset voice or a reusable Qwen3-TTS voice designed from a text prompt; manage local profiles and respect strict resource safeguards.
---

# Voiceover Skill

Use the bundled backend to create local WAV narration, reuse voice profiles, and verify every output. Model weights are not bundled; profile-backed synthesis is local-only and uses pinned model files.

**Verified scope:** Kokoro preset voiceover passed one real English CPU WAV smoke. Qwen3-TTS VoiceDesign passed one real English, prompt-profile CPU WAV smoke using the checkpoint's native BF16 weights. Those checks establish that these two paths produced accepted audio on the tested host—not subjective speech quality, every language, every control setting, or operation on every computer. Chatterbox/reference-clone and Qwen CustomVoice preset modes are not exposed by the Skill runtime because they have not passed a real WAV smoke.

## Resolve the bundle

Treat the directory containing the loaded `SKILL.md` as `SKILL_DIR`; resolve bundled files relative to it. The backend is `SKILL_DIR/backend`. Invoke Python files through the host's Python 3 interpreter (`python3` on many Unix hosts; `py -3` or `python` on Windows), quote every path, and never assume a fixed install location.

Read `references/api_reference.md` when an exact command, schema, control range, or failure status is needed. Read `references/platform-compatibility.md` before giving host-specific installation instructions. The sample request is `templates/qwen-voice-design-request-v2.json`.

## Workflow

1. **Choose one of the verified paths.** Use Kokoro `preset` for the verified fixed voice path, or Qwen3-TTS `voice_design` for a reusable voice created from a text description. Do not offer Qwen CustomVoice preset, reference cloning, or Chatterbox as supported Skill modes.
2. **Run the read-only resource gate** for the selected engine before setup, download, or synthesis:
   ```text
   python3 "<SKILL_DIR>/backend/scripts/preflight_tts_resources.py" --engine qwen3_tts --pretty
   ```
   Replace the engine with `kokoro` when appropriate. If the gate blocks, stop and report its reasons; do not override limits or fall back to a hosted service. The Qwen CPU policy requires at least a 14-GiB available-RAM preflight and retains the fixed 10-GiB process-tree RSS limit, two-thread policy, and finite 300-second smoke deadline.
3. **Check packages and local artifacts.** Use the read-only diagnostics in the API reference. A ready package or present checkpoint is not proof of inference. Show a plan before any installation or multi-gigabyte download; proceed only when the user requested or authorized that acquisition. Use the pinned revision, allowlist, timeout, and structured report.
4. **Create or reuse a profile.** For Qwen, keep the voice description in a private local UTF-8 file and pass its path with `--voice-description-file`; do not put the prompt in shell history or routine logs. For Kokoro, use the verified `af_heart` English preset. Keep the profile store on a private local path.
5. **Create a v2 request as UTF-8 JSON.** Requests contain a profile ID, supported engine ID, narration text, WAV options, and a bounded deadline—not inline prompts, reference audio, arbitrary paths, or extra engine fields. Validate against `backend/schemas/synthesis-request-v2.schema.json` when editing programmatically.
6. **Synthesize with a finite timeout.** Use `scripts/run_voiceover.py` with the request, the same profile-store root, an output directory, and a finite timeout. The runner applies the project resource policy and launches a killable worker.
7. **Verify the actual audio.** Run `scripts/inspect_voiceover_audio.py` on the returned WAV. For a fresh engine smoke, use `scripts/real_inference_smoke.py`; require its `PASS`, all checks, and the output manifest. Return the WAV path and verified technical properties. Label linguistic or subjective quality as unreviewed unless separately assessed.

## Voice-profile rules

- The Skill creates only `kokoro/preset` and `qwen3_tts/voice_design` profiles. Older stored profiles for other modes may be listed for management, but the runner rejects unsupported modes.
- Keep profiles local and reusable; normal list output does not print prompts or filesystem paths. Use `show` only when the selected prompt itself is needed.
- A Qwen voice description is limited to 1,600 characters. A saved prompt is a reusable recipe, not a guarantee of identical speaker identity across versions, hardware, or decoding settings.
- Reject unsupported controls and out-of-range values; never silently discard them. The exact allowlists are in `references/api_reference.md`.
- Treat prompts as sensitive local data. Do not upload them or send them to hosted TTS. Do not imitate a real person's voice without authorization.

## Failure handling

On a blocked resource gate, missing artifact, package/import error, timeout, OOM, unsupported profile, or failed WAV check, preserve the structured report and explain the precise status. Do not claim inference succeeded because a model was downloaded or a package imported. Do not retry by bypassing CPU, RAM, disk, thread, file-size, offline, or timeout safeguards. `ENGINE_PATH_NOT_VERIFIED` and `PROFILE_MODE_NOT_VERIFIED` mean the requested mode is intentionally unavailable until it passes real WAV acceptance.

## Host installation

The Skill directory is portable, but native imports and paths vary by agent. Use the matching package layout rather than editing host configuration blindly; see `references/platform-compatibility.md`. This package is a local Python workflow, not an Android APK or hosted TTS API.
