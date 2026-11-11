"""In-memory `Vcs`: workspaces in a set, scripted merge results, a call log, failure injection."""

from __future__ import annotations

from samba.ports import CommitResult, MergeAttempt, Workspace, WorkspaceError


class FakeVcs:
    def __init__(self, *, merge: MergeAttempt | None = None, problem: str | None = None,
                 commits: int = 2, commit: CommitResult | None = None,
                 repo_problem: str | None = None, ensure_error: str | None = None,
                 remove_error: str | None = None) -> None:
        self.merge = merge or MergeAttempt("pending", "", "pre0001")
        self.problem = problem
        self.commits = commits
        self.commit = commit or CommitResult(True, "abc1234")
        self.repo_problem = repo_problem
        self.ensure_error = ensure_error
        self.remove_error = remove_error
        self.workspaces: set[str] = set()
        self.calls: list[tuple[str, ...]] = []

    def branch_name(self, task_id: str) -> str:
        return f"samba/{task_id}"

    def workspace_location(self, task_id: str) -> str:
        return f"/ws/{task_id}"

    def checkout_location(self) -> str:
        return "/repo"

    async def ensure_workspace(self, task_id: str) -> Workspace:
        self.calls.append(("ensure_workspace", task_id))
        if self.ensure_error:
            raise WorkspaceError(self.ensure_error)
        created = task_id not in self.workspaces
        self.workspaces.add(task_id)
        return Workspace(self.workspace_location(task_id), created)

    async def remove_workspace(self, task_id: str) -> None:
        self.calls.append(("remove_workspace", task_id))
        if self.remove_error:
            raise WorkspaceError(self.remove_error)
        self.workspaces.discard(task_id)

    async def existing_workspaces(self) -> list[str]:
        return sorted(self.workspaces)

    async def repository_problem(self) -> str | None:
        return self.repo_problem

    async def exclude_samba_dir(self) -> None:
        self.calls.append(("exclude_samba_dir",))

    async def preflight(self, branch: str) -> str | None:
        self.calls.append(("preflight", branch))
        return self.problem

    async def commit_count(self, branch: str) -> int:
        return self.commits

    async def begin_merge(self, branch: str, message: str) -> MergeAttempt:
        self.calls.append(("begin_merge", branch, message))
        return self.merge

    async def abort_merge(self, restore_point: str) -> None:
        self.calls.append(("abort_merge", restore_point))

    async def commit_merge(self, restore_point: str) -> CommitResult:
        self.calls.append(("commit_merge", restore_point))
        return self.commit
