#!/usr/bin/env python3
"""Generate and objectively inspect a short offline eSpeak baseline WAV.

This is a system-TTS diagnostic, NOT a neural TTS engine and NOT proof that
Kokoro, Chatterbox, or Qwen3-TTS can load or synthesize speech.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from audio_quality import AudioQualityError, inspect_wav

MAX_TEXT_CHARS = 20_000
MAX_AUDIO_BYTES = 50_000_000
LANGUAGES = {"en", "en-us", "en-gb", "es", "fr", "de", "it", "pt", "ru", "hi", "zh", "ar"}


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().absolute()
    if path.is_symlink():
        raise ValueError("REPORT_PATH_IS_SYMLINK")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def generate_probe(text: str, output: str | Path, *, language: str = "en", speed: int = 165,
                   timeout_seconds: float = 30, overwrite: bool = False,
                   executable: str | None = None) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip() or "\x00" in text or len(text) > MAX_TEXT_CHARS:
        raise ValueError("INVALID_TEXT")
    if not isinstance(language, str) or language.lower() not in LANGUAGES:
        raise ValueError("UNSUPPORTED_ESPEAK_LANGUAGE")
    if isinstance(speed, bool) or not isinstance(speed, int) or not 80 <= speed <= 450:
        raise ValueError("INVALID_SPEED")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 1 <= timeout_seconds <= 120:
        raise ValueError("INVALID_TIMEOUT")
    path = Path(output).expanduser().absolute()
    if path.suffix.lower() != ".wav" or path.name in {".", ".."}:
        raise ValueError("OUTPUT_MUST_BE_WAV")
    if path.is_symlink():
        raise ValueError("OUTPUT_PATH_IS_SYMLINK")
    if path.exists() and not overwrite:
        raise ValueError("OUTPUT_ALREADY_EXISTS")
    binary = executable or shutil.which("espeak-ng") or shutil.which("espeak")
    if not binary:
        return {"schema_version": 1, "status": "BLOCKED", "error": "ESPEAK_EXECUTABLE_MISSING",
                "diagnostic_only": True, "neural_engine": False, "inference_verified": False,
                "speech_output_verified": False}
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a sibling temp file so a failed child cannot leave a partial final WAV.
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".wav.tmp", dir=path.parent)
    os.close(fd)
    temp = Path(tmp_name)
    started = time.monotonic()
    try:
        argv = [binary, "-v", language.lower(), "-s", str(speed), "-w", str(temp), text]
        try:
            child = subprocess.run(argv, shell=False, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   timeout=float(timeout_seconds), check=False)
        except subprocess.TimeoutExpired:
            return {"schema_version": 1, "status": "BLOCKED", "error": "ESPEAK_TIMEOUT",
                    "elapsed_ms": round((time.monotonic()-started)*1000), "diagnostic_only": True,
                    "neural_engine": False, "inference_verified": False, "speech_output_verified": False}
        except OSError as exc:
            return {"schema_version": 1, "status": "BLOCKED", "error": "ESPEAK_LAUNCH_FAILED",
                    "detail_type": type(exc).__name__, "diagnostic_only": True,
                    "neural_engine": False, "inference_verified": False, "speech_output_verified": False}
        if child.returncode != 0 or not temp.is_file():
            return {"schema_version": 1, "status": "FAIL", "error": "ESPEAK_FAILED",
                    "exit_code": child.returncode, "diagnostic_only": True,
                    "neural_engine": False, "inference_verified": False, "speech_output_verified": False}
        if temp.stat().st_size > MAX_AUDIO_BYTES:
            return {"schema_version": 1, "status": "FAIL", "error": "AUDIO_TOO_LARGE",
                    "diagnostic_only": True, "neural_engine": False, "inference_verified": False,
                    "speech_output_verified": False}
        payload = temp.read_bytes()
        try:
            quality = inspect_wav(payload, max_bytes=MAX_AUDIO_BYTES).to_dict()
        except AudioQualityError as exc:
            return {"schema_version": 1, "status": "FAIL", "error": str(exc),
                    "diagnostic_only": True, "neural_engine": False,
                    "inference_verified": False, "speech_output_verified": False}
        if quality["all_silent"] or quality["duration_seconds"] <= 0 or quality["rms_normalized"] <= 0:
            return {"schema_version": 1, "status": "FAIL", "error": "GENERATED_AUDIO_SILENT",
                    "audio_quality": quality, "diagnostic_only": True, "neural_engine": False,
                    "inference_verified": False, "speech_output_verified": False}
        # Publish only validated audio. Hard-link creation is atomic and refuses
        # a last-moment collision when overwrite was not explicitly requested.
        if overwrite:
            os.replace(temp, path)
        else:
            try:
                os.link(temp, path)
            except FileExistsError as exc:
                raise ValueError("OUTPUT_ALREADY_EXISTS") from exc
            temp.unlink()
        return {"schema_version": 1, "status": "PASS", "engine_id": "espeak_offline",
                "engine_kind": "system_formant_tts", "diagnostic_only": True,
                "neural_engine": False, "inference_verified": False, "speech_output_verified": True,
                "text_characters": len(text), "language": language.lower(), "speed_wpm": speed,
                "output_file": path.name, "sha256": hashlib.sha256(payload).hexdigest(),
                "elapsed_ms": round((time.monotonic()-started)*1000), "audio_quality": quality,
                "limitations": ["This is a system/formant TTS baseline, not Kokoro, Chatterbox, or Qwen3-TTS.",
                                "Signal metrics do not verify pronunciation, intelligibility, or language correctness."]}
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text")
    source.add_argument("--text-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", default="en", choices=sorted(LANGUAGES))
    parser.add_argument("--speed", type=int, default=165, help="eSpeak words per minute (80–450)")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    try:
        if args.report and args.report.expanduser().absolute() == args.output.expanduser().absolute():
            raise ValueError("REPORT_PATH_EQUALS_AUDIO_PATH")
        text = args.text if args.text is not None else args.text_file.read_text(encoding="utf-8")
        result = generate_probe(text, args.output, language=args.language, speed=args.speed,
                                timeout_seconds=args.timeout, overwrite=args.overwrite)
        if args.report:
            _atomic_json(args.report, result)
    except (OSError, UnicodeError):
        result = {"schema_version": 1, "status": "FAIL", "error": "INPUT_OR_OUTPUT_IO_ERROR",
                  "diagnostic_only": True, "neural_engine": False, "inference_verified": False,
                  "speech_output_verified": False}
    except ValueError as exc:
        result = {"schema_version": 1, "status": "FAIL", "error": str(exc),
                  "diagnostic_only": True, "neural_engine": False, "inference_verified": False,
                  "speech_output_verified": False}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2 if args.pretty else None, allow_nan=False))
    return 0 if result.get("status") == "PASS" else (3 if result.get("status") == "BLOCKED" else 2)

if __name__ == "__main__":
    raise SystemExit(main())
