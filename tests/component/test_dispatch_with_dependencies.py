"""`Tick` dispatch when tasks depend on others (spec: orchestrator, Dependencies), over the fakes."""

from __future__ import annotations

import asyncio

from test_tick import Rig

from samba.domain.task_id import TaskId


def tick(rig: Rig, times: int = 1) -> None:
    for _ in range(times):
        asyncio.run(rig.tick.run())


def test_a_todo_dependency_runs_first_and_its_dependent_waits() -> None:
    rig = Rig()
    rig.add("t1", deps=("dep",), priority=1)  # higher priority than its dependency
    rig.add("dep", priority=5)
    tick(rig)
    assert rig.spawned == ["dep"]
    assert rig.status("t1") == "work-todo"


def test_an_unknown_dependency_holds_the_task_and_is_journaled_once() -> None:
    rig = Rig()
    rig.add("t1", deps=("typo-id",))
    tick(rig, times=3)
    assert rig.spawned == []
    assert rig.status("t1") == "work-todo"
    warnings = [(e, f) for lvl, e, f in rig.journal.records if lvl == "warning"]
    assert warnings == [("unknown_dependency", {"task": TaskId("t1"), "dependency": "typo-id"})]


def test_a_dependent_retried_by_hand_while_its_dependency_is_discarded_goes_back_to_stuck() -> None:
    rig = Rig()
    rig.add("dep", status="discarded")
    rig.add("t1", deps=("dep",))
    tick(rig)
    assert rig.status("t1") == "stuck"
    rig.tasks.hand_move(TaskId("t1"), "work-todo")  # task.retry by hand, dependency still discarded
    tick(rig)
    assert rig.status("t1") == "stuck"
    assert rig.spawned == []
    log = rig.tasks.records[TaskId("t1")].log
    assert any("task.retry: stuck -> work-todo: observed hand move" in line for line in log), log
    assert sum("dependency was discarded" in line for line in log) == 2, log
