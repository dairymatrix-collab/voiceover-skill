"""Portable, atomic and path-contained voice-profile storage."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time
from typing import Any, Iterator, Mapping
import wave

from voice_controls import validate_controls, validate_voice_mode

PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
VOICE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
LANGUAGE_RE = re.compile(r"^[A-Za-z0-9_-]{2,32}$")
MAX_PROFILE_BYTES = 256 * 1024
MAX_REFERENCE_BYTES = 50 * 1024 * 1024
MAX_REFERENCE_SECONDS = 30.0


class ProfileStoreError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        self.code, self.detail = code, detail
        super().__init__(code if not detail else f"{code}:{detail}")


def default_store_dir() -> Path:
    """Return a platform-appropriate user data directory without creating it."""
    explicit = os.environ.get("VOICEOVER_PROFILE_DIR")
    if explicit:
        return Path(explicit).expanduser()
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "voiceover-skill"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser() / "voiceover-skill"
    return Path.home() / ".local" / "share" / "voiceover-skill"


def _store_root(store_dir: str | Path) -> Path:
    try:
        requested = Path(store_dir).expanduser()
        if requested.is_symlink():
            raise ProfileStoreError("PROFILE_STORE_SYMLINK")
        root = requested.resolve(strict=False)
    except ProfileStoreError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise ProfileStoreError("PROFILE_STORE_PATH_INVALID") from exc
    if root == Path(root.anchor) or root == Path.home().resolve():
        raise ProfileStoreError("PROFILE_STORE_PATH_UNSAFE")
    return root


def _profile_path(root: Path, profile_id: str) -> Path:
    if not isinstance(profile_id, str) or not PROFILE_ID_RE.fullmatch(profile_id):
        raise ProfileStoreError("PROFILE_ID_INVALID")
    profiles = root / "profiles"
    target = profiles / f"{profile_id}.json"
    if profiles.is_symlink() or target.is_symlink():
        raise ProfileStoreError("PROFILE_PATH_SYMLINK")
    if not target.resolve(strict=False).is_relative_to(root):
        raise ProfileStoreError("PROFILE_PATH_OUTSIDE_STORE")
    return target


def _asset_path(root: Path, relative: str, profile_id: str) -> Path:
    expected = f"assets/{profile_id}/reference.wav"
    if relative != expected:
        raise ProfileStoreError("PROFILE_REFERENCE_PATH_INVALID")
    assets = root / "assets"
    profile_assets = assets / profile_id
    target = profile_assets / "reference.wav"
    if assets.is_symlink() or profile_assets.is_symlink() or target.is_symlink():
        raise ProfileStoreError("PROFILE_REFERENCE_SYMLINK")
    if not target.resolve(strict=False).is_relative_to(root):
        raise ProfileStoreError("PROFILE_REFERENCE_PATH_OUTSIDE_STORE")
    return target


@contextmanager
def _store_lock(root: Path, timeout_seconds: float = 10.0) -> Iterator[None]:
    """Cross-platform advisory lock for profile create/update/delete operations."""
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 0.1 <= timeout_seconds <= 120:
        raise ProfileStoreError("PROFILE_LOCK_TIMEOUT_INVALID")
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".profiles.lock"
    if lock_path.is_symlink():
        raise ProfileStoreError("PROFILE_LOCK_SYMLINK")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise ProfileStoreError("PROFILE_LOCK_OPEN_FAILED") from exc
    locked = False
    deadline = time.monotonic() + float(timeout_seconds)
    try:
        while not locked:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    if os.fstat(fd).st_size == 0:
                        os.write(fd, b"\0")
                        os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise ProfileStoreError("PROFILE_STORE_BUSY")
                time.sleep(0.05)
        yield
    finally:
        if locked:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


def _atomic_write(target: Path, payload: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.parent.is_symlink() or target.is_symlink():
        raise ProfileStoreError("PROFILE_PATH_SYMLINK")
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        try:
            dir_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _strict_json_loads(raw: bytes) -> Any:
    def pairs_no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ProfileStoreError("PROFILE_JSON_DUPLICATE_KEY")
            result[key] = value
        return result

    def reject_constant(_value):
        raise ProfileStoreError("PROFILE_JSON_NONFINITE_NUMBER")

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs_no_duplicates, parse_constant=reject_constant)
    except ProfileStoreError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileStoreError("PROFILE_JSON_INVALID") from exc


def _load_profile_file(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ProfileStoreError("PROFILE_NOT_FOUND_OR_UNSAFE")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_PROFILE_BYTES:
                raise ProfileStoreError("PROFILE_FILE_INVALID")
            payload = stream.read(MAX_PROFILE_BYTES + 1)
    except ProfileStoreError:
        raise
    except OSError as exc:
        raise ProfileStoreError("PROFILE_READ_FAILED") from exc
    if len(payload) > MAX_PROFILE_BYTES:
        raise ProfileStoreError("PROFILE_FILE_TOO_LARGE")
    value = _strict_json_loads(payload)
    if not isinstance(value, dict):
        raise ProfileStoreError("PROFILE_OBJECT_REQUIRED")
    return value


def _validate_profile(profile: Mapping[str, Any], *, expected_id: str | None = None) -> dict[str, Any]:
    if not isinstance(profile, Mapping):
        raise ProfileStoreError("PROFILE_OBJECT_REQUIRED")
    required = {"schema_version", "profile_id", "name", "engine_id", "mode", "language", "voice_id",
                "voice_description", "reference_asset", "controls", "created_utc"}
    if set(profile) != required:
        raise ProfileStoreError("PROFILE_FIELDS_INVALID")
    if type(profile["schema_version"]) is not int or profile["schema_version"] != 1:
        raise ProfileStoreError("PROFILE_VERSION_UNSUPPORTED")
    profile_id = profile["profile_id"]
    if not isinstance(profile_id, str) or not PROFILE_ID_RE.fullmatch(profile_id) or (expected_id and profile_id != expected_id):
        raise ProfileStoreError("PROFILE_ID_INVALID")
    name = profile["name"]
    if not isinstance(name, str) or name != name.strip() or not 1 <= len(name) <= 80 or any(ord(c) < 32 for c in name):
        raise ProfileStoreError("PROFILE_NAME_INVALID")
    engine, mode = profile["engine_id"], profile["mode"]
    try:
        validate_voice_mode(engine, mode)
    except ValueError as exc:
        raise ProfileStoreError(str(exc).split(":", 1)[0]) from exc
    language = profile["language"]
    if not isinstance(language, str) or not LANGUAGE_RE.fullmatch(language) or language != language.lower():
        raise ProfileStoreError("PROFILE_LANGUAGE_INVALID")
    try:
        # Keep profile storage independent of optional neural package imports.
        from tts_engine_adapters import CHATTERBOX_LANG_IDS, KOKORO_LANG_CODES, LANGUAGE_NAMES
        language_sets = {
            "kokoro": set(KOKORO_LANG_CODES),
            "qwen3_tts": set(LANGUAGE_NAMES),
            "chatterbox": set(CHATTERBOX_LANG_IDS),
        }
        if language not in language_sets[engine]:
            raise ProfileStoreError("PROFILE_LANGUAGE_UNSUPPORTED")
    except ImportError:
        # This source module is part of the core package; absence is a damaged install.
        raise ProfileStoreError("PROFILE_LANGUAGE_REGISTRY_MISSING")

    voice_id, description, reference_asset = profile["voice_id"], profile["voice_description"], profile["reference_asset"]
    if mode == "voice_design":
        if voice_id is not None or not isinstance(description, str) or not 1 <= len(description.strip()) <= 1600 or "\x00" in description or reference_asset is not None:
            raise ProfileStoreError("PROFILE_VOICE_DESIGN_INVALID")
        if any(ord(c) < 32 and c not in "\n\r\t" for c in description):
            raise ProfileStoreError("PROFILE_VOICE_DESIGN_INVALID")
    elif mode == "reference_clone":
        if voice_id not in (None, "reference") or description is not None or not isinstance(reference_asset, str):
            raise ProfileStoreError("PROFILE_REFERENCE_CLONE_INVALID")
        _asset_path(Path("/profile-root"), reference_asset, profile_id)
    else:
        if not isinstance(voice_id, str) or not VOICE_ID_RE.fullmatch(voice_id) or description is not None or reference_asset is not None:
            raise ProfileStoreError("PROFILE_PRESET_INVALID")

    try:
        controls = validate_controls(engine, mode, profile["controls"])
    except ValueError as exc:
        raise ProfileStoreError(str(exc).split(":", 1)[0], str(exc).split(":", 1)[-1]) from exc
    created = profile["created_utc"]
    if not isinstance(created, str):
        raise ProfileStoreError("PROFILE_TIMESTAMP_INVALID")
    try:
        timestamp = datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProfileStoreError("PROFILE_TIMESTAMP_INVALID") from exc
    if timestamp.tzinfo is None:
        raise ProfileStoreError("PROFILE_TIMESTAMP_INVALID")
    return {**dict(profile), "controls": controls}


def _copy_reference(source_path: str | Path, root: Path, profile_id: str) -> str:
    try:
        source = Path(source_path).expanduser()
        if source.is_symlink() or source.suffix.lower() != ".wav":
            raise ProfileStoreError("PROFILE_REFERENCE_FILE_UNSAFE")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(source, flags)
        stream = os.fdopen(fd, "rb")
    except ProfileStoreError:
        raise
    except OSError as exc:
        raise ProfileStoreError("PROFILE_REFERENCE_NOT_READABLE") from exc

    target = _asset_path(root, f"assets/{profile_id}/reference.wav", profile_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.parent.is_symlink() or target.exists() or target.is_symlink():
        stream.close()
        raise ProfileStoreError("PROFILE_REFERENCE_DESTINATION_UNSAFE")
    temp_path: str | None = None
    try:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_REFERENCE_BYTES:
            raise ProfileStoreError("PROFILE_REFERENCE_SIZE_INVALID")
        try:
            with wave.open(stream, "rb") as audio:
                channels, rate, frames, width, comptype = (audio.getnchannels(), audio.getframerate(),
                                                           audio.getnframes(), audio.getsampwidth(), audio.getcomptype())
                duration = frames / rate if rate else 0.0
                if channels not in (1, 2) or width not in (1, 2, 3, 4) or rate < 8000 or rate > 96000 or frames <= 0 or comptype != "NONE" or duration > MAX_REFERENCE_SECONDS:
                    raise ProfileStoreError("PROFILE_REFERENCE_AUDIO_INVALID")
                audio.readframes(frames)
        except (wave.Error, EOFError, OSError) as exc:
            raise ProfileStoreError("PROFILE_REFERENCE_AUDIO_INVALID") from exc
        stream.seek(0)
        fd_out, temp_path = tempfile.mkstemp(prefix=".reference.", suffix=".tmp", dir=target.parent)
        if os.name != "nt":
            os.fchmod(fd_out, 0o600)
        with os.fdopen(fd_out, "wb") as output:
            shutil.copyfileobj(stream, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        # Recheck that the file did not grow between initial stat and copy.
        if os.path.getsize(temp_path) != info.st_size or os.path.getsize(temp_path) > MAX_REFERENCE_BYTES:
            raise ProfileStoreError("PROFILE_REFERENCE_CHANGED_DURING_COPY")
        os.replace(temp_path, target)
        temp_path = None
    finally:
        stream.close()
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
    return f"assets/{profile_id}/reference.wav"


def create_profile(store_dir: str | Path, *, profile_id: str, name: str, engine_id: str, mode: str,
                   language: str, voice_id: str | None = None, voice_description: str | None = None,
                   controls: Mapping[str, Any] | None = None,
                   reference_audio: str | Path | None = None) -> dict[str, Any]:
    """Create a profile atomically. A reference WAV is copied, never moved."""
    root = _store_root(store_dir)
    if not isinstance(profile_id, str) or not PROFILE_ID_RE.fullmatch(profile_id):
        raise ProfileStoreError("PROFILE_ID_INVALID")
    try:
        validate_voice_mode(engine_id, mode)
    except ValueError as exc:
        raise ProfileStoreError(str(exc)) from exc
    if mode == "voice_design":
        if voice_id is not None or reference_audio is not None:
            raise ProfileStoreError("PROFILE_VOICE_DESIGN_INVALID")
        reference_asset = None
    elif mode == "reference_clone":
        if voice_description is not None or voice_id not in (None, "reference") or reference_audio is None:
            raise ProfileStoreError("PROFILE_REFERENCE_CLONE_INVALID")
        voice_id = None
        reference_asset = f"assets/{profile_id}/reference.wav"
    else:
        if not isinstance(voice_id, str) or voice_description is not None or reference_audio is not None:
            raise ProfileStoreError("PROFILE_PRESET_INVALID")
        reference_asset = None
    try:
        normalized_controls = validate_controls(engine_id, mode, controls)
    except ValueError as exc:
        raise ProfileStoreError(str(exc).split(":", 1)[0], str(exc).split(":", 1)[-1]) from exc

    profile = {
        "schema_version": 1,
        "profile_id": profile_id,
        "name": name.strip() if isinstance(name, str) else name,
        "engine_id": engine_id,
        "mode": mode,
        "language": language.lower() if isinstance(language, str) else language,
        "voice_id": voice_id,
        "voice_description": voice_description.strip() if isinstance(voice_description, str) else voice_description,
        "reference_asset": reference_asset,
        "controls": normalized_controls,
        "created_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    checked = _validate_profile(profile, expected_id=profile_id)
    target = _profile_path(root, profile_id)
    with _store_lock(root):
        if target.exists() or target.is_symlink():
            raise ProfileStoreError("PROFILE_ALREADY_EXISTS")
        copied = False
        if mode == "reference_clone":
            _copy_reference(reference_audio, root, profile_id)
            copied = True
        try:
            payload = (json.dumps(checked, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
            _atomic_write(target, payload)
        except Exception:
            if copied:
                asset = _asset_path(root, reference_asset, profile_id)
                try:
                    asset.unlink()
                    asset.parent.rmdir()
                except OSError:
                    pass
            raise
    return checked


def load_profile(store_dir: str | Path, profile_id: str) -> dict[str, Any]:
    root = _store_root(store_dir)
    path = _profile_path(root, profile_id)
    profile = _validate_profile(_load_profile_file(path), expected_id=profile_id)
    if profile["reference_asset"] is not None:
        asset = _asset_path(root, profile["reference_asset"], profile_id)
        if asset.is_symlink():
            raise ProfileStoreError("PROFILE_REFERENCE_NOT_FOUND_OR_UNSAFE")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(asset, flags)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_REFERENCE_BYTES:
                    raise ProfileStoreError("PROFILE_REFERENCE_NOT_FOUND_OR_UNSAFE")
                # Revalidate the copied audio when reading a profile, not just its suffix.
                with wave.open(stream, "rb") as audio:
                    rate, frames = audio.getframerate(), audio.getnframes()
                    if (audio.getnchannels() not in (1, 2) or audio.getsampwidth() not in (1, 2, 3, 4)
                            or rate < 8000 or rate > 96000 or frames <= 0 or frames / rate > MAX_REFERENCE_SECONDS
                            or audio.getcomptype() != "NONE"):
                        raise ProfileStoreError("PROFILE_REFERENCE_AUDIO_INVALID")
                    audio.readframes(frames)
        except ProfileStoreError:
            raise
        except (wave.Error, EOFError, OSError) as exc:
            raise ProfileStoreError("PROFILE_REFERENCE_AUDIO_INVALID") from exc
    return profile


def reference_audio_path(store_dir: str | Path, profile_id: str) -> Path:
    """Return the fixed, store-contained WAV path for a validated clone profile."""
    profile = load_profile(store_dir, profile_id)
    relative = profile["reference_asset"]
    if relative is None:
        raise ProfileStoreError("PROFILE_REFERENCE_NOT_CONFIGURED")
    root = _store_root(store_dir)
    target = _asset_path(root, relative, profile_id)
    if target.is_symlink() or not target.is_file():
        raise ProfileStoreError("PROFILE_REFERENCE_NOT_FOUND_OR_UNSAFE")
    return target


def update_controls(store_dir: str | Path, profile_id: str, updates: Mapping[str, Any]) -> dict[str, Any]:
    """Atomically merge supported controls into a profile; unknown keys fail."""
    root = _store_root(store_dir)
    target = _profile_path(root, profile_id)
    with _store_lock(root):
        current = _validate_profile(_load_profile_file(target), expected_id=profile_id)
        merged = dict(current["controls"])
        if not isinstance(updates, Mapping):
            raise ProfileStoreError("VOICE_CONTROLS_INVALID")
        merged.update(updates)
        try:
            current["controls"] = validate_controls(current["engine_id"], current["mode"], merged)
        except ValueError as exc:
            raise ProfileStoreError(str(exc).split(":", 1)[0], str(exc).split(":", 1)[-1]) from exc
        checked = _validate_profile(current, expected_id=profile_id)
        payload = (json.dumps(checked, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        _atomic_write(target, payload)
    return checked


def list_profiles(store_dir: str | Path) -> list[dict[str, Any]]:
    root = _store_root(store_dir)
    profiles_dir = root / "profiles"
    if profiles_dir.is_symlink():
        raise ProfileStoreError("PROFILE_PATH_SYMLINK")
    if not profiles_dir.exists():
        return []
    if not profiles_dir.is_dir():
        raise ProfileStoreError("PROFILE_PATH_INVALID")
    result = []
    for path in sorted(profiles_dir.glob("*.json"), key=lambda p: p.name):
        if path.is_symlink():
            raise ProfileStoreError("PROFILE_PATH_SYMLINK")
        profile_id = path.stem
        if not PROFILE_ID_RE.fullmatch(profile_id):
            raise ProfileStoreError("PROFILE_FILENAME_INVALID")
        result.append(load_profile(root, profile_id))
    return result


def delete_profile(store_dir: str | Path, profile_id: str) -> None:
    """Delete exactly one named profile and its fixed, contained reference asset."""
    root = _store_root(store_dir)
    target = _profile_path(root, profile_id)
    with _store_lock(root):
        profile = _validate_profile(_load_profile_file(target), expected_id=profile_id)
        if profile["reference_asset"] is not None:
            asset = _asset_path(root, profile["reference_asset"], profile_id)
            if asset.is_symlink():
                raise ProfileStoreError("PROFILE_REFERENCE_SYMLINK")
            if asset.exists():
                asset.unlink()
            try:
                asset.parent.rmdir()
            except OSError:
                pass
        target.unlink()
