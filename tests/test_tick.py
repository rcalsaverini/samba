"""The `Tick` use case in-process: fake store, clock, lock and workspaces (no adapters)."""

from __future__ import annotations

import asyncio

from fake_tasks import FakeTasks
from fake_terminal import FakeLock
from test_scenarios import FakeClock

from samba.app.machine import Machine
from samba.app.tick import Notes, Running, Tick
from samba.domain.deps import deps_snapshot, evaluate
from samba.domain.states import State
from samba.domain.task import Task
from samba.domain.task_id import TaskId
from samba.ports import WorkspaceError


class FakeWorkspaces:
    def __init__(self, ids: list[str] | None = None, fail: bool = False) -> None:
        self.ids = list(ids or [])
        self.fail = fail
        self.removed: list[str] = []

    def existing_ids(self) -> list[str]:
        return list(self.ids)

    async def remove(self, task_id: str) -> None:
        if self.fail:
            raise WorkspaceError("boom")
        self.removed.append(task_id)


class Rig:
    def __init__(self, max_concurrent: int = 5, lock: FakeLock | None = None,
                 workspaces: FakeWorkspaces | None = None) -> None:
        self.tasks = FakeTasks()
        self.clock = FakeClock(100.0)
        self.running: dict[str, Running] = {}
        self.spawned: list[str] = []
        self.workspaces = workspaces or FakeWorkspaces()
        machine = Machine(self.tasks, self.clock, self.guard)
        self.notes = Notes(self.tasks, self.running)
        self.tick = Tick(self.tasks, self.clock, lock or FakeLock(), self.workspaces, machine,
                         max_concurrent, self.running, self.notes, self.spawn)

    def guard(self, name: str, task: Task) -> bool:
        return name == "deps_met" and evaluate(
            deps_snapshot(task, self.tasks.get), task.id).kind == "ready"

    def spawn(self, task: Task) -> None:
        self.spawned.append(task.id)
        self.running[task.id] = Running(asyncio.ensure_future(asyncio.sleep(10)), 0.0,
                                        "work-running")

    def add(self, tid: str, status: State = "work-todo", priority: int | None = 3,
            deps: tuple[str, ...] = (), queued_at: float | None = None,
            not_before: float | None = None) -> Task:
        task = Task.new(TaskId(tid), tid, "", priority, tuple(TaskId(d) for d in deps), status,
                        self.clock)
        task.queued_at = queued_at if queued_at is not None else 0.0
        task.not_before = not_before
        self.tasks.create(task)
        return task

    def status(self, tid: str) -> State:
        return self.tasks.records[TaskId(tid)].status


def test_dispatch_orders_by_priority_then_queued_at_then_id() -> None:
    rig = Rig()
    rig.add("c", priority=None)
    rig.add("b", priority=2, queued_at=5.0)
    rig.add("a", priority=2, queued_at=5.0)
    rig.add("z", priority=1, queued_at=9.0)
    rig.add("y", priority=2, queued_at=1.0)
    asyncio.run(rig.tick.run())
    assert rig.spawned == ["z", "y", "a", "b", "c"]
    assert rig.status("z") == "work-running"


def test_dispatch_respects_the_concurrency_cap_and_not_before() -> None:
    rig = Rig(max_concurrent=1)
    rig.add("late", priority=1, not_before=500.0)
    rig.add("a", priority=2)
    rig.add("b", priority=3)
    asyncio.run(rig.tick.run())
    assert rig.spawned == ["a"]
    assert rig.status("late") == "work-todo" and rig.status("b") == "work-todo"


def test_a_waiting_dependency_holds_the_task() -> None:
    rig = Rig()
    rig.add("dep", status="work-review")
    rig.add("child", deps=("dep",))
    asyncio.run(rig.tick.run())
    assert rig.spawned == []
    assert rig.tick.held == {"child": ("dep",)}
    assert rig.tick.runnable_todo() == []


def test_dependency_cycle_and_discarded_dependency_fire_the_stuck_rows() -> None:
    rig = Rig()
    rig.add("a", deps=("b",))
    rig.add("b", deps=("a",))
    rig.add("gone", status="discarded")
    rig.add("child", deps=("gone",))
    asyncio.run(rig.tick.run())
    assert rig.spawned == []
    assert rig.status("a") != "work-todo" and rig.status("b") != "work-todo"
    assert rig.status("child") != "work-todo"
    assert any("dependency was discarded: gone" in line
               for line in rig.tasks.records[TaskId("child")].log)


def test_the_tick_is_skipped_while_the_lock_is_held_by_someone_else() -> None:
    rig = Rig(lock=FakeLock(held=False))
    rig.add("a")
    asyncio.run(rig.tick.run())
    assert rig.spawned == []
    assert rig.status("a") == "work-todo"


def test_cleanup_removes_done_discarded_and_missing_but_not_running_or_open() -> None:
    ws = FakeWorkspaces(["done1", "disc", "ghost", "open", "busy"])
    rig = Rig(workspaces=ws)
    rig.add("done1", status="done")
    rig.add("disc", status="discarded")
    rig.add("open", status="work-review")
    rig.add("busy", status="done")

    async def go() -> None:
        rig.running["busy"] = Running(asyncio.ensure_future(asyncio.sleep(10)), 0.0, "work-running")
        await rig.tick.run()
        rig.running["busy"].task.cancel()

    asyncio.run(go())
    assert ws.removed == ["done1", "disc", "ghost"]


def test_cleanup_survives_a_removal_failure() -> None:
    ws = FakeWorkspaces(["ghost"], fail=True)
    rig = Rig(workspaces=ws)
    asyncio.run(rig.tick.run())
    assert ws.removed == []


def test_observe_notes_a_hand_move_and_reverts_an_illegal_one() -> None:
    rig = Rig()
    rig.add("ok", status="work-review")
    rig.add("bad", status="work-todo")
    rig.tasks.observe_moves()  # the baseline the store last knew
    rig.tasks.hand_move(TaskId("ok"), "done")
    rig.tasks.hand_move(TaskId("bad"), "work-review")
    rig.tick.observe()
    assert any("observed hand move" in line for line in rig.tasks.records[TaskId("ok")].log)
    assert rig.status("bad") == "work-todo"
    assert any("illegal move" in line for line in rig.tasks.records[TaskId("bad")].log)


def test_notes_are_held_while_the_agent_runs_and_written_after() -> None:
    rig = Rig()
    rig.add("t", status="work-running")

    async def go() -> None:
        rig.running["t"] = Running(asyncio.ensure_future(asyncio.sleep(10)), 0.0, "work-running")
        rig.notes.add("t", "held line")
        assert "held line" not in rig.tasks.records[TaskId("t")].log
        rig.running["t"].task.cancel()
        del rig.running["t"]
        rig.notes.release("t")

    asyncio.run(go())
    assert "held line" in rig.tasks.records[TaskId("t")].log


def test_reconcile_stops_a_worker_whose_file_left_its_folder() -> None:
    rig = Rig()
    rig.add("t", status="work-review")

    async def go() -> Running:
        entry = Running(asyncio.ensure_future(asyncio.sleep(10)), 0.0, "work-running")
        rig.running["t"] = entry
        rig.tick.reconcile()
        await asyncio.sleep(0)
        return entry

    entry = asyncio.run(go())
    assert entry.stop_reason == "moved"
