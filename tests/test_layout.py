"""Black-box tests for the stage x status folder layout (SPEC §2, §4). No symphony import."""

from __future__ import annotations

import signal
import subprocess
import time
from collections.abc import Callable

import pytest
from conftest import Sandbox

OLD_FOLDERS = ("plan", "todo", "running", "review", "blocked")


def wait_for(cond: Callable[[], bool], timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while not cond() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert cond()


def stop(proc: subprocess.Popen[str]) -> None:
    proc.send_signal(signal.SIGINT)
    proc.wait(timeout=15)


# ---- question versus stuck -----------------------------------------------------------------


def test_agent_blocked_goes_to_question(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "blocked"})
    sb.run_idle()
    assert sb.state_of("t1") == "question"
    side = sb.sidecar("t1")
    assert side["blocked_cause"] == "question"
    assert side["last_stage"] == "work"
    assert side["last_outcome"] == "blocked"


def test_budget_goes_to_stuck(sb: Sandbox) -> None:
    sb.write_workflow(max_cost_usd_per_task=0.15)
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "continue", "cost": 0.2})
    sb.run_idle()
    assert sb.state_of("t1") == "stuck"
    assert sb.sidecar("t1")["blocked_cause"] == "budget"


def test_giving_up_goes_to_stuck_for_both_stages(sb: Sandbox) -> None:
    sb.write_workflow(max_attempts=1, reflect_on_give_up=False)
    sb.add_task("w")
    sb.add_task("p", state="plan-todo")
    sb.steps("w", {"is_error": True})
    sb.steps("p", {"is_error": True})
    sb.run_idle()
    for tid, stage in (("w", "work"), ("p", "plan")):
        assert sb.state_of(tid) == "stuck"
        side = sb.sidecar(tid)
        assert side["blocked_cause"] == "gave_up"
        assert side["last_stage"] == stage


def test_answered_question_clears_cause_and_resets_attempts(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "blocked"}, {"outcome": "done"})
    sb.run_idle()
    assert sb.sidecar("t1")["blocked_cause"] == "question"
    (sb.tasks_dir / "question" / "t1.md").rename(sb.tasks_dir / "work-todo" / "t1.md")
    sb.run_idle()
    assert sb.state_of("t1") == "work-review"
    assert sb.sidecar("t1")["blocked_cause"] is None


def test_status_shows_cause_for_question_and_stuck(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "blocked"})
    sb.run_idle()
    out = sb.run("task", "list").stdout
    assert "question (question)" in out


# ---- done versus discarded -----------------------------------------------------------------


def test_done_and_discarded_remove_worktree_and_keep_branch(sb: Sandbox) -> None:
    for tid in ("a", "b"):
        sb.add_task(tid)
        sb.steps(tid, {"outcome": "done", "commit": True})
    sb.run_idle()
    for tid in ("a", "b"):
        assert sb.state_of(tid) == "work-review"
        assert sb.worktree(tid).is_dir()
    (sb.tasks_dir / "work-review" / "a.md").rename(sb.tasks_dir / "done" / "a.md")
    (sb.tasks_dir / "work-review" / "b.md").rename(sb.tasks_dir / "discarded" / "b.md")
    sb.run_idle()
    assert sb.state_of("a") == "done"
    assert sb.state_of("b") == "discarded"
    for tid in ("a", "b"):
        assert not sb.worktree(tid).exists()
        assert sb.branch_exists(f"symphony/{tid}")


def test_moving_running_task_to_discarded_stops_agent(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "done", "hang": 30})
    proc = sb.popen("run", "--exit-when-idle")
    running = sb.tasks_dir / "work-running" / "t1.md"
    wait_for(lambda: running.exists() and bool(sb.calls("t1")))
    running.rename(sb.tasks_dir / "discarded" / "t1.md")
    assert proc.wait(timeout=15) == 0
    assert sb.state_of("t1") == "discarded"
    assert not sb.worktree("t1").exists()
    assert sb.branch_exists("symphony/t1")


# ---- last_stage routing --------------------------------------------------------------------


@pytest.mark.parametrize("folder,stage", [("plan-todo", "plan"), ("work-todo", "work")])
def test_failed_attempt_retries_in_its_own_stage(sb: Sandbox, folder: str, stage: str) -> None:
    sb.write_workflow(retry_base_s=60, max_retry_backoff_s=60)
    sb.add_task("t1", state=folder)
    sb.steps("t1", {"is_error": True})
    proc = sb.popen("run", "--exit-when-idle")
    try:
        wait_for(lambda: sb.state_of("t1") == folder and bool(sb.calls("t1")))
        wait_for(lambda: sb.sidecar("t1").get("attempts") == 1)
        assert sb.sidecar("t1")["last_stage"] == stage
    finally:
        stop(proc)
    assert sb.state_of("t1") == folder


@pytest.mark.parametrize("folder,running,stage", [("plan-todo", "plan-running", "plan"),
                                                  ("work-todo", "work-running", "work")])
def test_shutdown_returns_task_to_its_stage(sb: Sandbox, folder: str, running: str,
                                            stage: str) -> None:
    sb.add_task("t1", state=folder)
    sb.steps("t1", {"hang": 30})
    proc = sb.popen("run", "--exit-when-idle")
    wait_for(lambda: (sb.tasks_dir / running / "t1.md").exists() and bool(sb.calls("t1")))
    assert sb.sidecar("t1")["last_stage"] == stage
    stop(proc)
    assert sb.state_of("t1") == folder


def test_startup_recovers_each_running_folder_to_its_todo(sb: Sandbox) -> None:
    sb.add_task("p", state="plan-running")
    sb.add_task("w", state="work-running")
    sb.steps("p", {"plan": "recovered"})
    sb.steps("w", {"outcome": "done"})
    sb.run_idle()
    assert sb.state_of("p") == "plan-review"
    assert sb.state_of("w") == "work-review"


# ---- old layout ----------------------------------------------------------------------------


@pytest.mark.parametrize("old", OLD_FOLDERS)
def test_old_folder_with_tasks_refuses_to_start(sb: Sandbox, old: str) -> None:
    sb.add_task("keep", state=old)
    sb.add_task("t1")
    res = sb.run("run", "--exit-when-idle")
    assert res.returncode != 0
    assert old in res.stderr and "mv " in res.stderr
    assert (sb.tasks_dir / old / "keep.md").exists()
    assert sb.state_of("t1") == "work-todo"
    assert sb.calls("t1") == []


def test_empty_old_folders_do_not_block(sb: Sandbox) -> None:
    for old in OLD_FOLDERS:
        (sb.tasks_dir / old).mkdir(parents=True)
    sb.add_task("t1")
    sb.run_idle()
    assert sb.state_of("t1") == "work-review"


def test_old_sidecar_still_loads(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.write_sidecar("t1", {"phase": "execute", "last_outcome": "approved", "attempts": 0})
    sb.run_idle()
    assert sb.state_of("t1") == "work-review"
    assert "phase" not in sb.sidecar("t1")
