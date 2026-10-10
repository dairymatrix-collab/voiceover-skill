#!/usr/bin/env python3
"""Create and verify a deterministic ZIP distribution for this contract harness.

Uses only Python's standard library. The SHA256SUMS manifest covers every
included regular file except itself; the ZIP container is not self-hashed.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile
import zipfile

FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_ARCHIVE_MEMBERS = 1000
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MANIFEST_NAME = "SHA256SUMS"
EXCLUDED_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".tmp", ".swp", ".bak"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_excluded(rel: Path, output_path: Path | None, root: Path) -> bool:
    if any(part in EXCLUDED_DIRS for part in rel.parts):
        return True
    if rel.name == MANIFEST_NAME or rel.name.startswith(".~") or rel.name.startswith(".#"):
        return True
    if rel.suffix.lower() in EXCLUDED_SUFFIXES or rel.name.endswith("~"):
        return True
    candidate = (root / rel).resolve()
    if output_path is not None and candidate == output_path.resolve():
        return True
    return False


def collect_files(root: Path, output_path: Path | None = None) -> list[Path]:
    files = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root)
        if is_excluded(rel, output_path, root):
            continue
        files.append(path)
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def manifest_bytes(root: Path, files: list[Path]) -> bytes:
    lines = [f"{sha256_file(path)}  {path.relative_to(root).as_posix()}" for path in files]
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_manifest(root: Path) -> None:
    files = collect_files(root)
    (root / MANIFEST_NAME).write_bytes(manifest_bytes(root, files))


def verify_manifest(root: Path) -> list[str]:
    manifest = root / MANIFEST_NAME
    if not manifest.is_file():
        return ["SHA256SUMS is missing"]
    errors: list[str] = []
    seen: set[str] = set()
    for number, raw in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        if len(raw) < 68 or raw[64:66] != "  ":
            errors.append(f"SHA256SUMS:{number}: malformed entry")
            continue
        expected, name = raw[:64], raw[66:]
        if not SHA256_RE.fullmatch(expected):
            errors.append(f"SHA256SUMS:{number}: malformed SHA-256 digest")
            continue
        rel = PurePosixPath(name)
        normalized = rel.as_posix()
        if (not name or name in {".", ".."} or rel.is_absolute() or
                any(part in {"", ".", ".."} for part in rel.parts) or
                "\\" in name or name.startswith("/") or
                normalized != name or name.casefold() in {item.casefold() for item in seen}):
            errors.append(f"SHA256SUMS:{number}: unsafe or duplicate path {name!r}")
            continue
        seen.add(name)
        path = root.joinpath(*rel.parts)
        parent_chain = [root.joinpath(*rel.parts[:index]) for index in range(1, len(rel.parts))]
        if (any(part.is_symlink() for part in parent_chain) or
                not path.is_file() or path.is_symlink() or
                not path.resolve().is_relative_to(root.resolve())):
            errors.append(f"{name}: missing, unsafe, or not a regular file")
        elif sha256_file(path) != expected:
            errors.append(f"{name}: SHA-256 mismatch")
    actual = {p.relative_to(root).as_posix() for p in collect_files(root)}
    # collect_files excludes the manifest; all other files should be represented.
    for missing in sorted(actual - seen):
        errors.append(f"{missing}: not listed in SHA256SUMS")
    for extra in sorted(seen - actual):
        errors.append(f"{extra}: manifest entry is not an eligible package file")
    return errors


def build_archive(root: Path, output: Path) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    files = collect_files(root, output)
    manifest = root / MANIFEST_NAME
    if not manifest.is_file():
        raise RuntimeError("SHA256SUMS was not generated")
    files = sorted([*files, manifest], key=lambda p: p.relative_to(root).as_posix())
    # A unique sibling temp file avoids clobbering another build's staging file.
    fd, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".building", dir=output.parent)
    os.close(fd)
    temp_output = Path(temp_name)
    try:
        with zipfile.ZipFile(temp_output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, strict_timestamps=True) as archive:
            for path in files:
                rel = path.relative_to(root).as_posix()
                info = zipfile.ZipInfo(rel, date_time=FIXED_ZIP_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                mode = stat.S_IMODE(path.stat().st_mode)
                info.external_attr = (stat.S_IFREG | mode) << 16
                info.flag_bits |= 0x800
                archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        with zipfile.ZipFile(temp_output, "r") as archive:
            bad = archive.testzip()
            if bad:
                raise RuntimeError(f"ZIP CRC verification failed for {bad}")
        os.replace(temp_output, output)
    finally:
        if temp_output.exists():
            temp_output.unlink()
    return sha256_file(output)


def verify_archive(archive_path: Path) -> None:
    """Preflight ZIP metadata and contents before extracting into a private temp dir."""
    with zipfile.ZipFile(archive_path, "r") as archive:
        infos = archive.infolist()
        if len(infos) > MAX_ARCHIVE_MEMBERS:
            raise RuntimeError(f"ZIP has too many members: {len(infos)}")
        if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_BYTES:
            raise RuntimeError("ZIP uncompressed size exceeds safety limit")
        names: set[str] = set()
        folded_names: set[str] = set()
        for info in infos:
            name = info.filename
            rel = PurePosixPath(name)
            if (not name or rel.is_absolute() or ".." in rel.parts or "\\" in name or
                    any(part in {"", "."} for part in rel.parts) or rel.as_posix() != name or
                    name.startswith("/") or name.endswith("/")):
                raise RuntimeError(f"Unsafe ZIP member path: {name!r}")
            if name in names or name.casefold() in folded_names:
                raise RuntimeError(f"ZIP contains duplicate or case-colliding paths: {name}")
            names.add(name)
            folded_names.add(name.casefold())
            if any(part in EXCLUDED_DIRS for part in rel.parts) or rel.suffix.lower() in EXCLUDED_SUFFIXES:
                raise RuntimeError(f"Excluded cache/temp artifact in ZIP: {name}")
            if info.flag_bits & 0x1:
                raise RuntimeError(f"Encrypted ZIP member is not supported: {name}")
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise RuntimeError(f"Unsupported ZIP compression method for {name}")
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            file_type = stat.S_IFMT(unix_mode)
            if file_type not in {0, stat.S_IFREG}:
                raise RuntimeError(f"ZIP member is not a regular file: {name}")
            if info.file_size < 0 or info.compress_size < 0:
                raise RuntimeError(f"Invalid ZIP size metadata for {name}")
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC verification failed for {bad}")
        if MANIFEST_NAME not in names:
            raise RuntimeError("ZIP is missing SHA256SUMS")
        with tempfile.TemporaryDirectory(prefix="voiceover-package-verify-") as tmp:
            archive.extractall(tmp)
            errors = verify_manifest(Path(tmp))
            if errors:
                raise RuntimeError("Extracted manifest verification failed:\n" + "\n".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="package source root (default: parent of scripts/)")
    parser.add_argument("--output", type=Path, default=None, help="output ZIP path (default: sibling voiceover_contract_harness.zip)")
    parser.add_argument("--check-reproducible", action="store_true", help="build two temporary archives and require identical SHA-256 hashes")
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f"source root is not a directory: {root}")
    output = (args.output or root.parent / f"{root.name}.zip").resolve()
    if output == root or root in output.parents:
        parser.error("output ZIP must be outside the package source root")
    if output.exists() and output.is_dir():
        parser.error(f"output path is a directory: {output}")
    if output.parent.exists() and not output.parent.is_dir():
        parser.error(f"output parent is not a directory: {output.parent}")
    if not os.access(output.parent if output.parent.exists() else output.parent.parent, os.W_OK):
        parser.error(f"output location is not writable: {output.parent}")

    write_manifest(root)
    errors = verify_manifest(root)
    if errors:
        print("Manifest verification failed:", *errors, sep="\n- ", file=sys.stderr)
        return 2

    digest = build_archive(root, output)
    verify_archive(output)
    print(f"Archive: {output}")
    print(f"SHA-256: {digest}")
    print(f"Manifest entries: {len((root / MANIFEST_NAME).read_text(encoding='utf-8').splitlines())}")
    print("Archive integrity and extracted manifest: PASS")

    if args.check_reproducible:
        with tempfile.TemporaryDirectory(prefix="voiceover-repro-") as tmp:
            first = Path(tmp) / "first.zip"
            second = Path(tmp) / "second.zip"
            first_hash = build_archive(root, first)
            second_hash = build_archive(root, second)
            verify_archive(first)
            verify_archive(second)
            print(f"Reproducibility build 1: {first_hash}")
            print(f"Reproducibility build 2: {second_hash}")
            if first_hash != second_hash or first.read_bytes() != second.read_bytes():
                print("Reproducibility check: FAIL", file=sys.stderr)
                return 3
            print("Reproducibility check: PASS (byte-identical archives)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
