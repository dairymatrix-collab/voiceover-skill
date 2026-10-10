#!/usr/bin/env python3
"""Create, inspect, update, list and delete reusable local voice profiles."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from voice_profile_store import (
    ProfileStoreError,
    create_profile,
    default_store_dir,
    delete_profile,
    list_profiles,
    load_profile,
    update_controls,
)
from voice_controls import VERIFIED_PROFILE_MODES


ENGINES = ("kokoro", "qwen3_tts")
MODES = ("preset", "voice_design")
MAX_VOICE_DESCRIPTION_CHARS = 1600


def parse_controls(values: list[str] | None) -> dict[str, Any]:
    controls: dict[str, Any] = {}
    for item in values or []:
        if not isinstance(item, str) or "=" not in item:
            raise ValueError("CONTROL_MUST_BE_KEY_VALUE")
        key, raw = item.split("=", 1)
        if not key or key in controls:
            raise ValueError("CONTROL_DUPLICATE_OR_EMPTY")
        try:
            controls[key] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("CONTROL_VALUE_MUST_BE_JSON_SCALAR") from exc
        if isinstance(controls[key], (dict, list)):
            raise ValueError("CONTROL_VALUE_MUST_BE_SCALAR")
    return controls


def summary(profile: dict[str, Any], *, include_prompt: bool = False) -> dict[str, Any]:
    result = {
        "profile_id": profile["profile_id"],
        "name": profile["name"],
        "engine_id": profile["engine_id"],
        "mode": profile["mode"],
        "language": profile["language"],
        "voice_id": profile["voice_id"],
        "controls": profile["controls"],
        "reference_asset_saved": profile["reference_asset"] is not None,
        "synthesis_supported": (profile["engine_id"], profile["mode"]) in VERIFIED_PROFILE_MODES,
    }
    if include_prompt:
        result["voice_description"] = profile["voice_description"]
    else:
        result["voice_description_saved"] = profile["voice_description"] is not None
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, help="profile-store root (default: user data directory)")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list", help="list profiles without voice prompts or filesystem paths")

    show = commands.add_parser("show", help="show one profile, including its voice description")
    show.add_argument("profile_id")

    create = commands.add_parser("create", help="create a reusable profile")
    create.add_argument("--profile-id", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--engine", required=True, choices=ENGINES)
    create.add_argument("--mode", required=True, choices=MODES)
    create.add_argument("--language", required=True)
    create.add_argument("--voice-id")
    description = create.add_mutually_exclusive_group()
    description.add_argument("--voice-description")
    description.add_argument("--voice-description-file", type=Path,
                             help="read a UTF-8 prompt file (maximum 1,600 characters)")
    create.add_argument("--control", action="append", default=[], metavar="KEY=JSON_VALUE")

    update = commands.add_parser("update-controls", help="merge supported controls into an existing profile")
    update.add_argument("profile_id")
    update.add_argument("--control", action="append", required=True, metavar="KEY=JSON_VALUE")

    delete = commands.add_parser("delete", help="delete one profile and its fixed profile-owned reference WAV")
    delete.add_argument("profile_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store_dir = args.store if args.store is not None else default_store_dir()
    try:
        if args.command == "list":
            profiles = list_profiles(store_dir)
            payload = {"ok": True, "profiles": [summary(profile) for profile in profiles]}
        elif args.command == "show":
            payload = {"ok": True, "profile": summary(load_profile(store_dir, args.profile_id), include_prompt=True)}
        elif args.command == "create":
            if (args.engine, args.mode) not in VERIFIED_PROFILE_MODES:
                raise ValueError("PROFILE_MODE_NOT_VERIFIED")
            voice_description = args.voice_description
            if args.voice_description_file is not None:
                prompt_path = args.voice_description_file.expanduser()
                try:
                    if prompt_path.is_symlink() or not prompt_path.is_file():
                        raise ValueError("VOICE_DESCRIPTION_FILE_INVALID")
                    with prompt_path.open("rb") as stream:
                        prompt_bytes = stream.read(MAX_VOICE_DESCRIPTION_CHARS * 4 + 1)
                    if len(prompt_bytes) > MAX_VOICE_DESCRIPTION_CHARS * 4:
                        raise ValueError("VOICE_DESCRIPTION_FILE_TOO_LARGE")
                    voice_description = prompt_bytes.decode("utf-8")
                    if len(voice_description) > MAX_VOICE_DESCRIPTION_CHARS:
                        raise ValueError("VOICE_DESCRIPTION_FILE_TOO_LARGE")
                except (OSError, UnicodeError) as exc:
                    raise ValueError("VOICE_DESCRIPTION_FILE_INVALID") from exc
            profile = create_profile(
                store_dir,
                profile_id=args.profile_id,
                name=args.name,
                engine_id=args.engine,
                mode=args.mode,
                language=args.language,
                voice_id=args.voice_id,
                voice_description=voice_description,
                controls=parse_controls(args.control),
            )
            payload = {"ok": True, "profile": summary(profile)}
        elif args.command == "update-controls":
            profile = update_controls(store_dir, args.profile_id, parse_controls(args.control))
            payload = {"ok": True, "profile": summary(profile)}
        elif args.command == "delete":
            delete_profile(store_dir, args.profile_id)
            payload = {"ok": True, "deleted_profile_id": args.profile_id}
        else:
            raise ValueError("COMMAND_UNSUPPORTED")
    except (ProfileStoreError, ValueError) as exc:
        code = exc.code if isinstance(exc, ProfileStoreError) else str(exc).split(":", 1)[0]
        print(json.dumps({"ok": False, "error": code}, sort_keys=True))
        return 2
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
