"""What the state-changing commands tell the person: retry hints, the discard prompt (spec: cli)."""

from __future__ import annotations

import pytest
from fake_journal import FakeJournal
from fake_tasks import FakeTasks
from fake_terminal import FakeLock, FakeTerminal
from test_scenarios import FakeClock

from samba.app.change_state import ChangeState, retry_hint
from samba.app.machine import Machine
from samba.app.results import Done
from samba.domain.states import State
from samba.domain.task import Task
from samba.domain.task_id import TaskId

CLOCK = FakeClock(100.0)


def rig(*tasks: tuple[str, State, dict[str, object]],
        terminal: FakeTerminal | None = None) -> tuple[FakeTasks, ChangeState, FakeTerminal]:
    store = FakeTasks()
    for tid, status, fields in tasks:
        task = Task.new(TaskId(tid), tid, "", 3, (), status, CLOCK)
        for key, value in fields.items():
            setattr(task, key, value)
        store.create(task)
    term = terminal or FakeTerminal(interactive=False)
    machine = Machine(store, CLOCK, FakeJournal())
    return store, ChangeState(store, machine, term, FakeLock()), term


@pytest.mark.parametrize("cause, names", [("budget", "WORKFLOW.md"),
                                          ("dependency_discarded", "depends_on"),
                                          ("dependency_cycle", "depends_on")])
def test_retry_hints_name_what_to_fix_first(cause: str, names: str) -> None:
    hint = retry_hint(cause)
    assert hint is not None and names in hint and hint.startswith("hint: ")


@pytest.mark.parametrize("cause", ["stopped", "gave_up", None])
def test_other_causes_have_no_hint(cause: str | None) -> None:
    assert retry_hint(cause) is None


def test_a_retry_with_a_hint_still_moves_the_task_and_prints_the_hint() -> None:
    store, change, _ = rig(("t1", "stuck", {"blocked_cause": "budget", "last_stage": "work"}))
    res = change.run("t1", "task.retry", "task.retry", hints=True)
    assert isinstance(res, Done)
    assert res.notes == (retry_hint("budget"),)
    task = store.records[TaskId("t1")]
    assert (task.status, task.blocked_cause) == ("work-todo", None)


def test_retrying_a_stopped_task_prints_no_hint_and_clears_the_cause() -> None:
    store, change, _ = rig(("t1", "stuck", {"blocked_cause": "stopped", "last_stage": "plan"}))
    res = change.run("t1", "task.retry", "task.retry", hints=True)
    assert isinstance(res, Done) and res.notes == ()
    task = store.records[TaskId("t1")]
    assert (task.status, task.blocked_cause) == ("plan-todo", None)


def test_the_discard_prompt_names_the_full_id_resolved_from_a_prefix() -> None:
    terminal = FakeTerminal(interactive=True, lines=["y"])
    store, change, _ = rig(("feature-cache-layer", "work-todo", {}), terminal=terminal)
    res = change.run("feature-c", "task.discard", "task.discard",
                     confirm_plan="Discard task {id}")
    assert isinstance(res, Done)
    assert len(terminal.prompts) == 1 and "feature-cache-layer" in terminal.prompts[0]
    assert store.records[TaskId("feature-cache-layer")].status == "discarded"
