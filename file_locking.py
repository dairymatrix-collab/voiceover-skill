"""Small cross-platform advisory file locks for local, single-host coordination."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import stat
import time
from typing import Iterator


class FileLockError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@contextmanager
def exclusive_file_lock(path: str | Path, *, timeout_seconds: float = 10.0,
                        busy_code: str = "LOCK_BUSY", symlink_code: str = "LOCK_PATH_SYMLINK") -> Iterator[None]:
    """Hold an exclusive advisory lock, creating its private lock file if needed."""
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not 0.0 <= timeout_seconds <= 120.0):
        raise FileLockError("LOCK_TIMEOUT_INVALID")
    try:
        requested_path = Path(path).expanduser()
        if requested_path.is_symlink():
            raise FileLockError(symlink_code)
        requested_path.parent.mkdir(parents=True, exist_ok=True)
        # Canonicalize the parent only; preserve the final component so its
        # symlink status can be checked before opening it.
        lock_path = requested_path.parent.resolve(strict=True) / requested_path.name
        if lock_path.is_symlink():
            raise FileLockError(symlink_code)
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(lock_path, flags, 0o600)
    except FileLockError:
        raise
    except OSError as exc:
        raise FileLockError("LOCK_OPEN_FAILED") from exc

    locked = False
    deadline = time.monotonic() + float(timeout_seconds)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise FileLockError("LOCK_FILE_INVALID")
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
                    raise FileLockError(busy_code)
                time.sleep(min(0.05, max(0.001, deadline - time.monotonic())))
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
