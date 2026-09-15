"""Serialize metadata transactions across callbacks and local app processes."""
from contextlib import contextmanager
from functools import wraps
from threading import RLock, local
import msvcrt
from services.project_paths import PROJECT_ROOT
from models.schemas import AppError

_lock = RLock()
_state = local()


@contextmanager
def metadata_lock():
    with _lock:
        if getattr(_state, "depth", 0):
            _state.depth += 1
            try:
                yield
            finally:
                _state.depth -= 1
            return
        path = PROJECT_ROOT / "data/.metadata.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as handle:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise AppError("STORAGE_BUSY", "另一个进程正在更新仓库，请稍后重试。") from exc
            _state.depth = 1
            try:
                yield
            finally:
                _state.depth = 0
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def serialized(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with metadata_lock():
            return fn(*args, **kwargs)
    return wrapped
