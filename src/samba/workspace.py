"""Per-task git worktrees outside the repository (spec: workspaces)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from samba.config import Hooks, Layout
from samba.ports import WorkspaceError
from samba.proc import git, run_shell


def repo_key(repo: Path) -> str:
    resolved = repo.resolve()
    digest = hashlib.sha256(str(resolved).encode()).hexdigest()[:8]
    return f"{resolved.name}-{digest}"


def branch_name(task_id: str) -> str:
    return f"samba/{task_id}"


class Workspaces:
    def __init__(self, layout: Layout, hooks: Hooks, shell: list[str]) -> None:
        self.layout = layout
        self.hooks = hooks
        self.shell = shell
        self.root = (layout.workspaces_root / repo_key(layout.repo)).resolve()

    def path(self, task_id: str) -> Path:
        p = (self.root / task_id).resolve()
        if p.parent != self.root:
            raise WorkspaceError(f"workspace path {p} escapes {self.root}")
        return p

    def existing_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir())

    async def ensure(self, task_id: str) -> tuple[Path, bool]:
        """Create the worktree if needed. Returns (path, created_now)."""
        path = self.path(task_id)
        if path.is_dir():
            return path, False
        self.root.mkdir(parents=True, exist_ok=True)
        repo = self.layout.repo
        branch = branch_name(task_id)
        exists = await git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
        if exists.ok:
            res = await git(repo, "worktree", "add", str(path), branch)
        else:
            res = await git(repo, "worktree", "add", "-b", branch, str(path),
                            self.layout.base_branch)
        if not res.ok:
            raise WorkspaceError(f"git worktree add failed: {res.output.strip()[-500:]}")
        if self.hooks.after_create:
            hook = await run_shell(self.shell, self.hooks.after_create, path,
                                   self.hooks.timeout_s)
            if not hook.ok:
                await self.remove(task_id)
                why = "timed out" if hook.timed_out else f"exit {hook.code}"
                raise WorkspaceError(
                    f"after_create hook {why}: {hook.output.strip()[-500:]}")
        return path, True

    async def remove(self, task_id: str) -> None:
        path = self.path(task_id)
        if not path.exists():
            return
        res = await git(self.layout.repo, "worktree", "remove", "--force", str(path))
        if not res.ok and path.exists():
            raise WorkspaceError(f"git worktree remove failed: {res.output.strip()[-500:]}")
        await git(self.layout.repo, "worktree", "prune")
