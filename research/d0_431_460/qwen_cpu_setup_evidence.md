# Qwen CPU setup evidence

Date: 2026-10-10

`research/d0_431_460/qwen_setup_cpu_report.json` records the bounded installation in the dedicated `/workspace/voiceover_qwen_cpu_py312` environment. The report status is `PACKAGE_READY`; it confirms CPU-only `torch==2.6.0+cpu` and `torchaudio==2.6.0+cpu`, `qwen-tts==0.1.1`, `transformers==4.57.3`, and the declared direct runtime packages installed successfully, with an empty `missing_modules` result.

This verifies runtime package readiness only. The setup report correctly records `model_downloaded=false` and `inference_verified=false`; neither weights nor generated audio were produced by package installation. The next Qwen step is a separate allowlisted download under a fresh 14-GiB RAM/disk resource preflight, followed by a time/RSS/thread-bounded CPU smoke and independent WAV quality inspection.
