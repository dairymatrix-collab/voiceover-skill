# D0-251–D0-280 Task Ledger — Explicit, Isolated TTS Engine Setup

Batch goal: add an explicit, safe engine setup workflow while being honest that current runtime cannot access package/model registries. The default must remain plan-only. Package installation must require an explicit flag and must not claim acoustic inference.

| Task | Acceptance condition | Status |
|---|---|---|
| D0-251 | Add reusable engine setup module | PASS — `engine_setup.py` |
| D0-252 | Reuse only declared engine IDs/distribution names | PASS — strict engine allowlist |
| D0-253 | Default to plan-only behavior | PASS — no venv/filesystem side effect |
| D0-254 | Require explicit `install=True` for pip work | PASS — CLI flag required |
| D0-255 | Restrict install target to a new/empty directory | PASS — nonempty path preserved and rejected |
| D0-256 | Reject unsafe root paths | PASS — root/home and symlink root rejected |
| D0-257 | Validate selected Python executable | PASS — NUL/empty values rejected |
| D0-258 | Probe interpreter before venv creation | PASS — failed probe creates no environment |
| D0-259 | Apply conservative Python 3.10–3.12 project policy | PASS — 3.13 blocked before changes |
| D0-260 | Validate timeout values including NaN/Inf | PASS — 37 setup tests include boundary cases |
| D0-261 | Use argv lists with shell disabled | PASS — no shell invocation |
| D0-262 | Avoid interactive pip prompts | PASS — stdin DEVNULL and PIP_NO_INPUT |
| D0-263 | Keep setup subprocess output bounded | PASS — tail capped at 128 KiB per stream |
| D0-264 | Redact common credential-like log values | PASS — regression test |
| D0-265 | Support optional local wheelhouse | PASS — path validated |
| D0-266 | Require wheelhouse for no-index mode | PASS — fail-closed error |
| D0-267 | Use a sanitized child environment | PASS — minimal PATH/HOME/pip variables, plus SYSTEMROOT on Windows |
| D0-268 | Apply install subprocess timeout | PASS — bounded command timeout |
| D0-269 | Run pip dependency consistency check | PASS — `pip check` gate |
| D0-270 | Probe import module after install | PASS — module discovery gate |
| D0-271 | Separate package-ready from inference-ready | PASS — `inference_verified` fixed false |
| D0-272 | Never download model weights during setup | PASS — setup code does not load model APIs |
| D0-273 | Add atomic JSON report writer | PASS — temporary sibling and replace |
| D0-274 | Add setup report schema | PASS — Draft 2020-12 validation in tests |
| D0-275 | Add CLI plan-only path | PASS — subprocess CLI test |
| D0-276 | Add CLI report file output | PASS — stdout/report parity test |
| D0-277 | Add structured blocked report for invalid offline setup | PASS — schema-valid `BLOCKED` response |
| D0-278 | Add install failure, pip conflict and import-missing tests | PASS — mocked subprocess branches |
| D0-279 | Add README instructions for online/offline setup | PASS — documents explicit opt-in and limits |
| D0-280 | Re-run tests, inspect network and keep real-inference claim honest | PARTIAL — 37 setup tests pass; PyPI and Hugging Face DNS unavailable; no engine installed and no real audio generated |

## Verification policy

The tests mock package-install subprocesses where necessary; they verify control flow and failure handling, not that third-party wheels can be installed. The real package registry probes failed with DNS resolution errors (`Temporary failure in name resolution`) for both PyPI and Hugging Face. Do not count that as an install attempt or an inference test.

A `PACKAGE_READY` status only means venv package install, `pip check`, and module discovery passed. The report schema requires `model_downloaded=false` and `inference_verified=false`; only the independent real-inference smoke test can verify generated speech.

## Final fresh-extraction release verification

- Targeted setup tests: **37 passed**.
- Full test inventory passed in non-overlapping groups from a fresh extraction: **672 passed** (151 audio/adapters/pipeline/preflight; 120 audit/contracts/docs; 61 evidence/schema; 10 evidence CLI; 101 runtime worker + IPC; 30 JSONL/consumer E2E; 50 isolation/protocol/provider; 62 report-writer/packaging; 87 engine setup/request mapping/environment diagnostics).
- Monolithic test run exceeded the 180-second command timeout at about 32%; it is not claimed as a single-command pass. All disjoint test groups passed individually.
- Archive: 91 members, no duplicate names, CRC PASS, 90/90 manifest entries, 61 Python files compiled, 10 schemas checked, reproducible build PASS.
- Final ZIP SHA-256 is recorded in the external discovery ledger; the embedded task ledger omits its own enclosing ZIP digest to avoid a self-reference.
- Real inference remains **BLOCKED** (`PREFERRED_ENGINE_UNAVAILABLE`); PyPI/Hugging Face DNS unavailable; no model download or WAV generation.

Batch verdict: **PASS for setup tooling and packaged test evidence; BLOCKED for real TTS inference.** Phase 0 remains OPEN / HOLD.
