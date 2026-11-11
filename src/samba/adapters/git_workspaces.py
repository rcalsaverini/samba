"""`GitWorkspaces`: the `Workspaces` port over `samba.workspace` (git worktrees)."""

from __future__ import annotations

from pathlib import Path

from samba.config import Hooks, Layout
from samba.workspace import Workspaces as _Worktrees


class GitWorkspaces:
    def __init__(self, layout: Layout, hooks: Hooks, shell: list[str]) -> None:
        self._worktrees = _Worktrees(layout, hooks, shell)

    def existing_ids(self) -> list[str]:
        return self._worktrees.existing_ids()

    async def remove(self, task_id: str) -> None:
        await self._worktrees.remove(task_id)

    # What the worker needs beyond the port.

    def path(self, task_id: str) -> Path:
        return self._worktrees.path(task_id)

    async def ensure(self, task_id: str) -> tuple[Path, bool]:
        return await self._worktrees.ensure(task_id)
