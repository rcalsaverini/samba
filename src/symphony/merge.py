"""Git steps of `work accept` (SPEC §11): preflight, merge, validate the merged result, commit."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from symphony.proc import CmdResult, git, run_shell

MAX_LOG_TAIL_LINES = 10


def _git(cwd: Path, *args: str) -> CmdResult:
    return asyncio.run(git(cwd, *args))


def current_branch(repo: Path) -> str | None:
    res = _git(repo, "symbolic-ref", "--short", "-q", "HEAD")
    return res.output.strip() if res.ok else None


def has_tracked_changes(repo: Path) -> bool:
    res = _git(repo, "status", "--porcelain", "--untracked-files=no")
    return bool(res.output.strip()) or not res.ok


def branch_exists(repo: Path, branch: str) -> bool:
    return _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").ok


def commit_count(repo: Path, base: str, branch: str) -> int:
    res = _git(repo, "rev-list", "--count", f"{base}..{branch}")
    return int(res.output.strip()) if res.ok and res.output.strip().isdigit() else 0


def preflight(repo: Path, base: str, branch: str) -> str | None:
    """A message describing the first failed check, or None when the merge may proceed."""
    cur = current_branch(repo)
    if cur != base:
        return f"the main checkout is on {cur or 'a detached HEAD'}, not the base branch {base}"
    if has_tracked_changes(repo):
        return "the main checkout has uncommitted changes to tracked files"
    if not branch_exists(repo, branch):
        return f"branch {branch} does not exist"
    return None


def _merge_in_progress(repo: Path) -> bool:
    return _git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD").ok


@dataclass(frozen=True)
class MergeResult:
    status: str  # merged | already | conflict | validation_failed | error
    detail: str = ""  # sha (merged), files (conflict), log tail (validation_failed), git error
    validated: bool = False
    log_path: Path | None = None


def _tail(output: str, limit: int, timed_out: bool, timeout_s: float) -> str:
    n = max(1, min(MAX_LOG_TAIL_LINES, limit))
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()][-n:]
    text = " | ".join(lines)
    if timed_out:
        note = f"(timed out after {timeout_s:g}s)"
        text = f"{text} {note}".strip()
    return text or "(no output)"


def _undo(repo: Path, pre: str) -> None:
    """Abort the merge; if that fails (validation touched tracked files) reset to `pre`. Safe
    because preflight proved the tracked tree was clean."""
    aborted = _git(repo, "merge", "--abort").ok
    if (not aborted or _git(repo, "rev-parse", "HEAD").output.strip() != pre
            or has_tracked_changes(repo)):
        _git(repo, "reset", "--hard", pre)


def merge_branch(repo: Path, branch: str, message: str, *, shell: list[str],
                 validate_command: str | None, timeout_s: float, tail_lines: int,
                 log_path: Path) -> MergeResult:
    """Merge `branch` with `--no-ff --no-commit`, validate the result in the main checkout, and
    commit only on a pass. On any failure the main checkout is left as it was."""
    pre = _git(repo, "rev-parse", "HEAD").output.strip()
    res = _git(repo, "merge", "--no-ff", "--no-commit", "-m", message, branch)
    if not res.ok:
        files = _git(repo, "diff", "--name-only", "--diff-filter=U").output.split()
        if _merge_in_progress(repo):
            _undo(repo, pre)
        return MergeResult("conflict" if files else "error",
                           ", ".join(files) if files else " | ".join(res.output.split("\n")[-4:]))
    if not _merge_in_progress(repo):
        return MergeResult("already")
    validated = False
    if validate_command:
        run = asyncio.run(run_shell(shell, validate_command, repo, timeout_s))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(run.output)
        if not run.ok:
            _undo(repo, pre)
            return MergeResult("validation_failed",
                               _tail(run.output, tail_lines, run.timed_out, timeout_s),
                               log_path=log_path)
        validated = True
    commit = _git(repo, "commit", "--no-edit")
    if not commit.ok:
        _undo(repo, pre)
        return MergeResult("error", " | ".join(commit.output.strip().split("\n")[-4:]))
    return MergeResult("merged", _git(repo, "rev-parse", "--short", "HEAD").output.strip(),
                       validated=validated)
