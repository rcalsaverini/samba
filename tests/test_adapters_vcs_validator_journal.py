"""Adapter tests: `GitVcs` over a temp git repo, `ShellValidator`, `LogJournal`.

This file may import adapters (the black-box and scenario runners may not).
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from collections.abc import Coroutine, Iterator
from pathlib import Path
from typing import TypeVar

import pytest

from samba.adapters.git_vcs import GitVcs
from samba.adapters.log_journal import LogJournal, NullJournal
from samba.adapters.shell_validator import ShellValidator
from samba.config import Hooks, Layout, Validation
from samba.domain.ports import WorkspaceError

SH = ["sh", "-c"]


def git(cwd: Path, *args: str) -> str:
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def commit_file(cwd: Path, name: str, text: str, message: str) -> None:
    (cwd / name).write_text(text)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = (tmp_path / "repo").resolve()
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "T")
    commit_file(r, "a.txt", "one\n", "init")
    return r


def make_vcs(repo: Path, tmp_path: Path, hook: str | None = None) -> GitVcs:
    layout = Layout(repo=repo, samba_dir=repo / ".samba", workspaces_root=tmp_path / "ws",
                    base_branch="main")
    return GitVcs(layout, Hooks(after_create=hook, timeout_s=30), SH)


T = TypeVar("T")


def run(coro: Coroutine[object, object, T]) -> T:
    return asyncio.run(coro)


# ---- workspaces -------------------------------------------------------------------------


def test_workspace_create_reuse_and_remove(repo: Path, tmp_path: Path) -> None:
    vcs = make_vcs(repo, tmp_path)
    assert run(vcs.existing_workspaces()) == []
    ws = run(vcs.ensure_workspace("t-1"))
    assert ws.created and Path(ws.location).is_dir()
    assert ws.location == vcs.workspace_location("t-1")
    assert git(Path(ws.location), "branch", "--show-current") == vcs.branch_name("t-1") == "samba/t-1"
    again = run(vcs.ensure_workspace("t-1"))
    assert not again.created and again.location == ws.location
    assert run(vcs.existing_workspaces()) == ["t-1"]
    run(vcs.remove_workspace("t-1"))
    assert not Path(ws.location).exists()
    run(vcs.remove_workspace("t-1"))  # removing nothing is fine


def test_failing_after_create_hook_removes_the_worktree(repo: Path, tmp_path: Path) -> None:
    vcs = make_vcs(repo, tmp_path, hook="echo boom; exit 3")
    with pytest.raises(WorkspaceError, match=r"after_create hook exit 3: boom"):
        run(vcs.ensure_workspace("t-1"))
    assert not Path(vcs.workspace_location("t-1")).exists()
    assert run(vcs.existing_workspaces()) == []


def test_the_after_create_hook_runs_in_the_new_workspace(repo: Path, tmp_path: Path) -> None:
    vcs = make_vcs(repo, tmp_path, hook="touch hooked")
    ws = run(vcs.ensure_workspace("t-1"))
    assert (Path(ws.location) / "hooked").exists()


def test_a_workspace_id_cannot_escape_the_root(repo: Path, tmp_path: Path) -> None:
    vcs = make_vcs(repo, tmp_path)
    with pytest.raises(WorkspaceError, match="escapes"):
        vcs.workspace_location("../x")


# ---- repository -------------------------------------------------------------------------


def test_repository_problem(repo: Path, tmp_path: Path) -> None:
    assert run(make_vcs(repo, tmp_path).repository_problem()) is None
    layout = Layout(repo=repo, samba_dir=repo / ".samba", workspaces_root=tmp_path / "ws",
                    base_branch="nope")
    assert run(GitVcs(layout, Hooks(None, 1), SH).repository_problem()) == (
        "base_branch 'nope' does not exist")
    sub = repo / "sub"
    sub.mkdir()
    layout = Layout(repo=sub, samba_dir=sub / ".samba", workspaces_root=tmp_path / "ws",
                    base_branch="main")
    assert run(GitVcs(layout, Hooks(None, 1), SH).repository_problem()) == (
        f"{sub} is not the root of a git repository")


def test_exclude_samba_dir_is_idempotent(repo: Path, tmp_path: Path) -> None:
    vcs = make_vcs(repo, tmp_path)
    run(vcs.exclude_samba_dir())
    run(vcs.exclude_samba_dir())
    exclude = (repo / ".git" / "info" / "exclude").read_text().splitlines()
    assert exclude.count("/.samba/") == 1


# ---- merge ------------------------------------------------------------------------------


def make_branch(repo: Path, branch: str, name: str, text: str) -> None:
    git(repo, "checkout", "-q", "-b", branch)
    commit_file(repo, name, text, f"work on {name}")
    git(repo, "checkout", "-q", "main")


def test_preflight_checks(repo: Path, tmp_path: Path) -> None:
    vcs = make_vcs(repo, tmp_path)
    assert run(vcs.preflight("samba/x")) == "branch samba/x does not exist"
    (repo / "a.txt").write_text("dirty\n")
    assert run(vcs.preflight("samba/x")) == (
        "the main checkout has uncommitted changes to tracked files")
    git(repo, "checkout", "-q", "--", "a.txt")
    git(repo, "checkout", "-q", "-b", "other")
    assert run(vcs.preflight("samba/x")) == (
        "the main checkout is on other, not the base branch main")


def test_merge_pending_then_commit(repo: Path, tmp_path: Path) -> None:
    vcs = make_vcs(repo, tmp_path)
    make_branch(repo, "samba/x", "b.txt", "b\n")
    assert run(vcs.commit_count("samba/x")) == 1
    attempt = run(vcs.begin_merge("samba/x", "Merge x"))
    assert attempt.status == "pending" and attempt.restore_point == git(repo, "rev-parse", "HEAD")
    done = run(vcs.commit_merge(attempt.restore_point))
    assert done.ok and done.detail == git(repo, "rev-parse", "--short", "HEAD")
    assert git(repo, "log", "-1", "--format=%s") == "Merge x"
    assert run(vcs.commit_count("samba/x")) == 0


def test_merge_already_merged(repo: Path, tmp_path: Path) -> None:
    vcs = make_vcs(repo, tmp_path)
    make_branch(repo, "samba/x", "b.txt", "b\n")
    git(repo, "merge", "-q", "--no-ff", "-m", "m", "samba/x")
    assert run(vcs.begin_merge("samba/x", "again")).status == "already"


def test_merge_conflict_lists_files_and_restores_the_checkout(repo: Path,
                                                              tmp_path: Path) -> None:
    vcs = make_vcs(repo, tmp_path)
    git(repo, "checkout", "-q", "-b", "samba/x")
    commit_file(repo, "a.txt", "branch\n", "branch change")
    git(repo, "checkout", "-q", "main")
    commit_file(repo, "a.txt", "main\n", "main change")
    head = git(repo, "rev-parse", "HEAD")
    attempt = run(vcs.begin_merge("samba/x", "Merge x"))
    assert (attempt.status, attempt.detail) == ("conflict", "a.txt")
    assert git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "status", "--porcelain", "--untracked-files=no") == ""
    assert (repo / "a.txt").read_text() == "main\n"


def test_abort_merge_undoes_a_pending_merge_even_with_a_dirty_tracked_file(
        repo: Path, tmp_path: Path) -> None:
    vcs = make_vcs(repo, tmp_path)
    make_branch(repo, "samba/x", "b.txt", "b\n")
    head = git(repo, "rev-parse", "HEAD")
    attempt = run(vcs.begin_merge("samba/x", "Merge x"))
    assert attempt.status == "pending" and (repo / "b.txt").exists()
    (repo / "a.txt").write_text("validation scribbled here\n")  # a validation touching a tracked file
    run(vcs.abort_merge(attempt.restore_point))
    assert git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "status", "--porcelain", "--untracked-files=no") == ""
    assert not (repo / "b.txt").exists() and (repo / "a.txt").read_text() == "one\n"
    with pytest.raises(subprocess.CalledProcessError):
        git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD")


def test_commit_merge_failure_undoes_the_merge(repo: Path, tmp_path: Path) -> None:
    vcs = make_vcs(repo, tmp_path)
    make_branch(repo, "samba/x", "b.txt", "b\n")
    head = git(repo, "rev-parse", "HEAD")
    attempt = run(vcs.begin_merge("samba/x", "Merge x"))
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho rejected by hook\nexit 1\n")
    hook.chmod(0o755)
    done = run(vcs.commit_merge(attempt.restore_point))
    assert not done.ok and "rejected by hook" in done.detail
    assert git(repo, "rev-parse", "HEAD") == head
    assert not (repo / "b.txt").exists()


# ---- validator --------------------------------------------------------------------------


def make_validator(tmp_path: Path, command: str, timeout_s: float = 30,
                   tail_lines: int = 5) -> ShellValidator:
    return ShellValidator(Validation(command, timeout_s, tail_lines, SH), tmp_path / "runs")


def test_validator_pass_writes_the_full_log(tmp_path: Path) -> None:
    work = tmp_path / "w"
    work.mkdir()
    res = run(make_validator(tmp_path, "pwd; echo done").run(str(work), "t-1/v.log"))
    assert res.ok and res.code == 0 and not res.timed_out
    assert res.output.splitlines()[-1] == "done"
    assert res.tail_lines == 5 and res.timeout_s == 30
    assert res.log_location == str(tmp_path / "runs" / "t-1" / "v.log")
    assert (tmp_path / "runs" / "t-1" / "v.log").read_text() == res.output
    assert work.name in res.output  # ran in the given location


def test_validator_failure_and_timeout(tmp_path: Path) -> None:
    res = run(make_validator(tmp_path, "echo bad; exit 2").run(str(tmp_path), "f.log"))
    assert not res.ok and res.code == 2 and res.output == "bad\n"
    slow = run(make_validator(tmp_path, "sleep 30", timeout_s=0.3).run(str(tmp_path), "s.log"))
    assert slow.timed_out and not slow.ok and slow.code is None
    assert (tmp_path / "runs" / "s.log").exists()


# ---- journal ----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_samba_logger() -> Iterator[None]:
    yield
    logger = logging.getLogger("samba")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def test_log_journal_writes_the_kv_format_to_samba_log(tmp_path: Path) -> None:
    samba_dir = tmp_path / ".samba"
    journal = LogJournal(samba_dir)
    journal.debug("tick", n=1)
    journal.info("started", repo="/a b", skipped=None)
    journal.warning("attempt_failed", task="t-1", error="x=y")
    try:
        raise RuntimeError("kaput")
    except RuntimeError:
        journal.exception("worker_crashed", task="t-1")
    journal.close()
    lines = (samba_dir / "samba.log").read_text().splitlines()
    assert lines[0].endswith(" DEBUG event=tick n=1")
    assert lines[1].endswith(' INFO event=started repo="/a b"')
    assert lines[2].endswith(' WARNING event=attempt_failed task=t-1 error="x=y"')
    assert lines[3].endswith(" ERROR event=worker_crashed task=t-1")
    assert lines[4] == "Traceback (most recent call last):"
    assert lines[-1] == "RuntimeError: kaput"
    assert lines[0][:4].isdigit()  # starts with the asctime stamp


def test_log_journal_sends_info_but_not_debug_to_stderr(tmp_path: Path,
                                                        capsys: pytest.CaptureFixture[str]) -> None:
    journal = LogJournal(tmp_path / ".samba")
    journal.debug("quiet")
    journal.info("loud")
    journal.close()
    err = capsys.readouterr().err
    assert "event=loud" in err and "event=quiet" not in err


def test_null_journal_writes_nothing(tmp_path: Path) -> None:
    journal = NullJournal()
    journal.info("x")
    journal.exception("y")
    assert list(tmp_path.iterdir()) == [] and logging.getLogger("samba").handlers == []
