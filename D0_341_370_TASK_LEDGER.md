# D0-341–D0-370 Task Ledger

Batch goal: make Python-runtime acquisition blockers machine-detectable and preserve strict evidence boundaries. No runtime or package installation is performed by this batch.

| Task | Item | Status | Evidence |
|---:|---|---|---|
| D0-341 | Fork previous verified harness | PASS | Source copied from D0-311–340 |
| D0-342 | Recheck active Python runtime | PASS | Python 3.13.5 |
| D0-343 | Recheck supported interpreter policy | PASS | Project policy remains Python 3.10–3.12 |
| D0-344 | Recheck uv availability | PASS | `/opt/pyvenv/bin/uv` available |
| D0-345 | Enumerate uv-supported Python candidates | PASS | uv lists 3.10/3.11/3.12 as downloadable candidates |
| D0-346 | Check local Python 3.12 executable | PASS | No local python3.12 executable discovered |
| D0-347 | Check local Python 3.11 executable | PASS | No local python3.11 executable discovered |
| D0-348 | Check local Python 3.10 executable | PASS | No local python3.10 executable discovered |
| D0-349 | Check installed TTS modules | PASS | kokoro/chatterbox/qwen_tts/transformers absent |
| D0-350 | Check PyTorch baseline | PASS | torch present in active 3.13 environment |
| D0-351 | Check local eSpeak baseline | PASS | `/usr/bin/espeak` available |
| D0-352 | Attempt offline uv 3.12 acquisition | PASS / BLOCKED | uv reports requested archive absent from cache |
| D0-353 | Capture acquisition blocker without secrets | PASS | Only status/error classification retained |
| D0-354 | Define read-only acquisition contract | PASS | Installation and acquisition claims remain false |
| D0-355 | Add uv cache inventory | PASS | New `python_runtime_acquisition.py` |
| D0-356 | Add supported-version validation | PASS | 3.10/3.11/3.12 only |
| D0-357 | Add bounded cache traversal | PASS | Symlink-safe, bounded file count |
| D0-358 | Add uv executable discovery | PASS | PATH-based, no shell |
| D0-359 | Add offline-only acquisition probe | PASS | `uv python install ... --offline` |
| D0-360 | Add timeout handling | PASS | Bounded subprocess timeout |
| D0-361 | Classify offline cache miss | PASS | Dedicated `OFFLINE_CACHE_MISS` status |
| D0-362 | Distinguish probe success from installation | PASS | `runtime_acquired=false` invariant |
| D0-363 | Add collection across supported versions | PASS | 3.12, 3.11, 3.10 |
| D0-364 | Add machine-readable schema | PASS | `python-runtime-acquisition-v1.schema.json` |
| D0-365 | Add unit tests | PASS | 8 tests |
| D0-366 | Add real-environment CLI test | PASS | Actual uv invocation |
| D0-367 | Verify existing regression suite subset | PASS | 68/68 tests passed with explicit project-root PYTHONPATH |
| D0-368 | Update documentation/evidence ledger | PASS | Batch ledger + runtime diagnostic docs |
| D0-369 | Rebuild package | PASS | Package rebuilt and fresh extraction verified |
| D0-370 | Re-verify neural inference acceptance gate | OPEN / BLOCKED | Fresh extraction still has no supported runtime or neural engine package; no inference claim made |

## Evidence boundary

A successful offline uv command is not treated as an installation claim by this diagnostic. A real neural TTS PASS still requires a supported interpreter, compatible engine dependencies, model assets, actual inference, and independent audio validation.
