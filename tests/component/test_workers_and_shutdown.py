"""A live worker stopped, discarded or shut down, and exit when idle: the orchestrator over fakes.

The agent here never answers until it is cancelled, so a task stays in `work-running` with a live
worker, as it does while a real `claude` runs (spec: orchestrator, Workers; states, task.stop).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

from fake_agent import FakeAgentRunner
from fake_journal import FakeJournal
from fake_tasks import FakeTasks
from fake_terminal import FakeLock, FakeTerminal
from fake_validator import FakeValidator, passing
from fake_vcs import FakeVcs
from test_app_run_task import Clock, Ids, make_config

from samba.app.change_state import ChangeState
from samba.app.guard import Guard
from samba.app.machine import Machine
from samba.app.results import Done
from samba.domain.agent import AgentReport, AgentRequest, Readiness
from samba.domain.settings import Config
from samba.domain.states import State
from samba.domain.task import Task
from samba.domain.task_id import TaskId
from samba.entrypoints.orchestrator import Orchestrator

T1 = TaskId("t1")


class HangingAgent:
    """An `AgentRunner` whose turn lasts until the worker is cancelled."""

    def __init__(self) -> None:
        self.requests: list[AgentRequest] = []
        self.started = asyncio.Event()

    async def run(self, request: AgentRequest) -> AgentReport:
        self.requests.append(request)
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def ready(self) -> Readiness:
        return Readiness(ok=True)


class Rig:
    def __init__(self, agent: HangingAgent | FakeAgentRunner | None = None,
                 config: Config | None = None) -> None:
        self.config = config or make_config()
        self.clock, self.tasks, self.journal = Clock(), FakeTasks(), FakeJournal()
        self.vcs, self.lock = FakeVcs(), FakeLock()
        self.agent = agent or HangingAgent()
        self.orch = Orchestrator(self.config, self.clock, Ids(), self.agent, self.tasks, self.vcs,
                                 FakeValidator(passing("ok")), self.lock, self.journal)
        machine = Machine(self.tasks, self.clock, self.journal,
                          Guard(self.config.policy.require_plan, self.tasks))
        self.change = ChangeState(self.tasks, machine, FakeTerminal(interactive=False), self.lock)

    def add(self, tid: str, status: State = "work-todo", deps: tuple[str, ...] = ()) -> None:
        task = Task.new(TaskId(tid), tid, "", 3, tuple(TaskId(d) for d in deps), status, self.clock)
        task.queued_at = 0.0
        self.tasks.create(task)

    def task(self, tid: str = "t1") -> Task:
        return self.tasks.records[TaskId(tid)]

    async def start_t1(self) -> None:
        """Dispatch t1 and wait until its agent is mid-turn."""
        assert isinstance(self.agent, HangingAgent)
        self.add("t1")
        await self.orch.startup()
        await self.orch.tick()
        await asyncio.wait_for(self.agent.started.wait(), 1.0)
        assert self.task().status == "work-running"

    def removed(self) -> list[str]:
        return [c[1] for c in self.vcs.calls if c[0] == "remove_workspace"]


def test_shutdown_returns_a_running_task_to_its_stages_todo_folder() -> None:
    async def go(rig: Rig) -> None:
        await rig.start_t1()
        await rig.orch.workers.shutdown()

    rig = Rig()
    asyncio.run(go(rig))
    assert rig.task().status == "work-todo"
    assert any("stopped by shutdown" in line for line in rig.task().log)
    assert rig.removed() == []  # the workspace is kept for the next run


def test_stopping_a_running_task_cancels_its_worker_and_it_stays_stuck() -> None:
    async def go(rig: Rig) -> None:
        await rig.start_t1()
        assert isinstance(rig.change.run("t1", "task.stop", "task.stop"), Done)
        await rig.orch.tick()  # reconcile: the worker of a moved task is cancelled
        await rig.orch.workers.wait_all()
        await rig.orch.tick()  # nothing is dispatched again

    rig = Rig()
    asyncio.run(go(rig))
    task = rig.task()
    assert (task.status, task.blocked_cause, task.last_stage) == ("stuck", "stopped", "work")
    assert isinstance(rig.agent, HangingAgent) and len(rig.agent.requests) == 1
    assert rig.orch.running == {}
    assert rig.removed() == []  # a stuck task keeps its workspace
    assert isinstance(rig.change.run("t1", "task.retry", "task.retry"), Done)
    assert rig.task().status == "work-todo"


def test_discarding_a_running_task_cancels_it_and_removes_its_workspace_only() -> None:
    before: list[str] = []

    async def go(rig: Rig) -> None:
        await rig.start_t1()
        before.extend(c[0] for c in rig.vcs.calls)
        assert isinstance(rig.change.run("t1", "task.discard", "task.discard",
                                         confirm_plan="Discard task {id}", yes=True), Done)
        await rig.orch.tick()
        await rig.orch.workers.wait_all()

    rig = Rig()
    asyncio.run(go(rig))
    assert rig.task().status == "discarded"
    assert rig.removed() == ["t1"]
    # Only the worktree goes: the port has no way to delete a branch, and nothing else is called.
    assert [c[0] for c in rig.vcs.calls][len(before):] == ["remove_workspace"]
    assert rig.journal.events("info").count("stopped") == 1


def test_exit_when_idle_returns_while_a_task_still_waits_on_its_dependency() -> None:
    agent = FakeAgentRunner([AgentReport(outcome="done", summary="built")])
    config = make_config()
    rig = Rig(agent, replace(config, policy=replace(config.policy, poll_interval_s=0.01)))
    rig.add("dep", status="work-review")  # never finishes without a human
    rig.add("t1", deps=("dep",))
    rig.add("t2")
    asyncio.run(asyncio.wait_for(rig.orch.run(exit_when_idle=True), 2.0))
    assert rig.task("t2").status == "work-review"
    assert rig.task("t1").status == "work-todo"
    assert "idle_exit" in rig.journal.events("info")
