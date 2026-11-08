"""Black-box tests for task dependencies (spec: orchestrator, Dependencies). Must not import the samba package."""

from __future__ import annotations

import time

import pytest
from conftest import Sandbox, stop, wait_for


@pytest.mark.parametrize("dep_folder", ["plan-todo", "plan-review", "work-review", "question",
                                        "stuck"])
def test_task_waits_while_dependency_is_not_done(sb: Sandbox, dep_folder: str) -> None:
    sb.add_task("dep", state=dep_folder)
    sb.add_task("t1", depends_on=["dep"])
    sb.run_idle()
    assert sb.state_of("t1") == "work-todo"
    assert sb.calls("t1") == []
    assert sb.state_of("t1") == "work-todo"


def test_task_runs_once_dependency_is_done(sb: Sandbox) -> None:
    sb.add_task("dep", state="work-review")
    sb.write_sidecar("dep", {"state": "work-review"})
    sb.add_task("t1", depends_on=["dep"])
    proc = sb.popen("run")  # not --exit-when-idle: a held task would let that exit at once
    try:
        wait_for(lambda: "event=started" in sb.log_text())
        time.sleep(0.5)
        assert sb.calls("t1") == []
        sb.move("dep", "work-review", "done")
        wait_for(lambda: sb.state_of("t1") == "work-review")
    finally:
        stop(proc)
    assert len(sb.calls("t1")) == 1


def test_dependency_already_done_runs_immediately(sb: Sandbox) -> None:
    sb.add_task("dep", state="done")
    sb.add_task("t1", depends_on=["dep"])
    sb.run_idle()
    assert sb.state_of("t1") == "work-review"


def test_all_dependencies_must_be_done(sb: Sandbox) -> None:
    sb.add_task("a", state="done")
    sb.add_task("b", state="work-review")
    sb.add_task("t1", depends_on=["a", "b"])
    sb.run_idle()
    assert sb.state_of("t1") == "work-todo"
    assert sb.calls("t1") == []
    sb.move("b", "work-review", "done")
    sb.run_idle()
    assert sb.state_of("t1") == "work-review"


def test_dependency_in_the_todo_folder_runs_first(sb: Sandbox) -> None:
    sb.add_task("dep")
    sb.add_task("t1", depends_on=["dep"])
    sb.run_idle()
    assert sb.state_of("dep") == "work-review"
    assert sb.state_of("t1") == "work-todo"  # dep is in review, not done
    assert sb.calls("t1") == []


def test_unknown_dependency_stays_waiting_with_a_warning(sb: Sandbox) -> None:
    sb.add_task("t1", depends_on=["typo-id"])
    sb.run_idle()
    assert sb.state_of("t1") == "work-todo"
    assert sb.calls("t1") == []
    assert "unknown_dependency" in sb.log_text()
    assert "typo-id" in sb.log_text()
    assert sb.log_text().count("event=unknown_dependency") == 1


def test_discarded_dependency_sends_dependent_to_stuck(sb: Sandbox) -> None:
    sb.add_task("dep", state="discarded")
    sb.add_task("t1", depends_on=["dep"])
    sb.run_idle()
    assert sb.state_of("t1") == "stuck"
    assert sb.sidecar("t1")["blocked_cause"] == "dependency_discarded"
    assert sb.calls("t1") == []
    assert "dependency_discarded: work-todo -> stuck" in sb.log_section("t1")


def test_two_task_cycle_sends_both_to_stuck(sb: Sandbox) -> None:
    sb.add_task("a", depends_on=["b"])
    sb.add_task("b", depends_on=["a"])
    sb.run_idle()
    for tid in ("a", "b"):
        assert sb.state_of(tid) == "stuck"
        assert sb.sidecar(tid)["blocked_cause"] == "dependency_cycle"
        assert sb.calls(tid) == []


def test_self_dependency_is_a_cycle(sb: Sandbox) -> None:
    sb.add_task("a", depends_on=["a"])
    sb.run_idle()
    assert sb.state_of("a") == "stuck"
    assert sb.sidecar("a")["blocked_cause"] == "dependency_cycle"


def test_dependencies_gate_planning(sb: Sandbox) -> None:
    sb.add_task("dep", state="question")
    sb.add_task("t1", state="plan-todo", depends_on=["dep"])
    sb.run_idle()
    assert sb.state_of("t1") == "plan-todo"
    assert sb.calls("t1") == []


def test_dependencies_gate_the_require_plan_route(sb: Sandbox) -> None:
    sb.write_workflow(planning={"require_plan": True})
    sb.add_task("dep", state="question")
    sb.add_task("t1", depends_on=["dep"])
    sb.run_idle()
    assert sb.state_of("t1") == "work-todo"
    assert sb.calls("t1") == []


def test_status_shows_waiting_on(sb: Sandbox) -> None:
    sb.add_task("a", state="question")
    sb.add_task("b", state="work-review")
    sb.add_task("t1", depends_on=["a", "b"])
    out = sb.run("task", "list").stdout
    line = next(ln for ln in out.splitlines() if ln.startswith("t1"))
    assert "waiting on a, b" in line


def test_waiting_task_does_not_hang_exit_when_idle(sb: Sandbox) -> None:
    sb.add_task("dep", state="question")
    sb.add_task("t1", depends_on=["dep"])
    sb.add_task("other")
    sb.run_idle(timeout=30)
    assert sb.state_of("other") == "work-review"
    assert sb.state_of("t1") == "work-todo"


def test_stuck_dependent_returns_with_a_hand_move_and_is_checked_again(sb: Sandbox) -> None:
    sb.add_task("dep", state="discarded")
    sb.add_task("t1", depends_on=["dep"])
    sb.run_idle()
    assert sb.state_of("t1") == "stuck"
    sb.move("t1", "stuck", "work-todo")  # task.retry, but the dependency is still discarded
    sb.run_idle()
    assert sb.state_of("t1") == "stuck"
    assert sb.calls("t1") == []


def test_malformed_depends_on_is_ignored(sb: Sandbox) -> None:
    p = sb.add_task("t1")
    p.write_text("---\ndepends_on: just-a-string\n---\n# t1\n\nbody\n")
    sb.run_idle()
    assert sb.state_of("t1") == "work-review"
