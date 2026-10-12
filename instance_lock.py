"""Khóa thư mục dữ liệu để mỗi thư mục chỉ có một app chạy.

Dùng khóa của hệ điều hành trên file `app.lock`, nên app bị tắt ngang (crash, kill)
thì khóa tự nhả, không để lại khóa treo.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

LOCK_NAME = "app.lock"
PID_NAME = "app.pid"


class AlreadyRunning(RuntimeError):
    pass


class InstanceLock:
    def __init__(self, handle, data_dir: Path) -> None:
        self._handle = handle
        self.data_dir = data_dir

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            _unlock(self._handle)
        finally:
            self._handle.close()
            self._handle = None
            try:
                (self.data_dir / PID_NAME).unlink()
            except OSError:
                pass


def acquire(data_dir: Path) -> InstanceLock:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    handle = open(data_dir / LOCK_NAME, "a+b")
    try:
        _lock(handle)
    except OSError:
        handle.close()
        raise AlreadyRunning(_busy_message(data_dir)) from None
    (data_dir / PID_NAME).write_text(str(os.getpid()), encoding="utf-8")
    return InstanceLock(handle, data_dir)


def _busy_message(data_dir: Path) -> str:
    try:
        pid = (data_dir / PID_NAME).read_text(encoding="utf-8").strip()
    except OSError:
        pid = ""
    owner = f" (PID {pid})" if pid else ""
    return (
        f"Thư mục dữ liệu {data_dir} đang được một cửa sổ tool khác dùng{owner}. "
        "Hãy dùng cửa sổ đang chạy, hoặc tắt nó trước khi mở lại."
    )


if sys.platform == "win32":
    import msvcrt

    def _lock(handle) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(handle) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
