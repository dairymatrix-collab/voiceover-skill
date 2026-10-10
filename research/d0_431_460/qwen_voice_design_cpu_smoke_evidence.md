# Qwen VoiceDesign CPU smoke evidence — 2026-10-10

A pinned Qwen VoiceDesign snapshot was acquired and passed the local artifact-readiness checks. One real profile-backed CPU smoke was then attempted in the isolated Python 3.12 engine environment with a 300-second deadline, two CPU threads, 14-GiB available-RAM preflight, and the fixed 10-GiB process-tree RSS ceiling.

The run failed with `RESOURCE_LIMIT_EXCEEDED`; the worker returned 137 and the smoke report correctly leaves `inference_verified=false`. The output directory contains no audio files, so no partial WAV is deliverable. In `resource_guard.py`, this error is emitted when monitored process-tree RSS exceeds the fixed `qwen3_tts` cap of 10,240 MiB and the process tree is terminated. The smoke report does not preserve the observed peak value; none is inferred or reported here. The resource cap was not raised and no retry was made.

Evidence: `qwen_voice_design_cpu_smoke_report.json`; fixed policy in `resource_guard.py`; the monitored runner's 300-second command is recorded in the task history. Artifact availability and CPU package readiness do not upgrade this result to a successful inference claim. A larger-memory host or a reviewed low-memory loader optimization may be evaluated separately under the same safety policy.
