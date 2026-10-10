#!/usr/bin/env python3
"""Build reproducible standalone Skill, Claude Code, MiniMax Code, and marketplace ZIP packages.

The output contains source code and schemas only; no Python runtime, TTS weights,
credentials, installer hooks, or platform-specific native binaries are bundled.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKILL_SOURCE = ROOT / "skills" / "voiceover-skill"
ICON_SOURCE = SKILL_SOURCE / "assets" / "voiceover.png"
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)
MAX_MEMBERS = 1000
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
ASCII_PATH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")

BACKEND_MODULES = (
    "audio_quality.py", "cache_paths.py", "contracts.py", "engine_setup.py",
    "file_locking.py", "ipc_contract.py", "resource_guard.py", "runtime_worker.py",
    "tts_artifact_readiness.py", "tts_engine_adapters.py", "tts_environment.py",
    "tts_model_catalog.py", "tts_runtime_preflight.py", "voice_controls.py",
    "voice_profile_store.py", "voiceover_pipeline.py", "voiceover_preflight.py",
)
BACKEND_SCRIPTS = (
    "diagnose_tts_environment.py", "download_tts_model.py", "inspect_tts_artifacts.py",
    "inspect_voiceover_audio.py", "preflight_tts_install.py", "preflight_tts_resources.py",
    "preflight_voiceover.py", "real_inference_smoke.py", "run_voiceover.py",
    "setup_tts_engine.py", "voice_profiles.py", "voiceover_worker.py",
)
PLUGIN_DESCRIPTION = (
    "A local, resource-guarded TTS workflow for reusable voice profiles, prompt-designed narration, and verified WAV output."
)
PLUGIN_NAME = "voiceover-skill"


def _copy_regular(source: Path, target: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"package input is not a regular file: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _copy_skill_directory(target: Path) -> None:
    _copy_regular(SKILL_SOURCE / "SKILL.md", target / "SKILL.md")
    for folder in ("references", "templates"):
        source_folder = SKILL_SOURCE / folder
        if not source_folder.is_dir() or source_folder.is_symlink():
            raise ValueError(f"missing skill resource directory: {source_folder}")
        for source in sorted(source_folder.rglob("*")):
            if source.is_symlink():
                raise ValueError(f"symlink is not permitted in a package input: {source}")
            if source.is_file():
                _copy_regular(source, target / folder / source.relative_to(source_folder))
    backend = target / "backend"
    for name in BACKEND_MODULES:
        _copy_regular(ROOT / name, backend / name)
    for name in BACKEND_SCRIPTS:
        _copy_regular(ROOT / "scripts" / name, backend / "scripts" / name)
    schema_source = ROOT / "schemas"
    if not schema_source.is_dir() or schema_source.is_symlink():
        raise ValueError("schemas directory is required")
    schema_files = sorted(schema_source.glob("*.json"))
    if not schema_files:
        raise ValueError("no backend JSON schemas found")
    for source in schema_files:
        _copy_regular(source, backend / "schemas" / source.name)
    _copy_regular(ROOT / "requirements-skill.txt", backend / "requirements-skill.txt")


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8", newline="\n")


def _root_readme(kind: str) -> str:
    if kind == "minimax_code":
        return """# Voiceover Skill — MiniMax Code compatibility package

This ZIP targets both MiniMax Code versions with their required parallel layouts: root `plugin.json` for Agent Plugins 1.0 / mcode 0.3.x, and `.claude-plugin/plugin.json` plus top-level `skills/SKILL.md` for mcode 0.4.0+. `skills/voiceover-skill/SKILL.md` is byte-identical to the top-level Skill entry point for the older runtime/validator.

This is a Code compatibility package, not a Marketplace submission ZIP. For third-party submission use the separate `voiceover-minimax-marketplace-plugin.zip`, which contains only the native `.minimax-plugin` entry point.

The Skill invokes bundled Python scripts through an explicit interpreter. It contains no model weights, native binaries, secrets, install lifecycle hooks, Hooks, or MCP servers.
"""
    if kind == "minimax_submission":
        return """# Voiceover Skill — MiniMax Agent Plugin submission package

This ZIP uses the native third-party MiniMax submission format. Its only Plugin manifest is `.minimax-plugin/plugin.json` at the ZIP root, and it references `skills/voiceover-skill/SKILL.md`. There is no wrapper directory and no MiniMax Code/Claude compatibility manifest mixed into this submission package.

