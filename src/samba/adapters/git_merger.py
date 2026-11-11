"""`GitMerger`: the `Merger` port over `samba.merge` (git in the main checkout)."""

from __future__ import annotations

from typing import cast

from samba import merge
from samba.config import Layout, Validation
from samba.ports import MergeResult, MergeStatus
from samba.workspace import branch_name


class GitMerger:
    def __init__(self, layout: Layout, validation: Validation) -> None:
        self.layout = layout
        self.validation = validation

    def branch_name(self, task_id: str) -> str:
        return branch_name(task_id)

    def preflight(self, branch: str) -> str | None:
        return merge.preflight(self.layout.repo, self.layout.base_branch, branch)

    def commit_count(self, branch: str) -> int:
        return merge.commit_count(self.layout.repo, self.layout.base_branch, branch)

    def merge(self, task_id: str, branch: str, message: str, validate: bool) -> MergeResult:
        v = self.validation
        res = merge.merge_branch(
            self.layout.repo, branch, message, shell=v.shell,
            validate_command=v.command if validate else None, timeout_s=v.timeout_s,
            tail_lines=v.tail_lines,
            log_path=self.layout.samba_dir / "runs" / task_id / "accept-validate.log")
        return MergeResult(cast(MergeStatus, res.status), res.detail, res.validated,
                           str(res.log_path) if res.log_path is not None else None)
