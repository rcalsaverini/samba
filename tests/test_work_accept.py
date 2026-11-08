"""Black-box tests for `work accept` (spec: cli). Must not import samba."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from conftest import Sandbox, git

IDENT: dict[str, Any] = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
         "GIT_COMMITTER_EMAIL": "t@t"}


def commit_file(cwd: Path, name: str, text: str, msg: str = "change") -> None:
    (cwd / name).write_text(text)
    git(cwd, "add", name)
    git(cwd, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", msg)


def accept_task(sb: Sandbox, task_id: str = "t1", state: str = "work-review",
                branch: bool = True, **workflow: Any) -> None:
    """A task in `state` whose branch `samba/<id>` has one commit adding `feature.txt`."""
    if workflow:
        sb.write_workflow(**workflow)
    sb.add_task(task_id, state=state, title="Add the feature")
    sb.write_sidecar(task_id, {"state": state, "branch": f"samba/{task_id}"})
    if branch:
        git(sb.repo, "checkout", "-q", "-b", f"samba/{task_id}")
        commit_file(sb.repo, "feature.txt", "feature\n", "add feature")
        git(sb.repo, "checkout", "-q", "main")


def head(sb: Sandbox, ref: str = "HEAD") -> str:
    return git(sb.repo, "rev-parse", ref)


def clean(sb: Sandbox) -> bool:
    return git(sb.repo, "status", "--porcelain", "--untracked-files=no") == ""


def merge_in_progress(sb: Sandbox) -> bool:
    return subprocess.run(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"], cwd=sb.repo,
                          capture_output=True).returncode == 0


def test_success(sb: Sandbox) -> None:
    accept_task(sb)
    before = head(sb)
    res = sb.run("work", "accept", "t1", "--yes", **IDENT)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == str(sb.tasks_dir / "done" / "t1.md")
    assert "no validate.command" in res.stderr
    assert sb.state_of("t1") == "done"
    assert len(git(sb.repo, "rev-list", "--parents", "-n1", "HEAD").split()) == 3  # two parents
    assert git(sb.repo, "rev-parse", "HEAD^1") == before
    assert "t1" in git(sb.repo, "log", "-1", "--format=%s")
    assert "Add the feature" in git(sb.repo, "log", "-1", "--format=%s")
    assert (sb.repo / "feature.txt").exists()
    assert sb.branch_exists("samba/t1")
    assert "work.accept: work-review -> done" in sb.log_section("t1")


def test_no_merge(sb: Sandbox) -> None:
    accept_task(sb, validate={"command": "touch ran.marker"})
    before = head(sb)
    res = sb.run("work", "accept", "t1", "--no-merge", "--yes", **IDENT)
    assert res.returncode == 0, res.stderr
    assert sb.state_of("t1") == "done"
    assert head(sb) == before
    assert not (sb.repo / "feature.txt").exists() and not (sb.repo / "ran.marker").exists()
    assert sb.branch_exists("samba/t1")


def test_dry_run(sb: Sandbox) -> None:
    accept_task(sb, validate={"command": "touch ran.marker"})
    before = head(sb)
    res = sb.run("work", "accept", "t1", "--dry-run", **IDENT)
    assert res.returncode == 0, res.stderr
    out = res.stdout + res.stderr
    assert "samba/t1" in out and "main" in out and "touch ran.marker" in out
    assert "1 commit" in out
    assert head(sb) == before and sb.state_of("t1") == "work-review"
    assert not (sb.repo / "ran.marker").exists()


def test_refuses_without_tty_and_yes(sb: Sandbox) -> None:
    accept_task(sb)
    before = head(sb)
    res = sb.run("work", "accept", "t1", **IDENT)
    assert res.returncode == 2
    assert "--yes" in res.stderr
    assert head(sb) == before and sb.state_of("t1") == "work-review"


def test_tty_prompt(sb: Sandbox) -> None:
    pty = pytest.importorskip("pty")
    import os

    from conftest import samba_cmd
    accept_task(sb)
    for answer, merged in ((b"n\n", False), (b"y\n", True)):
        master, slave = pty.openpty()
        proc = subprocess.Popen([*samba_cmd(), "work", "accept", "t1", "--repo", str(sb.repo)],
                                cwd=sb.repo, env=sb.env(**IDENT), stdin=slave, stdout=slave,
                                stderr=subprocess.PIPE)
        os.close(slave)
        os.write(master, answer)
        proc.wait(timeout=60)
        os.close(master)
        assert (proc.returncode == 0) == merged, proc.stderr.read() if proc.stderr else ""
        assert (sb.state_of("t1") == "done") == merged


def test_preflight_other_branch(sb: Sandbox) -> None:
    accept_task(sb)
    git(sb.repo, "checkout", "-q", "-b", "other")
    res = sb.run("work", "accept", "t1", "--yes", **IDENT)
    assert res.returncode == 1 and "main" in res.stderr
    assert sb.state_of("t1") == "work-review" and git(sb.repo, "branch", "--show-current") == "other"


def test_preflight_dirty_tracked(sb: Sandbox) -> None:
    accept_task(sb)
    (sb.repo / "README.md").write_text("modified\n")
    res = sb.run("work", "accept", "t1", "--yes", **IDENT)
    assert res.returncode == 1 and "uncommitted" in res.stderr
    assert sb.state_of("t1") == "work-review"
    assert (sb.repo / "README.md").read_text() == "modified\n"


def test_untracked_file_does_not_block(sb: Sandbox) -> None:
    accept_task(sb)
    (sb.repo / "scratch.txt").write_text("x\n")
    res = sb.run("work", "accept", "t1", "--yes", **IDENT)
    assert res.returncode == 0, res.stderr


def test_preflight_branch_missing(sb: Sandbox) -> None:
    accept_task(sb, branch=False)
    before = head(sb)
    res = sb.run("work", "accept", "t1", "--yes", **IDENT)
    assert res.returncode == 1 and "samba/t1" in res.stderr
    assert sb.state_of("t1") == "work-review" and head(sb) == before


@pytest.mark.parametrize("state", ["plan-review", "work-todo", "done", "stuck"])
def test_wrong_state(sb: Sandbox, state: str) -> None:
    accept_task(sb, state=state)
    before = head(sb)
    res = sb.run("work", "accept", "t1", "--yes", **IDENT)
    assert res.returncode == 1 and "Legal events" in res.stderr
    assert sb.state_of("t1") == state and head(sb) == before


def test_unknown_id(sb: Sandbox) -> None:
    res = sb.run("work", "accept", "nope", "--yes")
    assert res.returncode == 2


def test_conflict_aborted(sb: Sandbox) -> None:
    accept_task(sb)
    git(sb.repo, "checkout", "-q", "samba/t1")
    commit_file(sb.repo, "shared.txt", "branch side\n")
    git(sb.repo, "checkout", "-q", "main")
    commit_file(sb.repo, "shared.txt", "main side\n")
    before = head(sb)
    res = sb.run("work", "accept", "t1", "--yes", **IDENT)
    assert res.returncode == 1
    assert "shared.txt" in res.stderr
    assert head(sb) == before and not merge_in_progress(sb) and clean(sb)
    assert (sb.repo / "shared.txt").read_text() == "main side\n"
    assert sb.state_of("t1") == "work-review"
    assert "work.accept: merge failed" in sb.log_section("t1")


def moved_main(sb: Sandbox, command: str, **validate: Any) -> str:
    """Branch passes alone; main then gains old.txt (no textual conflict)."""
    accept_task(sb, validate={"command": command, **validate})
    commit_file(sb.repo, "old.txt", "old\n")
    return head(sb)


def test_validation_failure_after_merge(sb: Sandbox) -> None:
    before = moved_main(sb, "echo MARKER-OUTPUT; ! test -f old.txt")
    res = sb.run("work", "accept", "t1", "--yes", **IDENT)
    assert res.returncode == 1
    assert "MARKER-OUTPUT" in res.stderr
    assert head(sb) == before and clean(sb) and not merge_in_progress(sb)
    assert not (sb.repo / "feature.txt").exists()
    assert sb.state_of("t1") == "work-review"
    log = sb.log_section("t1")
    assert "validation failed after merge" in log and "MARKER-OUTPUT" in log
    assert sb.branch_exists("samba/t1")


def test_validation_passes_after_merge(sb: Sandbox) -> None:
    moved_main(sb, "test -f old.txt && test -f feature.txt")
    res = sb.run("work", "accept", "t1", "--yes", **IDENT)
    assert res.returncode == 0, res.stderr
    assert sb.state_of("t1") == "done"
    assert len(git(sb.repo, "rev-list", "--parents", "-n1", "HEAD").split()) == 3
    assert "validated" in sb.log_section("t1")


def test_no_validate(sb: Sandbox) -> None:
    moved_main(sb, "! test -f old.txt")
    res = sb.run("work", "accept", "t1", "--yes", "--no-validate", **IDENT)
    assert res.returncode == 0, res.stderr
    assert sb.state_of("t1") == "done" and (sb.repo / "feature.txt").exists()
    assert "validation skipped" in sb.log_section("t1")


def test_validation_runs_in_main_checkout(sb: Sandbox, tmp_path: Path) -> None:
    out = tmp_path / "pwd.txt"
    accept_task(sb, validate={"command": 'pwd > "$PWD_OUT" && test -f feature.txt'})
    res = sb.run("work", "accept", "t1", "--yes", PWD_OUT=str(out), **IDENT)
    assert res.returncode == 0, res.stderr
    assert Path(out.read_text().strip()).resolve() == sb.repo.resolve()


def test_validation_timeout(sb: Sandbox) -> None:
    before = moved_main(sb, "sleep 30", timeout_s=1)
    res = sb.run("work", "accept", "t1", "--yes", **IDENT)
    assert res.returncode == 1
    assert head(sb) == before and clean(sb) and not merge_in_progress(sb)
    assert sb.state_of("t1") == "work-review"
    assert "timed out" in sb.log_section("t1")


def test_hand_move_does_not_merge(sb: Sandbox) -> None:
    accept_task(sb)
    before = head(sb)
    sb.move("t1", "work-review", "done")
    assert head(sb) == before and not (sb.repo / "feature.txt").exists()
