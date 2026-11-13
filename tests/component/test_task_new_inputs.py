"""`task new` inputs: dependencies by flag and the questions asked on a terminal (spec: cli)."""

from __future__ import annotations

from fake_tasks import FakeTasks
from fake_terminal import FakeTerminal
from test_scenarios import FakeClock

from samba.app.create_task import CreateTask
from samba.app.results import Done, Refused
from samba.domain.task import Task
from samba.domain.task_id import TaskId

CLOCK = FakeClock(100.0)


def store(*ids: str) -> FakeTasks:
    tasks = FakeTasks()
    for tid in ids:
        tasks.create(Task.new(TaskId(tid), tid, "", 3, (), "work-todo", CLOCK))
    return tasks


def test_dependencies_are_comma_separated_ids_or_prefixes_ignoring_blanks() -> None:
    tasks = store("alpha-one", "beta-two")
    res = CreateTask(tasks, FakeTerminal(interactive=False), CLOCK).run(
        "New thing", None, "alpha, , beta-two,", 3, False)
    assert isinstance(res, Done)
    assert tasks.records[TaskId("new-thing")].depends_on == (TaskId("alpha-one"),
                                                             TaskId("beta-two"))


def test_an_ambiguous_dependency_prefix_by_flag_creates_nothing() -> None:
    tasks = store("alpha-one", "alpha-two")
    res = CreateTask(tasks, FakeTerminal(interactive=False), CLOCK).run(
        "New thing", None, "alpha", 3, False)
    assert isinstance(res, Refused) and res.kind == "usage"
    text = "\n".join(res.messages)
    assert "alpha-one" in text and "alpha-two" in text
    assert sorted(tasks.records) == ["alpha-one", "alpha-two"]


def test_on_a_terminal_only_the_missing_fields_are_asked() -> None:
    terminal = FakeTerminal(interactive=True, lines=["", "n"])  # no dependencies, no plan
    tasks = store()
    res = CreateTask(tasks, terminal, CLOCK).run("Given title", "given body", None, 3, False)
    assert isinstance(res, Done)
    assert not any("Title" in p or "Description" in p for p in terminal.prompts)
    assert len(terminal.prompts) == 2  # dependencies, then plan first
    task = tasks.records[TaskId("given-title")]
    assert task.status == "work-todo" and task.body.strip() == "given body"


def test_on_a_terminal_flags_for_dependencies_skip_that_question_too() -> None:
    terminal = FakeTerminal(interactive=True, lines=["y"])
    tasks = store("alpha-one")
    res = CreateTask(tasks, terminal, CLOCK).run("Given title", "body", "alpha", 3, False)
    assert isinstance(res, Done)
    assert len(terminal.prompts) == 1 and "Plan" in terminal.prompts[0]
    assert tasks.records[TaskId("given-title")].status == "plan-todo"