The Skill invokes bundled Python scripts through an explicit interpreter. It contains no model weights, native binaries, secrets, install lifecycle hooks, Hooks, or MCP servers. Engine runtimes and model files remain separate and must be acquired under the resource gates described in `skills/voiceover-skill/SKILL.md`.
"""
    return """# Voiceover Skill Plugin

This package is a Claude Code Plugin with a portable `skills/voiceover-skill/` directory and a `.claude-plugin/plugin.json` manifest whose `skills` entry names that Skill directory. It is separate from the MiniMax Code 0.4 compatibility package, whose manifest points to a top-level `skills/SKILL.md` file.

Use the bundled Skill instructions for local setup and execution. Model weights and engine runtimes are not bundled. No installer hooks, MCP server, credentials, or native binaries are included.
"""


def _portable_manifest() -> dict:
    return {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        "name": PLUGIN_NAME,
    }


def _minimax_manifest() -> dict:
    return {
        "schemaVersion": 1,
        "name": PLUGIN_NAME,
        "displayName": "Local Voiceover Skill",
        "version": "1.0.0",
        "description": PLUGIN_DESCRIPTION,
        "author": "Voiceover Skill project",
        "icon": "assets/voiceover.png",
        "category": "Productivity",
        "exampleQueries": [
            "Create a local voiceover using my saved narrator profile.",
            "Design a reusable narrator voice from my text prompt and synthesize this script locally.",
            "Check whether my local Qwen VoiceDesign files and WAV output pass the resource and integrity gates.",
        ],
        "apps": [],
        "mcpServers": [],
        "skills": ["skills/voiceover-skill/SKILL.md"],
    }


def _build_standalone(stage: Path) -> None:
    _copy_skill_directory(stage / "voiceover-skill")


def _build_claude(stage: Path) -> None:
    (stage / ".claude-plugin").mkdir(parents=True)
    _write_json(stage / ".claude-plugin" / "plugin.json", {
        "name": PLUGIN_NAME,
        "version": "1.0.0",
        "description": PLUGIN_DESCRIPTION,
        "author": {"name": "Voiceover Skill project"},
        "skills": ["./skills/voiceover-skill"],
    })
    _copy_skill_directory(stage / "skills" / "voiceover-skill")
    (stage / "assets").mkdir(parents=True)
    _copy_regular(ICON_SOURCE, stage / "assets" / "voiceover.png")
    (stage / "README.md").write_text(_root_readme("claude"), encoding="utf-8", newline="\n")


def _build_minimax_code(stage: Path) -> None:
    _write_json(stage / "plugin.json", _portable_manifest())
    _write_json(stage / ".claude-plugin" / "plugin.json", {
        "name": PLUGIN_NAME,
        "version": "1.0.0",
        "description": PLUGIN_DESCRIPTION,
        "skills": "./skills/SKILL.md",
    })
    _copy_skill_directory(stage / "skills")
    _copy_skill_directory(stage / "skills" / PLUGIN_NAME)
    (stage / "assets").mkdir(parents=True)
    _copy_regular(ICON_SOURCE, stage / "assets" / "voiceover.png")
    (stage / "README.md").write_text(_root_readme("minimax_code"), encoding="utf-8", newline="\n")


def _build_minimax_submission(stage: Path) -> None:
    _write_json(stage / ".minimax-plugin" / "plugin.json", _minimax_manifest())
    _copy_skill_directory(stage / "skills" / PLUGIN_NAME)
    (stage / "assets").mkdir(parents=True)
    _copy_regular(ICON_SOURCE, stage / "assets" / "voiceover.png")
    (stage / "README.md").write_text(_root_readme("minimax_submission"), encoding="utf-8", newline="\n")


def _validate_stage(stage: Path, kind: str) -> None:
    if not (stage / "skills" / "voiceover-skill" / "SKILL.md").is_file() and kind != "standalone":
        raise ValueError("nested plugin Skill entry point missing")
    if kind == "standalone" and not (stage / "voiceover-skill" / "SKILL.md").is_file():
        raise ValueError("standalone Skill entry point missing")
    icon = stage / "assets" / "voiceover.png"
    if kind != "standalone":
        payload = icon.read_bytes()
        if len(payload) < 24 or payload[:8] != b"\x89PNG\r\n\x1a\n" or payload[12:16] != b"IHDR":
            raise ValueError("plugin icon is not a valid PNG")
        width = int.from_bytes(payload[16:20], "big")
        height = int.from_bytes(payload[20:24], "big")
        if width < 64 or height < 64 or width != height:
            raise ValueError("plugin icon must be square and at least 64x64 pixels")
    if kind == "minimax_code":
        top_skill = (stage / "skills" / "SKILL.md").read_bytes()
        nested_skill = (stage / "skills" / PLUGIN_NAME / "SKILL.md").read_bytes()
        if top_skill != nested_skill:
            raise ValueError("MiniMax Code 0.4 and 0.3 Skill entry points must be byte-identical")
        portable = json.loads((stage / "plugin.json").read_text(encoding="utf-8"))
        modern = json.loads((stage / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        if set(portable) != {"$schema", "name"}:
            raise ValueError("MiniMax Code 0.3 manifest has properties outside its closed schema")
        if portable.get("$schema") != "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json":
            raise ValueError("MiniMax Code 0.3 manifest schema reference is invalid")
        if modern.get("skills") != "./skills/SKILL.md":
            raise ValueError("MiniMax Code 0.4 Skill file path is invalid")
        if (stage / ".minimax-plugin" / "plugin.json").exists():
            raise ValueError("MiniMax Code archive must not include the Marketplace submission manifest")
    if kind == "minimax_submission":
        submission = json.loads((stage / ".minimax-plugin" / "plugin.json").read_text(encoding="utf-8"))
        if submission.get("skills") != ["skills/voiceover-skill/SKILL.md"] or submission.get("apps") != [] or submission.get("mcpServers") != []:
            raise ValueError("MiniMax marketplace manifest capability paths are invalid")
        if len(submission.get("exampleQueries", [])) > 3 or submission.get("category") != "Productivity":
            raise ValueError("MiniMax marketplace manifest metadata is invalid")
        if (stage / "plugin.json").exists() or (stage / ".claude-plugin").exists():
            raise ValueError("Marketplace ZIP must not include foreign Code/Claude manifests")
    if kind == "claude":
        manifest = json.loads((stage / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        if manifest.get("skills") != ["./skills/voiceover-skill"]:
            raise ValueError("Claude Code Skill path must target the Skill directory")


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(ASCII_PATH_RE.fullmatch(name)) and not path.is_absolute() and "\\" not in name and all(
        part not in {"", ".", ".."} for part in path.parts
    )


def _archive(stage: Path, output: Path) -> str:
    files = sorted((path for path in stage.rglob("*") if path.is_file()),
                   key=lambda path: path.relative_to(stage).as_posix())
    if any(path.is_symlink() for path in files):
        raise ValueError("package staging tree contains a symlink")
    if len(files) > MAX_MEMBERS:
        raise ValueError("package contains too many files")
    total = sum(path.stat().st_size for path in files)
    if total > MAX_UNCOMPRESSED_BYTES:
        raise ValueError("package exceeds the uncompressed size limit")
    names = [path.relative_to(stage).as_posix() for path in files]
    folded = [name.casefold() for name in names]
    if len(set(folded)) != len(names) or any(not _safe_member(name) for name in names):
        raise ValueError("package contains unsafe or colliding paths")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".building", dir=output.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=9, strict_timestamps=True) as archive:
            for source, name in zip(files, names):
                info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                info.flag_bits |= 0x800
                archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED,
                                 compresslevel=9)
        with zipfile.ZipFile(temp_path, "r") as archive:
            if archive.testzip() is not None:
                raise ValueError("ZIP CRC validation failed")
        os.replace(temp_path, output)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return hashlib.sha256(output.read_bytes()).hexdigest()


def _verify_zip(path: Path, kind: str) -> None:
    with zipfile.ZipFile(path, "r") as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) > MAX_MEMBERS or sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError(f"archive limits exceeded: {path.name}")
        if len({name.casefold() for name in names}) != len(names) or any(not _safe_member(name) for name in names):
            raise ValueError(f"unsafe or duplicate path in {path.name}")
        for info in infos:
            if info.flag_bits & 0x1:
                raise ValueError(f"encrypted ZIP member is not allowed: {info.filename}")
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_IFMT(unix_mode) not in {0, stat.S_IFREG}:
                raise ValueError(f"non-regular ZIP member is not allowed: {info.filename}")
        if archive.testzip() is not None:
            raise ValueError(f"ZIP integrity failure: {path.name}")
        contents = {name: archive.read(name) for name in names}
        if kind == "minimax_code":
            expected = {"plugin.json", ".claude-plugin/plugin.json",
                        "skills/SKILL.md", "skills/voiceover-skill/SKILL.md"}
            if not expected.issubset(contents):
                raise ValueError("MiniMax dual-layout required entries are missing")
            if contents["skills/SKILL.md"] != contents["skills/voiceover-skill/SKILL.md"]:
                raise ValueError("MiniMax dual-layout Skill files differ")
            if ".minimax-plugin/plugin.json" in contents:
                raise ValueError("MiniMax Code archive contains the Marketplace submission manifest")
            if "README.md" not in contents:
                raise ValueError("MiniMax plugin README is missing")
        elif kind == "minimax_submission":
            expected = {".minimax-plugin/plugin.json", "skills/voiceover-skill/SKILL.md", "assets/voiceover.png"}
            if not expected.issubset(contents):
                raise ValueError("MiniMax Marketplace required entries are missing")
            if "plugin.json" in contents or ".claude-plugin/plugin.json" in contents:
                raise ValueError("MiniMax Marketplace archive contains a foreign manifest")
            if "README.md" not in contents:
                raise ValueError("MiniMax Marketplace README is missing")
        elif kind == "claude":
            if ".claude-plugin/plugin.json" not in contents or "skills/voiceover-skill/SKILL.md" not in contents:
                raise ValueError("Claude Code plugin required entries are missing")
        elif "voiceover-skill/SKILL.md" not in contents:
            raise ValueError("standalone Skill ZIP is missing its folder entry point")


def _build_one(kind: str, output: Path) -> str:
    with tempfile.TemporaryDirectory(prefix=f"voiceover-{kind}-stage-") as temp:
        stage = Path(temp)
        if kind == "standalone":
            _build_standalone(stage)
        elif kind == "claude":
            _build_claude(stage)
        elif kind == "minimax_code":
            _build_minimax_code(stage)
        elif kind == "minimax_submission":
            _build_minimax_submission(stage)
        else:
            raise ValueError(f"unknown package kind: {kind}")
        _validate_stage(stage, kind)
        digest = _archive(stage, output)
    _verify_zip(output, kind)
    return digest


def build_packages(output_dir: Path, *, check_reproducible: bool = False) -> list[dict[str, str]]:
    output_dir = output_dir.expanduser().resolve()
    if output_dir == ROOT or output_dir.is_relative_to(ROOT):
        raise ValueError("output directory must be outside the source root")
    if not ICON_SOURCE.is_file() or ICON_SOURCE.is_symlink():
        raise ValueError(f"required generated MiniMax icon is missing: {ICON_SOURCE}")
    output_dir.mkdir(parents=True, exist_ok=True)
    definitions = (
        ("standalone", "voiceover-agent-skill.zip"),
        ("claude", "voiceover-claude-code-plugin.zip"),
        ("minimax_code", "voiceover-minimax-code-dual-plugin.zip"),
        ("minimax_submission", "voiceover-minimax-marketplace-plugin.zip"),
    )
    results: list[dict[str, str]] = []
    for kind, filename in definitions:
        output = output_dir / filename
        if output.is_symlink() or output.is_dir():
            raise ValueError(f"unsafe output path: {output}")
        digest = _build_one(kind, output)
        if check_reproducible:
            with tempfile.TemporaryDirectory(prefix=f"voiceover-{kind}-repro-") as temp:
                second = Path(temp) / filename
                second_digest = _build_one(kind, second)
                if digest != second_digest or output.read_bytes() != second.read_bytes():
                    raise ValueError(f"reproducibility check failed: {filename}")
        results.append({"kind": kind, "path": str(output), "sha256": digest,
                        "size_bytes": str(output.stat().st_size)})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT.parent / "voiceover_skill_distribution",
                        help="directory outside the project source root for generated ZIPs")
    parser.add_argument("--check-reproducible", action="store_true",
                        help="rebuild each ZIP and require byte-identical output")
    args = parser.parse_args()
    try:
        results = build_packages(args.output_dir, check_reproducible=args.check_reproducible)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))
    for row in results:
        print(f"{row['kind']}: {row['path']} ({row['size_bytes']} bytes) SHA-256 {row['sha256']}")
    print("All package ZIPs passed structural and CRC checks.")
    if args.check_reproducible:
        print("Reproducibility check: PASS (byte-identical builds)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
