#!/usr/bin/env python3
"""Attempt one real TTS request and verify the resulting WAV artifact.

A PASS is emitted only after the real worker returns success and a valid audio
file passes objective duration, silence, and clipping thresholds. This does not
prove linguistic correctness or subjective voice quality.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from audio_quality import AudioQualityError, inspect_wav

BLOCKED_ERRORS = {
    "NO_COMPATIBLE_ENGINE", "PREFERRED_ENGINE_UNAVAILABLE", "ENGINE_DEPENDENCY_MISSING",
    "ENGINE_MODEL_LOAD_FAILED", "VOICE_REFERENCE_NOT_FOUND",
}


def _atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def evaluate_result(worker_data: object, worker_return_code: int, output_dir: Path,
                    *, min_duration: float, max_duration: float,
                    max_silence_ratio: float, max_clipping_ratio: float) -> dict:
    report = {
        "schema_version": 1,
        "status": "FAIL",
        "inference_verified": False,
        "worker_return_code": worker_return_code,
        "checks": [],
    }
    if not isinstance(worker_data, dict) or not isinstance(worker_data.get("ok"), bool):
        report["status"] = "FAIL"
        report["error"] = "WORKER_PROTOCOL_ERROR"
        return report
    if not worker_data["ok"]:
        error = worker_data.get("error", "WORKER_FAILED")
        report["error"] = error
        report["status"] = "BLOCKED" if error in BLOCKED_ERRORS else "FAIL"
        report["checks"].append({"id": "worker_result", "status": report["status"], "detail": error})
        return report
    result = worker_data.get("result")
    if not isinstance(result, dict):
        report["error"] = "WORKER_RESULT_INVALID"
        return report
    output_path = Path(str(result.get("output_path", "")))
    try:
        resolved_root = output_dir.resolve()
        resolved_audio = output_path.resolve(strict=True)
        if resolved_audio.parent != resolved_root or not resolved_audio.is_file():
            raise OSError("output path is outside expected directory")
        payload = resolved_audio.read_bytes()
    except (OSError, RuntimeError):
        report["error"] = "AUDIO_ARTIFACT_MISSING_OR_UNSAFE"
        report["checks"].append({"id": "audio_artifact", "status": "FAIL", "detail": report["error"]})
        return report
    try:
        quality = inspect_wav(payload).to_dict()
    except AudioQualityError as exc:
        report["error"] = str(exc)
        report["checks"].append({"id": "audio_decode", "status": "FAIL", "detail": str(exc)})
        return report
    expected_sha = result.get("sha256")
    digest = hashlib.sha256(payload).hexdigest()
    integrity_ok = expected_sha == digest and result.get("size_bytes") == len(payload)
    duration = quality["duration_seconds"]
    duration_ok = min_duration <= duration <= max_duration
    duration_match = isinstance(result.get("duration_seconds"), (int, float)) and not isinstance(result.get("duration_seconds"), bool) and math.isfinite(result["duration_seconds"]) and abs(float(result["duration_seconds"]) - duration) <= 1e-6
    manifest_ok = False
    manifest_path_value = result.get("manifest_path")
    if isinstance(manifest_path_value, str) and manifest_path_value:
        try:
            manifest_path = Path(manifest_path_value).resolve(strict=True)
            if manifest_path.parent == resolved_root and manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                audio_entry = manifest.get("audio", {}) if isinstance(manifest, dict) else {}
                manifest_ok = (manifest.get("request_id") == result.get("request_id") and
                               manifest.get("engine_id") == result.get("engine_id") and
                               audio_entry.get("file") == resolved_audio.name and
                               audio_entry.get("sha256") == digest and
                               audio_entry.get("size_bytes") == len(payload) and
                               audio_entry.get("sample_rate_hz") == quality["sample_rate_hz"] and
                               audio_entry.get("frames") == quality["frames"] and
                               isinstance(audio_entry.get("duration_seconds"), (int, float)) and
                               abs(float(audio_entry["duration_seconds"]) - duration) <= 1e-6)
        except (OSError, UnicodeError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
            manifest_ok = False
    silence_ok = quality["silent_frame_ratio"] <= max_silence_ratio
    clipping_ok = quality["clipping_sample_ratio"] <= max_clipping_ratio
    checks = [
        ("audio_integrity", integrity_ok, "SHA-256 and byte-size match pipeline result"),
        ("manifest_integrity", manifest_ok, "manifest identity, audio digest, size and WAV metadata match"),
        ("duration_match", duration_match, "pipeline duration matches decoded WAV duration"),
        ("duration", duration_ok, f"duration={duration:.6f}s; expected [{min_duration}, {max_duration}]s"),
        ("silence_ratio", silence_ok, f"silent_frame_ratio={quality['silent_frame_ratio']:.6f}; maximum={max_silence_ratio}"),
        ("clipping_ratio", clipping_ok, f"clipping_sample_ratio={quality['clipping_sample_ratio']:.6f}; maximum={max_clipping_ratio}"),
        ("audio_decode", True, "WAV decoded and PCM frame count verified"),
    ]
    report["checks"] = [{"id": key, "status": "PASS" if ok else "FAIL", "detail": detail}
                        for key, ok, detail in checks]
    report["audio"] = {"file": resolved_audio.name, **quality}
    report["engine_id"] = result.get("engine_id")
    report["request_id"] = result.get("request_id")
    report["inference_verified"] = all(ok for _, ok, _ in checks)
    report["status"] = "PASS" if report["inference_verified"] else "FAIL"
    if report["status"] != "PASS":
        report["error"] = "AUDIO_ACCEPTANCE_FAILED"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path, help="UTF-8 JSON synthesis request")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--engine", choices=("qwen3_tts", "chatterbox", "kokoro"))
    parser.add_argument("--profile-store", type=Path,
                        help="local profile-store root for version-2 profile-backed requests")
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--min-duration", type=float, default=0.05)
    parser.add_argument("--max-duration", type=float, default=600.0)
    parser.add_argument("--max-silence-ratio", type=float, default=0.98)
    parser.add_argument("--max-clipping-ratio", type=float, default=0.01)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    numeric = ((args.timeout_seconds, 0.1, 86400, "timeout-seconds"),
               (args.min_duration, 0.001, 86400, "min-duration"),
               (args.max_duration, 0.001, 86400, "max-duration"),
               (args.max_silence_ratio, 0.0, 1.0, "max-silence-ratio"),
               (args.max_clipping_ratio, 0.0, 1.0, "max-clipping-ratio"))
    for value, low, high, name in numeric:
        if isinstance(value, bool) or not math.isfinite(value) or not low <= value <= high:
            parser.error(f"--{name} must be finite and in [{low}, {high}]")
    if args.min_duration > args.max_duration:
        parser.error("--min-duration cannot exceed --max-duration")
    try:
        request_data = json.loads(args.request.read_text(encoding="utf-8"))
        if not isinstance(request_data, dict):
            raise ValueError("request must be a JSON object")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        report = {"schema_version": 1, "status": "FAIL", "inference_verified": False,
                  "error": "REQUEST_FILE_INVALID", "checks": []}
        _emit(report, args.report, args.pretty)
        return 2
    command = [sys.executable, str(ROOT / "scripts/run_voiceover.py"),
               "--request", str(args.request.resolve()), "--output-dir", str(args.output_dir.resolve()),
               "--timeout-seconds", str(args.timeout_seconds)]
    if args.engine:
        command.extend(["--engine", args.engine])
    if args.profile_store:
        command.extend(["--profile-store", str(args.profile_store.expanduser().resolve())])
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        child = subprocess.run(command, cwd=ROOT, env=env, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=args.timeout_seconds + 5, check=False)
        try:
            worker_data = json.loads(child.stdout)
        except json.JSONDecodeError:
            worker_data = {"ok": False, "error": "WORKER_PROTOCOL_ERROR"}
        report = evaluate_result(worker_data, child.returncode, args.output_dir,
                                 min_duration=args.min_duration, max_duration=args.max_duration,
                                 max_silence_ratio=args.max_silence_ratio,
                                 max_clipping_ratio=args.max_clipping_ratio)
    except subprocess.TimeoutExpired:
        report = {"schema_version": 1, "status": "BLOCKED", "inference_verified": False,
                  "error": "INFERENCE_TIMEOUT", "checks": []}
    except OSError:
        report = {"schema_version": 1, "status": "FAIL", "inference_verified": False,
                  "error": "WORKER_LAUNCH_FAILED", "checks": []}
    report = _emit(report, args.report, args.pretty, protected_output_dir=args.output_dir)
    return 0 if report.get("status") == "PASS" else (3 if report.get("status") == "BLOCKED" else 2)


def _emit(report: dict, path: Path | None, pretty: bool, *, protected_output_dir: Path | None = None) -> dict:
    if path:
        if protected_output_dir is not None and isinstance(report.get("audio"), dict):
            audio_name = report["audio"].get("file")
            if isinstance(audio_name, str):
                audio_path = (protected_output_dir / audio_name).resolve()
                try:
                    report_path = path.expanduser().resolve()
                except OSError:
                    report_path = path.expanduser().absolute()
                if report_path == audio_path:
                    report = {"schema_version": 1, "status": "FAIL", "inference_verified": False,
                              "error": "REPORT_PATH_COLLIDES_WITH_AUDIO", "checks": []}
                    path = None
        if path:
            _atomic_json(path, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True,
                     indent=2 if pretty else None, allow_nan=False))
    return report


if __name__ == "__main__":
    raise SystemExit(main())
