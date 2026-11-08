"""Per-task git worktrees outside the repository (SPEC §7)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from samba.config import Config
from samba.proc import git, run_shell


class WorkspaceError(Exception):
    pass


def repo_key(repo: Path) -> str:
    resolved = repo.resolve()
    digest = hashlib.sha256(str(resolved).encode()).hexdigest()[:8]
    return f"{resolved.name}-{digest}"


def branch_name(task_id: str) -> str:
    return f"samba/{task_id}"


class Workspaces:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.root = (config.workspaces_root / repo_key(config.repo)).resolve()

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
        repo = self.config.repo
        branch = branch_name(task_id)
        exists = await git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
        if exists.ok:
            res = await git(repo, "worktree", "add", str(path), branch)
        else:
            res = await git(repo, "worktree", "add", "-b", branch, str(path),
                            self.config.base_branch)
        if not res.ok:
            raise WorkspaceError(f"git worktree add failed: {res.output.strip()[-500:]}")
        if self.config.after_create:
            hook = await run_shell(self.config.shell, self.config.after_create, path,
                                   self.config.hooks_timeout_s)
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
        res = await git(self.config.repo, "worktree", "remove", "--force", str(path))
        if not res.ok and path.exists():
            raise WorkspaceError(f"git worktree remove failed: {res.output.strip()[-500:]}")
        await git(self.config.repo, "worktree", "prune")
