"""`Tick`: the decisions of one poll of the orchestrator (spec: orchestrator).

Observe hand moves, reconcile the running workers with the task files, clean up workspaces and
dispatch the next tasks. Starting a worker is the orchestrator's business: `Tick` calls `spawn`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from samba.app.machine import Machine
from samba.domain.deps import deps_snapshot, evaluate
from samba.domain.states import Stage, State, running_of
from samba.domain.task import Task
from samba.domain.task_id import TaskId
from samba.domain.transitions import human_row, log_line
from samba.domain.ports import Clock, Journal, Lock, Tasks, Vcs, WorkspaceError

StopReason = Literal["moved", "shutdown"]


def stage_of(task: Task) -> Stage:
    return "plan" if task.last_stage == "plan" else "work"


@dataclass
class Running:
    task: asyncio.Task[None]
    started_at: float
    folder: State  # the running folder the task was claimed into
    turn: int = 0
    stop_reason: StopReason | None = None


class Notes:
    """`## Log` lines, written at once or held while an agent runs (spec: task-files, Write
    discipline). One holder is shared by the tick and the orchestrator."""

    def __init__(self, tasks: Tasks, running: dict[str, Running]) -> None:
        self.tasks = tasks
        self.running = running
        self.pending: dict[str, list[str]] = {}

    def add(self, task_id: str, line: str) -> None:
        if task_id in self.running:
            self.pending.setdefault(task_id, []).append(line)
        else:
            self._write(task_id, [line])

    def release(self, task_id: str) -> None:
        """The agent stopped: write the held lines."""
        lines = self.pending.pop(task_id, [])
        if lines:
            self._write(task_id, lines)

    def _write(self, task_id: str, lines: list[str]) -> None:
        task = self.tasks.get(TaskId(task_id))
        if task is not None:
            for line in lines:
                task.add_log(line)
            self.tasks.save(task)


class Tick:
    def __init__(self, tasks: Tasks, clock: Clock, lock: Lock, vcs: Vcs,
                 machine: Machine, max_concurrent: int, running: dict[str, Running],
                 notes: Notes, spawn: Callable[[Task], None], journal: Journal) -> None:
        self.journal = journal
        self.tasks = tasks
        self.clock = clock
        self.lock = lock
        self.vcs = vcs
        self.machine = machine
        self.max_concurrent = max_concurrent
        self.running = running
        self.notes = notes
        self.spawn = spawn
        self.held: dict[str, tuple[str, ...]] = {}  # todo tasks waiting on dependencies
        self.warned_invalid: set[str] = set()
        self.warned_deps: set[tuple[str, str]] = set()

    def _status(self, task_id: str) -> State | None:
        task = self.tasks.get(TaskId(task_id))
        return task.status if task is not None else None

    def runnable_todo(self) -> list[str]:
        """Todo tasks that will run eventually: not held only by dependencies (spec: cli)."""
        return [tid for status in ("plan-todo", "work-todo") for tid in self.tasks.ids(status)
                if tid not in self.held]

    async def run(self) -> None:
        # A state-changing command holds the repo lock for its whole rename + sidecar + log
        # sequence (spec: task-files, Write discipline). Skip the tick while it does: observe()
        # would misread the half-done move as a hand move, and dispatch could claim the task
        # before the command saved.
        with self.lock.acquire(blocking=False) as held:
            if not held:
                self.journal.debug("tick_skipped", reason="repo lock held")
                return
            self.observe()
            self.reconcile()
            await self.cleanup_workspaces()
            self.dispatch()

    def observe(self) -> None:
        """Interpret hand moves: a task in another status than the store last knew (spec: states)."""
        for move in self.tasks.observe_moves():
            task = self.tasks.get(move.task_id)
            if task is None:
                continue
            row = human_row(move.src, move.dst, task)
            if row is not None:
                self.notes.add(move.task_id, self.machine.observe(move, row, task))
                continue
            if not self.tasks.revert_move(move):
                continue
            self.journal.warning("illegal_move", task=move.task_id, src=move.src, dst=move.dst)
            self.notes.add(move.task_id, log_line(
                f"illegal move: {move.src} -> {move.dst}, moved back to {move.src}", self.clock))

    def reconcile(self) -> None:
        for task_id, entry in list(self.running.items()):
            status = self._status(task_id)
            if entry.stop_reason is None and status != entry.folder:
                entry.stop_reason = "moved"
                entry.task.cancel()
                self.journal.info("stopping", task=task_id,
                                  reason=f"task file left {entry.folder}/",
                                  now=status or "deleted")

    async def cleanup_workspaces(self) -> None:
        for task_id in await self.vcs.existing_workspaces():
            if task_id in self.running:
                continue
            state = self._status(task_id)
            if state in (None, "done", "discarded"):
                try:
                    await self.vcs.remove_workspace(task_id)
                    self.journal.info("workspace_removed", task=task_id)
                except WorkspaceError as e:
                    self.journal.warning("workspace_remove_failed", task=task_id, error=e)

    def dispatch(self) -> None:
        for status in ("plan-todo", "work-todo"):
            for name in self.tasks.rejected_names(status):
                if name not in self.warned_invalid:
                    self.warned_invalid.add(name)
                    self.journal.warning("invalid_task_name", file=name,
                                         hint="use only letters, digits, '.', '_' and '-'")
        now = self.clock.time()
        self.held = {}
        candidates: list[Task] = []
        for status in ("plan-todo", "work-todo"):
            for task in self.tasks.list(status):
                if task.id in self.running or not self._deps_ready(task):
                    continue
                if task.not_before is not None and task.not_before > now:
                    continue
                candidates.append(task)
        candidates.sort(key=lambda t: (t.priority is None, t.priority or 0, t.queued_at or 0.0,
                                       t.id))
        for task in candidates:
            if len(self.running) >= self.max_concurrent:
                break
            if task.status == "work-todo":
                self.machine.fire(task.id, "route_to_plan", task=task)  # to plan-todo, if it applies
            if not self.machine.fire(task.id, "dispatch_plan" if task.status == "plan-todo"
                                     else "dispatch_work", task=task):
                continue
            stage = stage_of(task)
            self.journal.info("dispatch", task=task.id, attempt=task.attempts, stage=stage,
                              resume=bool(task.plan_session_id if stage == "plan"
                                          else task.session_id))
            self.spawn(task)

    def _deps_ready(self, task: Task) -> bool:
        """The dependency guard of the dispatch rows (spec: orchestrator, Dependencies). Fires the stuck rows."""
        status = evaluate(deps_snapshot(task, self.tasks.get), task.id)
        if status.kind == "ready":
            return True
        if status.kind == "cycle":
            self.machine.fire(task.id, "dependency_cycle", message="dependency cycle")
        elif status.kind == "discarded":
            self.machine.fire(task.id, "dependency_discarded", message=(
                "a dependency was discarded: " + ", ".join(status.waiting)))
        else:
            self.held[task.id] = status.waiting
            for dep_id in status.unknown:
                if (task.id, dep_id) not in self.warned_deps:
                    self.warned_deps.add((task.id, dep_id))
                    self.journal.warning("unknown_dependency", task=task.id, dependency=dep_id)
        return False


def running_folder(task: Task) -> State:
    return running_of(stage_of(task))
