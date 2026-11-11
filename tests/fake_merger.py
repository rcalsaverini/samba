"""Scripted `Merger` for in-process tests: records its calls, returns what it was given."""

from __future__ import annotations

from samba.ports import MergeResult


class FakeMerger:
    def __init__(self, result: MergeResult | None = None, problem: str | None = None,
                 commits: int = 2) -> None:
        self.result = result or MergeResult("merged", "abc1234", validated=True)
        self.problem = problem
        self.commits = commits
        self.calls: list[tuple[str, str, str, bool]] = []
        self.preflights = 0

    def branch_name(self, task_id: str) -> str:
        return f"samba/{task_id}"

    def preflight(self, branch: str) -> str | None:
        self.preflights += 1
        return self.problem

    def commit_count(self, branch: str) -> int:
        return self.commits

    def merge(self, task_id: str, branch: str, message: str, validate: bool) -> MergeResult:
        self.calls.append((task_id, branch, message, validate))
        return self.result
