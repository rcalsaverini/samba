"""`FileLock`, the `Lock` port: an advisory flock on `<samba_dir>/lock` (spec: task-files, Write
discipline). It serialises state-changing commands against the orchestrator."""

from __future__ import annotations

import fcntl
import os
import time
from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

LOCK_NAME = "lock"


class FileLock:
    def __init__(self, samba_dir: Path, timeout: float = 10.0) -> None:
        self.samba_dir = samba_dir
        self.timeout = timeout

    def acquire(self, blocking: bool = True) -> AbstractContextManager[bool]:
        return self._hold(blocking)

    @contextmanager
    def _hold(self, blocking: bool) -> Generator[bool]:
        """Yields True once held. Non-blocking, or blocking past `timeout` seconds, yields False
        and holds nothing."""
        self.samba_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.samba_dir / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o644)
        held = False
        try:
            deadline = time.monotonic() + self.timeout
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held = True
                    break
                except BlockingIOError:
                    if not blocking or time.monotonic() >= deadline:
                        break
                    time.sleep(0.02)
            yield held
        finally:
            if held:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
