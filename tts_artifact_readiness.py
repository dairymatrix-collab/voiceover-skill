"""Deterministic, non-installing artifact readiness checks for neural TTS engines.

Artifact presence is diagnostic evidence only. This module never imports an engine,
loads weights, downloads files, or verifies inference.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import deque
from cache_paths import hf_hub_cache_path
import errno
from fnmatch import fnmatchcase
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any


MAX_HASH_BYTES = 64 * 1024 * 1024
MAX_SCAN_ENTRIES = 100_000
MAX_SCAN_DEPTH = 32
_READ_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ArtifactSpec:
    engine_id: str
    artifact_id: str
    relative_candidates: tuple[str, ...]
    required: bool = True
    kind: str = "directory"
    required_file_groups: tuple[tuple[str, ...], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"engine_id": self.engine_id, "artifact_id": self.artifact_id,
                "relative_candidates": list(self.relative_candidates), "required": self.required,
                "kind": self.kind, "required_file_groups": [list(group) for group in self.required_file_groups]}


ENGINE_ARTIFACTS: dict[str, tuple[ArtifactSpec, ...]] = {
    "kokoro": (
        ArtifactSpec("kokoro", "kokoro_model", ("Kokoro-82M", "models/Kokoro-82M",
                                                   "models--hexgrad--Kokoro-82M"), True, "directory",
                     (("config.json",), ("kokoro-v1_0.pth",), ("voices/*.pt",))),
    ),
    "qwen3_tts": (
        ArtifactSpec("qwen3_tts", "qwen_model", ("Qwen3-TTS-12Hz-1.7B-CustomVoice",
                                                   "models/Qwen3-TTS-12Hz-1.7B-CustomVoice",
                                                   "models--Qwen--Qwen3-TTS-12Hz-1.7B-CustomVoice"),
                     True, "directory",
                     (("config.json",), ("model.safetensors", "pytorch_model.bin"),
                      ("tokenizer_config.json",), ("vocab.json",), ("merges.txt",),
                      ("preprocessor_config.json",), ("speech_tokenizer/config.json",),
                      ("speech_tokenizer/model.safetensors", "speech_tokenizer/pytorch_model.bin"),
                      ("speech_tokenizer/preprocessor_config.json",))),
    ),
    "chatterbox": (
        ArtifactSpec("chatterbox", "chatterbox_model", ("chatterbox", "models/chatterbox",
                                                           "ResembleAI/chatterbox",
                                                           "models--ResembleAI--chatterbox"),
                     True, "directory",
                     (("ve.pt",), ("s3gen.pt",), ("grapheme_mtl_merged_expanded_v1.json",),
                      ("t3_mtl23ls_v2.safetensors",))),
    ),
}

QWEN_VOICE_DESIGN_ARTIFACTS = (
    ArtifactSpec("qwen3_tts", "qwen_voice_design_model",
                 ("Qwen3-TTS-12Hz-1.7B-VoiceDesign",
                  "models/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
                  "models--Qwen--Qwen3-TTS-12Hz-1.7B-VoiceDesign"),
                 True, "directory",
                 (("config.json",), ("model.safetensors", "pytorch_model.bin"),
                  ("tokenizer_config.json",), ("vocab.json",), ("merges.txt",),
                  ("preprocessor_config.json",), ("speech_tokenizer/config.json",),
                  ("speech_tokenizer/model.safetensors", "speech_tokenizer/pytorch_model.bin"),
                  ("speech_tokenizer/preprocessor_config.json",))),
)

# Accept explicitly documented ecosystem spellings while always reporting the
# canonical project engine ID. Unknown strings are not guessed or fuzzy-matched.
ENGINE_ALIASES: dict[str, str] = {
    "kokoro": "kokoro",
    "kokoro_tts": "kokoro",
    "chatterbox": "chatterbox",
    "chatterbox_tts": "chatterbox",
    "qwen3_tts": "qwen3_tts",
    "qwen_tts": "qwen3_tts",
}


def normalize_engine_id(engine: str) -> str:
    if not isinstance(engine, str) or "\x00" in engine:
        raise ValueError("engine must be a supported engine ID")
    key = engine.strip().lower().replace("-", "_")
    try:
        return ENGINE_ALIASES[key]
    except KeyError as exc:
        raise ValueError(f"unknown engine: {engine}") from exc


def _safe_root(value: str | Path) -> Path:
    try:
        raw = os.fspath(value)
    except (TypeError, ValueError, OSError) as exc:
        raise ValueError("model root must be a filesystem path") from exc
    if not isinstance(raw, str) or "\x00" in raw:
        raise ValueError("model root must not contain NUL")
    try:
        return Path(raw).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("model root cannot be resolved") from exc


def resolve_model_root(explicit: str | Path | None = None) -> Path | None:
    if explicit is not None:
        return _safe_root(explicit)
    candidates: list[str | Path] = []
    for key in ("VOICEOVER_MODEL_ROOT", "TTS_MODEL_ROOT"):
        value = os.environ.get(key)
        if value:
            candidates.append(value)
    if candidates:
        return _safe_root(candidates[0])
    cache_root = hf_hub_cache_path()
    if any(os.environ.get(key) for key in ("HF_HUB_CACHE", "HF_HOME", "XDG_CACHE_HOME")):
        return _safe_root(cache_root)
    try:
        return _safe_root(cache_root) if cache_root.is_dir() else None
    except OSError:
        return None


def _open_relative(root: Path, parts: tuple[str, ...], *, directory: bool = False) -> int:
    """Open beneath root without following any path-component symlink where supported."""
    if not parts:
        if not directory:
            raise OSError(errno.EISDIR, "expected a file beneath model root")
        return os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))

    if os.name != "nt" and os.open in getattr(os, "supports_dir_fd", set()):
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        dir_flag = getattr(os, "O_DIRECTORY", 0)
        current = os.open(root, os.O_RDONLY | dir_flag)
        try:
            for part in parts[:-1]:
                following = os.open(part, os.O_RDONLY | dir_flag | nofollow, dir_fd=current)
                os.close(current)
                current = following
            flags = os.O_RDONLY | nofollow | (dir_flag if directory else 0)
            result = os.open(parts[-1], flags, dir_fd=current)
            os.close(current)
            return result
        except BaseException:
            try:
                os.close(current)
            except OSError:
                pass
            raise

    # Portable best-effort fallback: callers have already resolved and checked
    # containment; lstat rejects a final symlink before opening.
    path = root.joinpath(*parts)
    if path.is_symlink():
        raise OSError(errno.ELOOP, "symlink path component")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    if directory:
        flags |= getattr(os, "O_DIRECTORY", 0)
    return os.open(path, flags)


def _readable_regular_file(root: Path, resolved: Path) -> tuple[int, os.stat_result]:
    try:
        parts = resolved.relative_to(root).parts
    except ValueError as exc:
        raise OSError(errno.EPERM, "path escapes model root") from exc
    fd = _open_relative(root, parts)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError(errno.EINVAL, "artifact is not a regular file")
        if info.st_size:
            os.read(fd, 1)
            os.lseek(fd, 0, os.SEEK_SET)
        return fd, info
    except BaseException:
        os.close(fd)
        raise


def _unchanged(before: os.stat_result, after: os.stat_result, bytes_read: int) -> bool:
    return (
        before.st_dev == after.st_dev
        and before.st_ino == after.st_ino
        and before.st_size == after.st_size
        and getattr(before, "st_mtime_ns", int(before.st_mtime * 1_000_000_000))
        == getattr(after, "st_mtime_ns", int(after.st_mtime * 1_000_000_000))
        and getattr(before, "st_ctime_ns", int(before.st_ctime * 1_000_000_000))
        == getattr(after, "st_ctime_ns", int(after.st_ctime * 1_000_000_000))
        and bytes_read == after.st_size
    )


def _digest_open_file(fd: int, initial: os.stat_result) -> tuple[str | None, str, int]:
    """Hash a complete bounded file; never label a truncated prefix as SHA-256."""
    if initial.st_size > MAX_HASH_BYTES:
        return None, "SKIPPED_SIZE_LIMIT", 0
    digest = hashlib.sha256()
    total = 0
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        block = os.read(fd, min(_READ_BYTES, MAX_HASH_BYTES + 1 - total))
        if not block:
            break
        total += len(block)
        if total > MAX_HASH_BYTES:
            return None, "SKIPPED_SIZE_LIMIT", total
        digest.update(block)
    final = os.fstat(fd)
    if not _unchanged(initial, final, total):
        return None, "CHANGED_DURING_SCAN", total
    return digest.hexdigest(), "SHA256_COMPLETE", total


def _error_state(exc: OSError) -> str:
    if exc.errno in (errno.EACCES, errno.EPERM):
        return "UNREADABLE"
    if exc.errno == errno.ELOOP:
        return "PATH_UNSAFE"
    if exc.errno == errno.EINVAL:
        return "UNSUPPORTED_TYPE"
    if isinstance(exc, FileNotFoundError) or exc.errno == errno.ENOENT:
        return "MISSING"
    return "IO_ERROR"


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _matches_required_pattern(relative_path: str, pattern: str) -> bool:
    relative_path = relative_path.replace("\\", "/")
    pattern = pattern.replace("\\", "/")
    if "/" not in pattern:
        return fnmatchcase(relative_path.rsplit("/", 1)[-1], pattern)
    return (fnmatchcase(relative_path, pattern) or fnmatchcase(relative_path, "**/" + pattern)
            or relative_path.endswith("/" + pattern))


def _mark_file_groups(relative_path: str, groups: tuple[tuple[str, ...], ...], matched: list[bool],
                      matched_paths: list[str | None] | None = None) -> None:
    for index, alternatives in enumerate(groups):
        if not matched[index] and any(_matches_required_pattern(relative_path, item) for item in alternatives):
            matched[index] = True
            if matched_paths is not None:
                matched_paths[index] = relative_path


def _scan_directory_fallback(root: Path, directory: Path,
 required_file_groups: tuple[tuple[str, ...], ...] = ()) -> dict[str, Any]:
    """Portable path-based fallback where fd-based ``scandir`` is unavailable."""
    count = entries = symlink_entries_seen = 0
    unreadable = escaped = io_error = scan_limited = False
    matched_groups = [False] * len(required_file_groups)
    matched_paths: list[str | None] = [None] * len(required_file_groups)

    def onerror(exc: OSError) -> None:
        nonlocal unreadable, io_error
        if exc.errno in (errno.EACCES, errno.EPERM):
            unreadable = True
        else:
            io_error = True

    for current, dirs, files in os.walk(directory, topdown=True, followlinks=False, onerror=onerror):
        current_path = Path(current)
        try:
            depth = len(current_path.relative_to(directory).parts)
        except ValueError:
            escaped = True
            break
        dirs.sort()
        files.sort()
        names_count = len(dirs) + len(files)
        entries += names_count
        if entries > MAX_SCAN_ENTRIES:
            scan_limited = True
            break
        keep_dirs: list[str] = []
        for name in dirs:
            candidate = current_path / name
            if candidate.is_symlink():
                symlink_entries_seen += 1
                try:
                    if not _within(candidate.resolve(strict=True), root):
                        escaped = True
                except (OSError, RuntimeError):
                    io_error = True
                continue
            if depth + 1 > MAX_SCAN_DEPTH:
                scan_limited = True
                continue
            keep_dirs.append(name)
        dirs[:] = keep_dirs
        for name in files:
            candidate = current_path / name
            is_symlink = candidate.is_symlink()
            if is_symlink:
                symlink_entries_seen += 1
            try:
                resolved = candidate.resolve(strict=True)
                if not _within(resolved, root):
                    escaped = True
                    continue
                fd, info = _readable_regular_file(root, resolved)
                try:
                    if info.st_size > 0:
                        count += 1
                        relative_file = (current_path.relative_to(directory) / name).as_posix()
                        _mark_file_groups(relative_file, required_file_groups, matched_groups, matched_paths)
                finally:
                    os.close(fd)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EPERM):
                    unreadable = True
                else:
                    io_error = True
            except RuntimeError:
                io_error = True
        if scan_limited:
            break

    if escaped:
        state = "PATH_UNSAFE"
    elif unreadable:
        state = "UNREADABLE"
    elif scan_limited:
        state = "SCAN_LIMIT_EXCEEDED"
    elif io_error:
        state = "IO_ERROR"
    elif count == 0:
        state = "EMPTY"
    else:
        state = "PRESENT"
    if state == "PRESENT" and not all(matched_groups):
        state = "INCOMPLETE"
    return {"state": state, "regular_file_count": count, "entries_scanned": entries,
            "symlink_entries_seen": symlink_entries_seen,
            "satisfied_file_groups": matched_groups}


def _scan_directory(root: Path, directory: Path,
                    required_file_groups: tuple[tuple[str, ...], ...] = ()) -> dict[str, Any]:
    """Count readable, non-empty regular files using descriptor-anchored traversal."""
    if os.scandir not in getattr(os, "supports_fd", set()):
        return _scan_directory_fallback(root, directory, required_file_groups)
    try:
        relative = directory.relative_to(root).parts
        first_fd = _open_relative(root, relative, directory=True)
    except OSError as exc:
        return {"state": _error_state(exc), "regular_file_count": 0, "entries_scanned": 0,
                "symlink_entries_seen": 0, "error_type": type(exc).__name__}

    pending = deque([(first_fd, relative, 0)])
    count = entries = symlink_entries_seen = 0
    unreadable = False
    escaped = False
    io_error = False
    scan_limited = False
    matched_groups = [False] * len(required_file_groups)
    while pending:
        dir_fd, parts, depth = pending.popleft()
        try:
            if depth > MAX_SCAN_DEPTH:
                scan_limited = True
                continue
            try:
                with os.scandir(dir_fd) as iterator:
                    names = sorted(entry.name for entry in iterator)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EPERM):
                    unreadable = True
                else:
                    io_error = True
                continue
            entries += len(names)
            if entries > MAX_SCAN_ENTRIES:
                scan_limited = True
                break
            for name in names:
                try:
                    info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
                except OSError as exc:
                    if exc.errno in (errno.EACCES, errno.EPERM):
                        unreadable = True
                    else:
                        io_error = True
                    continue
                mode = info.st_mode
                child_parts = (*parts, name)
                if stat.S_ISLNK(mode):
                    symlink_entries_seen += 1
                    try:
                        resolved = root.joinpath(*child_parts).resolve(strict=True)
                        if not _within(resolved, root):
                            escaped = True
                            continue
                        if not stat.S_ISREG(resolved.stat().st_mode):
                            continue
                        fd, actual = _readable_regular_file(root, resolved)
                        try:
                            if actual.st_size > 0:
                                count += 1
                                relative_file = Path(*child_parts[len(relative):]).as_posix()
                                _mark_file_groups(relative_file, required_file_groups, matched_groups)
                        finally:
                            os.close(fd)
                    except (OSError, RuntimeError):
                        io_error = True
                    continue
                if stat.S_ISDIR(mode):
                    if depth + 1 > MAX_SCAN_DEPTH:
                        scan_limited = True
                        continue
                    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
                    try:
                        child_fd = os.open(name, flags, dir_fd=dir_fd)
                    except OSError as exc:
                        if exc.errno in (errno.EACCES, errno.EPERM):
                            unreadable = True
                        elif exc.errno == errno.ELOOP:
                            escaped = True
                        else:
                            io_error = True
                        continue
                    pending.append((child_fd, child_parts, depth + 1))
                    continue
                if not stat.S_ISREG(mode):
                    continue
                try:
                    fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dir_fd)
                    try:
                        actual = os.fstat(fd)
                        if not stat.S_ISREG(actual.st_mode):
                            io_error = True
                        elif actual.st_size > 0:
                            os.read(fd, 1)
                            count += 1
                            relative_file = Path(*child_parts[len(relative):]).as_posix()
                            _mark_file_groups(relative_file, required_file_groups, matched_groups)
                    finally:
                        os.close(fd)
                except OSError as exc:
                    if exc.errno in (errno.EACCES, errno.EPERM):
                        unreadable = True
                    elif exc.errno == errno.ELOOP:
                        escaped = True
                    else:
                        io_error = True
        finally:
            os.close(dir_fd)
    for fd, _, _ in pending:
        try:
            os.close(fd)
        except OSError:
            pass

    if escaped:
        state = "PATH_UNSAFE"
    elif unreadable:
        state = "UNREADABLE"
    elif scan_limited:
        state = "SCAN_LIMIT_EXCEEDED"
    elif io_error:
        state = "IO_ERROR"
    elif count == 0:
        state = "EMPTY"
    else:
        state = "PRESENT"
    if state == "PRESENT" and not all(matched_groups):
        state = "INCOMPLETE"
    return {"state": state, "regular_file_count": count, "entries_scanned": entries,
            "symlink_entries_seen": symlink_entries_seen,
            "satisfied_file_groups": matched_groups}


def _find_required_matches(root: Path, directory: Path,
                           groups: tuple[tuple[str, ...], ...]) -> tuple[list[str | None], str | None]:
    """Find the first bounded, readable match for each group inside one checked directory."""
    matched = [False] * len(groups)
    paths: list[str | None] = [None] * len(groups)
    entries = 0
    issue: str | None = None

    def onerror(exc: OSError) -> None:
        nonlocal issue
        issue = _error_state(exc)

    for current, dirs, files in os.walk(directory, topdown=True, followlinks=False, onerror=onerror):
        current_path = Path(current)
        try:
            depth = len(current_path.relative_to(directory).parts)
        except ValueError:
            return paths, "PATH_UNSAFE"
        dirs.sort()
        files.sort()
        entries += len(dirs) + len(files)
        if entries > MAX_SCAN_ENTRIES:
            return paths, "SCAN_LIMIT_EXCEEDED"
        keep: list[str] = []
        for name in dirs:
            child = current_path / name
            if child.is_symlink():
                try:
                    if not _within(child.resolve(strict=True), root):
                        return paths, "PATH_UNSAFE"
                except (OSError, RuntimeError) as exc:
                    return paths, _error_state(exc) if isinstance(exc, OSError) else "IO_ERROR"
                continue
            if depth + 1 > MAX_SCAN_DEPTH:
                return paths, "SCAN_LIMIT_EXCEEDED"
            keep.append(name)
        dirs[:] = keep
        for name in files:
            candidate = current_path / name
            try:
                resolved = candidate.resolve(strict=True)
                if not _within(resolved, root):
                    return paths, "PATH_UNSAFE"
                if not stat.S_ISREG(resolved.stat().st_mode):
                    continue
                fd, info = _readable_regular_file(root, resolved)
                try:
                    if info.st_size > 0:
                        relative = (current_path.relative_to(directory) / name).as_posix()
                        _mark_file_groups(relative, groups, matched, paths)
                finally:
                    os.close(fd)
            except OSError as exc:
                return paths, _error_state(exc)
            except RuntimeError:
                return paths, "IO_ERROR"
        if all(matched):
            break
    if issue:
        return paths, issue
    return paths, None


def _hash_required_matches(root: Path, directory: Path,
                           matches: list[str | None]) -> tuple[list[dict[str, Any]], str | None]:
    records: list[dict[str, Any]] = []
    failure: str | None = None
    for index, relative in enumerate(matches):
        if relative is None:
            continue
        record: dict[str, Any] = {"group_index": index, "relative_path": relative,
                                  "hash_status": "IO_ERROR", "bytes_hashed": 0}
        fd: int | None = None
        try:
            resolved = (directory / relative).resolve(strict=True)
            if not _within(resolved, root):
                record["hash_status"] = "IO_ERROR"
                failure = failure or "PATH_UNSAFE"
            else:
                fd, initial = _readable_regular_file(root, resolved)
                record["size_bytes"] = initial.st_size
                if initial.st_size == 0:
                    record["hash_status"] = "IO_ERROR"
                    failure = failure or "CHANGED_DURING_SCAN"
                elif initial.st_size > MAX_HASH_BYTES:
                    record["hash_status"] = "SKIPPED_SIZE_LIMIT"
                else:
                    digest, hash_status, hashed_bytes = _digest_open_file(fd, initial)
                    record.update(hash_status=hash_status, bytes_hashed=hashed_bytes)
                    if digest:
                        record["sha256"] = digest
                    elif hash_status == "CHANGED_DURING_SCAN":
                        failure = failure or "CHANGED_DURING_SCAN"
                    elif hash_status == "UNREADABLE":
                        failure = failure or "UNREADABLE"
                    elif hash_status == "IO_ERROR":
                        failure = failure or "IO_ERROR"
        except OSError as exc:
            record["hash_status"] = "UNREADABLE" if _error_state(exc) == "UNREADABLE" else "IO_ERROR"
            record["error_type"] = type(exc).__name__
            failure = failure or _error_state(exc)
        except RuntimeError:
            record["hash_status"] = "IO_ERROR"
            failure = failure or "IO_ERROR"
        finally:
            if fd is not None:
                os.close(fd)
        records.append(record)
    return records, failure


def _inspect_candidate(root: Path, spec: ArtifactSpec, rel: str, hash_files: bool) -> dict[str, Any]:
    candidate = root / rel
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        return {"state": "MISSING", "present": False, "matched_path": None, "relative_path": rel,
                "match_count": 0, "hash_status": "NOT_APPLICABLE"}
    except (OSError, RuntimeError) as exc:
        state = _error_state(exc) if isinstance(exc, OSError) else "IO_ERROR"
        return {"state": state, "present": False, "matched_path": None, "relative_path": rel,
                "match_count": 0, "hash_status": "NOT_APPLICABLE",
                **({"error_type": type(exc).__name__} if isinstance(exc, OSError) else {})}
    if not _within(resolved, root):
        return {"state": "PATH_UNSAFE", "present": False, "matched_path": None, "relative_path": rel,
                "match_count": 0, "hash_status": "NOT_APPLICABLE"}

    try:
        initial = resolved.stat()
    except OSError as exc:
        state = _error_state(exc)
        return {"state": state, "present": False, "matched_path": None, "relative_path": rel,
                "match_count": 0, "hash_status": "NOT_APPLICABLE", "error_type": type(exc).__name__}

    if spec.kind == "file":
        if not stat.S_ISREG(initial.st_mode):
            return {"state": "UNSUPPORTED_TYPE", "present": False, "matched_path": None,
                    "relative_path": rel, "match_count": 0, "hash_status": "NOT_APPLICABLE"}
        fd = None
        try:
            fd, initial = _readable_regular_file(root, resolved)
            if initial.st_size == 0:
                return {"state": "EMPTY", "present": False, "matched_path": None, "relative_path": rel,
                        "match_count": 0, "size_bytes": 0, "hash_status": "NOT_APPLICABLE"}
            record: dict[str, Any] = {"state": "PRESENT", "present": True, "matched_path": str(resolved),
                                      "relative_path": rel, "match_count": 1, "size_bytes": initial.st_size,
                                      "hash_status": "NOT_REQUESTED"}
            if hash_files:
                digest, hash_status, hashed_bytes = _digest_open_file(fd, initial)
                record.update(hash_status=hash_status, bytes_hashed=hashed_bytes)
                if digest:
                    record["sha256"] = digest
                elif hash_status == "CHANGED_DURING_SCAN":
                    record.update(state="CHANGED_DURING_SCAN", present=False, matched_path=None, match_count=0)
            return record
        except OSError as exc:
            state = _error_state(exc)
            return {"state": state, "present": False, "matched_path": None, "relative_path": rel,
                    "match_count": 0, "hash_status": "UNREADABLE" if state == "UNREADABLE" else "IO_ERROR",
                    "error_type": type(exc).__name__}
        finally:
            if fd is not None:
                os.close(fd)

    if spec.kind == "directory":
        if not stat.S_ISDIR(initial.st_mode):
            return {"state": "UNSUPPORTED_TYPE", "present": False, "matched_path": None,
                    "relative_path": rel, "match_count": 0, "hash_status": "NOT_APPLICABLE"}
        scan = _scan_directory(root, resolved, spec.required_file_groups)
        if hash_files and scan["state"] in {"PRESENT", "INCOMPLETE"}:
            matches, match_issue = _find_required_matches(root, resolved, spec.required_file_groups)
            scan["required_file_matches"] = matches
            hashes, hash_issue = _hash_required_matches(root, resolved, matches)
            scan["required_file_hashes"] = hashes
            issue = match_issue or hash_issue
            if issue:
                scan["state"] = issue
            elif scan["state"] == "PRESENT" and any(path is None for path in matches):
                scan["state"] = "CHANGED_DURING_SCAN"
        present = scan["state"] == "PRESENT"
        return {**scan, "present": present, "matched_path": str(resolved) if present else None,
                "relative_path": rel, "match_count": 1 if present else 0,
                "hash_status": "NOT_APPLICABLE"}
    return {"state": "UNSUPPORTED_TYPE", "present": False, "matched_path": None,
            "relative_path": rel, "match_count": 0, "hash_status": "NOT_APPLICABLE"}


def _base_artifact_record(spec: ArtifactSpec) -> dict[str, Any]:
    return {"engine_id": spec.engine_id, "artifact_id": spec.artifact_id,
            "relative_candidates": list(spec.relative_candidates), "required": spec.required,
            "required_file_groups": [list(group) for group in spec.required_file_groups],
            "satisfied_file_groups": [False] * len(spec.required_file_groups),
            "kind": spec.kind, "present": False, "matched_path": None, "match_count": 0,
            "state": "MISSING", "hash_status": "NOT_APPLICABLE", "candidate_issues": []}


def _select_artifact_specs(canonical: str, model_variant: str | None) -> tuple[ArtifactSpec, ...]:
    if model_variant is not None and (not isinstance(model_variant, str) or "\x00" in model_variant):
        raise ValueError("model_variant must be a supported string")
    variant = model_variant.strip().lower().replace("-", "_") if model_variant else None
    if canonical == "qwen3_tts" and variant == "voice_design":
        return QWEN_VOICE_DESIGN_ARTIFACTS
    if canonical == "qwen3_tts" and variant not in (None, "preset", "custom_voice"):
        raise ValueError(f"unsupported qwen3_tts model variant: {model_variant}")
    if canonical == "kokoro" and variant not in (None, "preset"):
        raise ValueError(f"unsupported kokoro model variant: {model_variant}")
    if canonical == "chatterbox" and variant not in (None, "reference_clone"):
        raise ValueError(f"unsupported chatterbox model variant: {model_variant}")
    return ENGINE_ARTIFACTS[canonical]


def _inspect_v2(engine: str, *, model_root: str | Path | None, hash_files: bool,
                model_variant: str | None = None) -> dict[str, Any]:
    canonical = normalize_engine_id(engine)
    if not isinstance(hash_files, bool):
        raise ValueError("hash_files must be boolean")
    root = resolve_model_root(model_root)
    specs = _select_artifact_specs(canonical, model_variant)
    records: list[dict[str, Any]] = []
    if root is None or not root.is_dir():
        state = "MODEL_ROOT_NOT_CONFIGURED"
        for spec in specs:
            record = _base_artifact_record(spec)
            record["state"] = state
            records.append(record)
        status = state
        resolved_root: str | None = None if root is None else str(root)
    else:
        for spec in specs:
            attempts = [_inspect_candidate(root, spec, rel, hash_files) for rel in spec.relative_candidates]
            valid = [item for item in attempts if item["present"]]
            chosen = valid[0] if valid else None
            if chosen is None:
                states = [item["state"] for item in attempts]
                priority = ("PATH_UNSAFE", "UNREADABLE", "SCAN_LIMIT_EXCEEDED", "CHANGED_DURING_SCAN",
                            "IO_ERROR", "INCOMPLETE", "EMPTY", "UNSUPPORTED_TYPE", "MISSING")
                state = next((candidate_state for candidate_state in priority if candidate_state in states), "MISSING")
                selected = next((item for item in attempts if item["state"] == state), attempts[0] if attempts else {})
                chosen = {**selected, "state": state, "present": False, "matched_path": None, "match_count": 0}
            record = {**_base_artifact_record(spec), **chosen}
            record["match_count"] = len({item.get("matched_path") for item in valid})
            record["candidate_issues"] = [item["state"] for item in attempts if item["state"] not in {"PRESENT", "MISSING"}]
            records.append(record)
        resolved_root = str(root)
        missing_required = [record["artifact_id"] for record in records
                            if record["required"] and not record["present"]]
        states = {record["state"] for record in records if record["required"] and not record["present"]}
        if not missing_required:
            status = "ARTIFACTS_READY"
        elif "PATH_UNSAFE" in states:
            status = "ARTIFACT_PATH_UNSAFE"
        elif "UNREADABLE" in states:
            status = "ARTIFACTS_UNREADABLE"
        elif "SCAN_LIMIT_EXCEEDED" in states:
            status = "ARTIFACT_SCAN_INCOMPLETE"
        elif "INCOMPLETE" in states:
            status = "ARTIFACTS_INCOMPLETE"
        elif "IO_ERROR" in states or "CHANGED_DURING_SCAN" in states:
            status = "ARTIFACT_INSPECTION_ERROR"
        else:
            status = "ARTIFACTS_MISSING"
    missing_required = [record["artifact_id"] for record in records
                        if record["required"] and not record["present"]]
    missing_optional = [record["artifact_id"] for record in records
                        if not record["required"] and not record["present"]]
    return {"schema_version": 2, "diagnostic_only": True, "engine": canonical,
            "status": status, "model_root": resolved_root, "artifacts": records,
            "missing_required": missing_required, "missing_optional": missing_optional,
            "artifact_ready": not missing_required, "inference_verified": False,
            "installation_performed": False, "model_downloaded": False,
            "hash_limit_bytes": MAX_HASH_BYTES if hash_files else None,
            "scan_entry_limit": MAX_SCAN_ENTRIES, "scan_depth_limit": MAX_SCAN_DEPTH}


def inspect_engine_artifacts_v2(engine: str, *, model_root: str | Path | None = None,
                                hash_files: bool = False,
                                model_variant: str | None = None) -> dict[str, Any]:
    """Return the detailed, version-2 artifact-only report."""
    return _inspect_v2(engine, model_root=model_root, hash_files=hash_files,
                       model_variant=model_variant)


def inspect_all_v2(model_root: str | Path | None = None, *, hash_files: bool = False) -> dict[str, Any]:
    reports = [inspect_engine_artifacts_v2(engine, model_root=model_root, hash_files=hash_files)
               for engine in sorted(ENGINE_ARTIFACTS)]
    return {"schema_version": 2, "diagnostic_only": True, "inference_verified": False,
            "installation_performed": False, "model_downloaded": False, "engines": reports,
            "ready_engine_count": sum(bool(report["artifact_ready"]) for report in reports),
            "hash_limit_bytes": MAX_HASH_BYTES if hash_files else None,
            "scan_entry_limit": MAX_SCAN_ENTRIES, "scan_depth_limit": MAX_SCAN_DEPTH}


def _v1_report(report: dict[str, Any]) -> dict[str, Any]:
    artifacts = []
    for source in report["artifacts"]:
        item = {key: source[key] for key in ("engine_id", "artifact_id", "relative_candidates", "required", "kind",
                                               "present", "matched_path", "match_count")}
        if source["present"] and source["kind"] == "file":
            item["size_bytes"] = source.get("size_bytes", 0)
            if source.get("sha256"):
                # v1 retains its historical field name; the value is now a complete
                # digest only, never a prefix digest disguised as whole-file SHA-256.
                item["sha256_prefix_safe"] = source["sha256"]
        if source["present"] and source["kind"] == "directory":
            item["regular_file_count_estimate"] = source.get("regular_file_count", 0)
        artifacts.append(item)
    return {"schema_version": 1, "diagnostic_only": True, "engine": report["engine"],
            "status": ("MODEL_ROOT_NOT_CONFIGURED" if report["status"] == "MODEL_ROOT_NOT_CONFIGURED"
                       else "ARTIFACTS_READY" if report["artifact_ready"] else "ARTIFACTS_MISSING"),
            "model_root": report["model_root"], "artifacts": artifacts,
            "missing_required": report["missing_required"], "artifact_ready": report["artifact_ready"],
            "inference_verified": False, "installation_performed": False, "model_downloaded": False}


def inspect_engine_artifacts(engine: str, *, model_root: str | Path | None = None,
                             hash_files: bool = False) -> dict[str, Any]:
    """Backward-compatible version-1 projection; new consumers should use v2."""
    return _v1_report(_inspect_v2(engine, model_root=model_root, hash_files=hash_files))


def inspect_all(model_root: str | Path | None = None, *, hash_files: bool = False) -> dict[str, Any]:
    reports = [inspect_engine_artifacts(engine, model_root=model_root, hash_files=hash_files)
               for engine in sorted(ENGINE_ARTIFACTS)]
    return {"schema_version": 1, "diagnostic_only": True, "inference_verified": False,
            "installation_performed": False, "model_downloaded": False, "engines": reports,
            "ready_engine_count": sum(bool(report["artifact_ready"]) for report in reports)}


def write_report_atomic(path: str | Path, report: dict[str, Any], *,
                        protected_root: str | Path | None = None) -> None:
    """Atomically write a privacy-safe JSON report outside the inspected model root."""
    try:
        raw = os.fspath(path)
    except (TypeError, ValueError, OSError) as exc:
        raise ValueError("report path must be a filesystem path") from exc
    if not isinstance(raw, str) or "\x00" in raw:
        raise ValueError("report path must not contain NUL")
    target = Path(raw).expanduser().absolute()
    if target.is_symlink():
        raise ValueError("REPORT_DESTINATION_SYMLINK")
    parent = target.parent.resolve(strict=False)
    normalized_target = parent / target.name
    if protected_root is not None:
        root = _safe_root(protected_root)
        if normalized_target == root or _within(normalized_target, root):
            raise ValueError("REPORT_DESTINATION_INSIDE_MODEL_ROOT")
    if target.exists() and target.is_dir():
        raise ValueError("REPORT_DESTINATION_IS_DIRECTORY")
    parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, normalized_target)
        try:
            dir_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            # Atomic replacement remains valid on platforms/filesystems that do
            # not support directory fsync; durability is then filesystem-specific.
            pass
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
