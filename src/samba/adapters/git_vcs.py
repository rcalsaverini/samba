"""`GitVcs`: the `Vcs` port over git (worktrees outside the repository, merge in the main checkout)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from samba.config import Hooks, Layout
from samba.ports import CommitResult, MergeAttempt, Workspace, WorkspaceError
from samba.proc import git, run_shell


def repo_key(repo: Path) -> str:
    resolved = repo.resolve()
    digest = hashlib.sha256(str(resolved).encode()).hexdigest()[:8]
    return f"{resolved.name}-{digest}"


class GitVcs:
    def __init__(self, layout: Layout, hooks: Hooks, shell: list[str]) -> None:
        self.layout = layout
        self.hooks = hooks
        self.shell = shell
        self.root = (layout.workspaces_root / repo_key(layout.repo)).resolve()

    # ---- naming -------------------------------------------------------------------------

    def branch_name(self, task_id: str) -> str:
        return f"samba/{task_id}"

    def _path(self, task_id: str) -> Path:
        p = (self.root / task_id).resolve()
        if p.parent != self.root:
            raise WorkspaceError(f"workspace path {p} escapes {self.root}")
        return p

    def workspace_location(self, task_id: str) -> str:
        return str(self._path(task_id))

    def checkout_location(self) -> str:
        return str(self.layout.repo)

    # ---- workspaces ---------------------------------------------------------------------

    async def existing_workspaces(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir())

    async def ensure_workspace(self, task_id: str) -> Workspace:
        path = self._path(task_id)
        if path.is_dir():
            return Workspace(str(path), False)
        self.root.mkdir(parents=True, exist_ok=True)
        repo = self.layout.repo
        branch = self.branch_name(task_id)
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
                await self.remove_workspace(task_id)
                why = "timed out" if hook.timed_out else f"exit {hook.code}"
                raise WorkspaceError(
                    f"after_create hook {why}: {hook.output.strip()[-500:]}")
        return Workspace(str(path), True)

    async def remove_workspace(self, task_id: str) -> None:
        path = self._path(task_id)
        if not path.exists():
            return
        res = await git(self.layout.repo, "worktree", "remove", "--force", str(path))
        if not res.ok and path.exists():
            raise WorkspaceError(f"git worktree remove failed: {res.output.strip()[-500:]}")
        await git(self.layout.repo, "worktree", "prune")

    # ---- repository ---------------------------------------------------------------------

    async def repository_problem(self) -> str | None:
        layout = self.layout
        top = await git(layout.repo, "rev-parse", "--show-toplevel")
        if not top.ok or Path(top.output.strip()).resolve() != layout.repo:
            return f"{layout.repo} is not the root of a git repository"
        base = await git(layout.repo, "rev-parse", "--verify", "--quiet",
                         f"refs/heads/{layout.base_branch}")
        if not base.ok:
            return f"base_branch '{layout.base_branch}' does not exist"
        return None

    async def exclude_samba_dir(self) -> None:
        repo = self.layout.repo
        try:
            rel = self.layout.samba_dir.relative_to(repo)
        except ValueError:
            return  # samba_dir outside the repo: nothing to exclude
        res = await git(repo, "rev-parse", "--git-path", "info/exclude")
        if not res.ok:
            return
        exclude = Path(res.output.strip())
        if not exclude.is_absolute():
            exclude = repo / exclude
        entry = f"/{rel.as_posix()}/"
        existing = exclude.read_text() if exclude.exists() else ""
        if entry not in existing.splitlines() and f"{rel.as_posix()}/" not in existing.splitlines():
            exclude.parent.mkdir(parents=True, exist_ok=True)
            sep = "" if not existing or existing.endswith("\n") else "\n"
            exclude.write_text(existing + sep + entry + "\n")

    # ---- merge (the main checkout) ------------------------------------------------------

    async def _has_tracked_changes(self) -> bool:
        res = await git(self.layout.repo, "status", "--porcelain", "--untracked-files=no")
        return bool(res.output.strip()) or not res.ok

    async def _merge_in_progress(self) -> bool:
        return (await git(self.layout.repo, "rev-parse", "-q", "--verify", "MERGE_HEAD")).ok

    async def preflight(self, branch: str) -> str | None:
        repo = self.layout.repo
        base = self.layout.base_branch
        res = await git(repo, "symbolic-ref", "--short", "-q", "HEAD")
        cur = res.output.strip() if res.ok else None
        if cur != base:
            return f"the main checkout is on {cur or 'a detached HEAD'}, not the base branch {base}"
        if await self._has_tracked_changes():
            return "the main checkout has uncommitted changes to tracked files"
        if not (await git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")).ok:
            return f"branch {branch} does not exist"
        return None

    async def commit_count(self, branch: str) -> int:
        res = await git(self.layout.repo, "rev-list", "--count",
                        f"{self.layout.base_branch}..{branch}")
        return int(res.output.strip()) if res.ok and res.output.strip().isdigit() else 0

    async def begin_merge(self, branch: str, message: str) -> MergeAttempt:
        repo = self.layout.repo
        pre = (await git(repo, "rev-parse", "HEAD")).output.strip()
        res = await git(repo, "merge", "--no-ff", "--no-commit", "-m", message, branch)
        if not res.ok:
            files = (await git(repo, "diff", "--name-only", "--diff-filter=U")).output.split()
            if await self._merge_in_progress():
                await self.abort_merge(pre)
            if files:
                return MergeAttempt("conflict", ", ".join(files), pre)
            return MergeAttempt("error", " | ".join(res.output.split("\n")[-4:]), pre)
        if not await self._merge_in_progress():
            return MergeAttempt("already", "", pre)
        return MergeAttempt("pending", "", pre)

    async def abort_merge(self, restore_point: str) -> None:
        """Abort the merge; if that fails (validation touched tracked files) reset to
        `restore_point`. Safe because preflight proved the tracked tree was clean."""
        repo = self.layout.repo
        aborted = (await git(repo, "merge", "--abort")).ok
        if (not aborted
                or (await git(repo, "rev-parse", "HEAD")).output.strip() != restore_point
                or await self._has_tracked_changes()):
            await git(repo, "reset", "--hard", restore_point)

    async def commit_merge(self, restore_point: str) -> CommitResult:
        repo = self.layout.repo
        commit = await git(repo, "commit", "--no-edit")
        if not commit.ok:
            await self.abort_merge(restore_point)
            return CommitResult(False, " | ".join(commit.output.strip().split("\n")[-4:]))
        return CommitResult(True, (await git(repo, "rev-parse", "--short", "HEAD")).output.strip())
