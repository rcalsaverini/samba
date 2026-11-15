"""`Startup` over the fakes, no orchestrator and no loop of its own (`asyncio.run` only drives the call)."""

from __future__ import annotations

import asyncio

import pytest
from fake_agent import FakeAgentRunner
from fake_clock import FakeClock
from fake_journal import FakeJournal
from fake_tasks import FakeTasks
from fake_vcs import FakeVcs

from samba.app.guard import Guard
from samba.app.machine import Machine
from samba.app.startup import Startup, StartupError
from samba.domain.agent import Readiness
from samba.app.ports import StoreError
from samba.domain.validation import NO_VALIDATION_WARNING
from samba.domain.states import State
from samba.domain.task import Task
from samba.domain.task_id import TaskId


class BrokenTasks(FakeTasks):
    def prepare(self) -> None:
        raise StoreError("cannot create the task folders")


class Rig:
    def __init__(self, *, tasks: FakeTasks | None = None, vcs: FakeVcs | None = None,
                 readiness: Readiness | None = None, warnings: list[str] | None = None) -> None:
        self.tasks = tasks or FakeTasks()
        self.vcs = vcs or FakeVcs()
        self.journal = FakeJournal()
        self.clock = FakeClock()
        machine = Machine(self.tasks, self.clock, self.journal, Guard(False, self.tasks))
        self.startup = Startup(warnings or [], self.tasks, self.vcs, FakeAgentRunner([], readiness),
                               machine, self.journal)

    def add(self, task_id: str, status: State) -> None:
        self.tasks.create(Task.new(TaskId(task_id), task_id, "", None, (), status, self.clock.now()))


def test_a_store_error_becomes_a_startup_error() -> None:
    rig = Rig(tasks=BrokenTasks())
    with pytest.raises(StartupError, match="cannot create the task folders"):
        asyncio.run(rig.startup.run())


def test_a_repository_problem_becomes_a_startup_error() -> None:
    rig = Rig(vcs=FakeVcs(repo_problem="not a git repository"))
    with pytest.raises(StartupError, match="^not a git repository$"):
        asyncio.run(rig.startup.run())
    assert ("exclude_samba_dir",) not in rig.vcs.calls


def test_an_agent_that_is_not_logged_in_becomes_a_startup_error() -> None:
    rig = Rig(readiness=Readiness(ok=False, detail="no token"))
    with pytest.raises(StartupError) as err:
        asyncio.run(rig.startup.run())
    assert str(err.value) == ("claude auth status says not logged in; run `claude auth login`. "
                              "no token")


def test_config_warnings_are_journaled_at_warning_level() -> None:
    rig = Rig(warnings=["unknown key x", "unknown key y"])
    asyncio.run(rig.startup.run())
    assert [(lvl, f["message"]) for lvl, e, f in rig.journal.records if e == "config_warning"] == [
        ("warning", "unknown key x"), ("warning", "unknown key y")]


def test_the_missing_validate_command_warning_is_journaled_like_any_config_warning() -> None:
    rig = Rig(warnings=[NO_VALIDATION_WARNING])
    asyncio.run(rig.startup.run())
    assert [(lvl, f["message"]) for lvl, e, f in rig.journal.records if e == "config_warning"] == [
        ("warning", "validate.command is not set: Samba will accept work without running "
                    "validation")]


def test_the_samba_dir_is_excluded() -> None:
    rig = Rig()
    asyncio.run(rig.startup.run())
    assert rig.vcs.calls == [("exclude_samba_dir",)]


def test_running_tasks_are_recovered_to_their_todo_folders() -> None:
    rig = Rig()
    rig.add("p", "plan-running")
    rig.add("w", "work-running")
    rig.add("r", "work-review")
    asyncio.run(rig.startup.run())
    assert {str(i): rig.tasks.records[i].status for i in rig.tasks.records} == {
        "p": "plan-todo", "w": "work-todo", "r": "work-review"}
    for name in ("p", "w"):
        assert any("recovered at startup" in line for line in rig.tasks.records[TaskId(name)].log)
    assert [(f["task"], f["to"]) for _, e, f in rig.journal.records if e == "recovered"] == [
        ("p", "plan-todo"), ("w", "work-todo")]
