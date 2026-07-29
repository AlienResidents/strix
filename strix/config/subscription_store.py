"""Shared on-disk store for subscription OAuth credentials.

Every subscription provider (ChatGPT/Codex, Grok) keeps its record under its own
key in a single ``~/.strix/subscription-auth.json`` file. Reads and writes go
through here so that:

* tokens are written owner-only (mode 0600) from the moment the file is created,
  never briefly exposed with umask-derived permissions, and
* concurrent read-modify-write mutations — even across different providers or
  processes — are serialized, so one provider's update can't clobber another's.

The lock is reentrant, so a provider may nest a ``save`` inside a longer
``guard`` (e.g. refreshing a token then persisting it) without deadlocking.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Iterator
    from io import TextIOWrapper
    from pathlib import Path


def read(path: Path) -> dict[str, Any]:
    """The store's contents, or an empty dict when absent/unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write(path: Path, data: dict[str, Any]) -> None:
    """Atomically replace the store, owner-only from creation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    tmp.replace(path)
    with contextlib.suppress(OSError):
        path.chmod(0o600)


class _StoreLock:
    """A reentrant lock serializing store mutations within (thread lock) and
    across (flock) Strix processes. Nesting reuses the single held file lock, so
    a provider can persist a record inside a longer critical section."""

    def __init__(self) -> None:
        self._thread_lock = threading.RLock()
        self._flock_handle: TextIOWrapper | None = None
        self._depth = 0

    @contextlib.contextmanager
    def hold(self, path: Path) -> Iterator[None]:
        with self._thread_lock:
            if self._depth == 0:
                self._flock_handle = _acquire_flock(path)
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
                if self._depth == 0:
                    self._release_flock()

    def _release_flock(self) -> None:
        handle = self._flock_handle
        if handle is None:
            return
        try:
            import fcntl

            with contextlib.suppress(OSError):
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except ImportError:
            pass
        finally:
            handle.close()
            self._flock_handle = None


_store_lock = _StoreLock()


def guard(path: Path) -> contextlib.AbstractContextManager[None]:
    """Serialize store mutation across threads and processes (reentrant)."""
    return _store_lock.hold(path)


def _acquire_flock(path: Path) -> TextIOWrapper | None:
    try:
        import fcntl
    except ImportError:
        return None
    lock_path = path.with_suffix(".lock")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("w")
    except OSError:
        return None
    with contextlib.suppress(OSError):
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle
