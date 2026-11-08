"""Advisory repo lock (SPEC §3.3): serialises state-changing commands against the orchestrator."""

from __future__ import annotations

import fcntl
import os
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

LOCK_NAME = "lock"


@contextmanager
def repo_lock(symphony_dir: Path, *, blocking: bool = True,
              timeout: float = 10.0) -> Generator[bool]:
    """Hold `<symphony_dir>/lock` (flock). Yields True once held. Non-blocking, or blocking past
    `timeout` seconds, yields False and holds nothing."""
    symphony_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(symphony_dir / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o644)
    held = False
    try:
        deadline = time.monotonic() + timeout
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
