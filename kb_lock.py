from __future__ import annotations

import os
import tempfile
from pathlib import Path

from kb_config import INSTANCE_LOCK_FILENAME


def _close_fd_safely(lock_fd: int) -> None:
    try:
        os.close(lock_fd)
    except OSError:
        pass


def _unlink_safely(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except OSError:
        pass


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def acquire_instance_lock() -> tuple[int, Path] | None:
    lock_path = Path(tempfile.gettempdir()) / INSTANCE_LOCK_FILENAME
    current_pid = os.getpid()

    for _ in range(2):
        try:
            lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
        except FileExistsError:
            try:
                existing_pid_text = lock_path.read_text(encoding="utf-8").strip()
                existing_pid = int(existing_pid_text)
            except (OSError, ValueError):
                existing_pid = -1

            if _pid_is_running(existing_pid):
                return None

            _unlink_safely(lock_path)
            continue
        except OSError:
            return None

        try:
            os.write(lock_fd, str(current_pid).encode("utf-8"))
            os.fsync(lock_fd)
        except OSError:
            _close_fd_safely(lock_fd)
            _unlink_safely(lock_path)
            return None

        return lock_fd, lock_path

    return None


def release_instance_lock(lock_fd: int, lock_path: Path) -> None:
    _close_fd_safely(lock_fd)
    _unlink_safely(lock_path)
