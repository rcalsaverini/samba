"""`FileRepoLock`: the `RepoLock` port over `samba.lock.repo_lock`."""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path

from samba.lock import repo_lock


class FileRepoLock:
    def __init__(self, samba_dir: Path) -> None:
        self.samba_dir = samba_dir

    def acquire(self, blocking: bool = True) -> AbstractContextManager[bool]:
        return repo_lock(self.samba_dir, blocking=blocking)
