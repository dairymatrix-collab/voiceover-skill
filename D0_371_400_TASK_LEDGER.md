# D0-371–D0-400 Task Ledger

## Mission
Strengthen neural-TTS installation readiness without fake inference claims: inspect local model artifacts deterministically, preserve isolation, validate schemas, and package the new capability reproducibly.

| Range | Work | Status | Evidence |
|---|---|---|---|
| 371–374 | Define artifact readiness contract and engine artifact inventory | PASS | `tts_artifact_readiness.py` |
| 375–378 | Add Kokoro/Qwen3-TTS/Chatterbox artifact discovery | PASS | `ENGINE_ARTIFACTS` + tests |
| 379–382 | Reject model-root path escape via symlinks | PASS | `test_symlink_outside_root_is_rejected` |
| 383–386 | Add optional deterministic SHA-256 file evidence | PASS | `test_kokoro_artifacts` |
| 387–390 | Add JSON schema v1 | PASS | schema validation test |
| 391–394 | Add CLI with honest exit semantics | PASS | CLI test |
| 395–397 | Update README/engine documentation | PASS | documentation files |
| 398–399 | Regression tests | PASS | 17/17 new+runtime tests; 176/176 affected-area group |
| 400 | Package/reproducibility/fresh extraction verification | PASS | build evidence |

## Non-goals
- No package installation.
- No model download.
- No model loading.
- No synthetic/fake neural output.
- No `inference_verified=true` from artifact presence alone.

## External technical evidence reviewed
- Kokoro package metadata: Python 3.11–3.12 target.
- Qwen3-TTS project documentation: isolated Python 3.12 recommendation and local model-directory loading/manual weight-download path.
- Chatterbox ecosystem documentation: Python/uv setup and model-weight requirements vary by backend/runtime.
