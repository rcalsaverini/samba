"""The asyncio workers: one per running task (spec: orchestrator, architecture).

`Workers` starts a worker for a task the tick claimed, tracks it in the `running` dict shared
with `Tick`, handles a cancelled worker (journal `stopped`, recover on shutdown, workspace
removal when the task was moved by hand), reports any other exception as a crash, and shuts
the workers down. It holds no rule: the run of a task is `RunTask`.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools

from samba.app.machine import Machine
from samba.app.run_task import RunTask
from samba.app.tick import Notes, Running, running_folder
from samba.domain.ports import Clock, Journal, Tasks, Vcs, WorkspaceError
from samba.domain.states import State
from samba.domain.task import Task
from samba.domain.task_id import TaskId


class Workers:
    def __init__(self, run_task: RunTask, machine: Machine, tasks: Tasks, vcs: Vcs,
                 clock: Clock, journal: Journal, running: dict[str, Running],
                 notes: Notes) -> None:
        self.run_task = run_task
        self.machine = machine
        self.tasks = tasks
        self.vcs = vcs
        self.clock = clock
        self.journal = journal
        self.running = running
        self.notes = notes
        self._workers: dict[str, asyncio.Task[None]] = {}

    def spawn(self, task: Task) -> None:
        """Start the worker of a task the tick just claimed."""
        worker = asyncio.create_task(self._work(task.id))
        self._workers[task.id] = worker
        self.running[task.id] = Running(task=worker, started_at=self.clock.monotonic(),
                                        folder=running_folder(task))
        worker.add_done_callback(functools.partial(self._on_done, task.id))

    def _on_done(self, task_id: str, _worker: asyncio.Task[None]) -> None:
        self.running.pop(task_id, None)
        self._workers.pop(task_id, None)
        self.notes.release(task_id)

    def _status(self, task_id: str) -> State | None:
        task = self.tasks.get(TaskId(task_id))
        return task.status if task is not None else None

    async def _work(self, task_id: str) -> None:
        def on_turn(n: int) -> None:
            entry = self.running.get(task_id)
            if entry:
                entry.turn = n

        try:
            await self.run_task.run(task_id, on_turn)
        except asyncio.CancelledError:
            entry = self.running.get(task_id)
            reason = entry.stop_reason if entry else "shutdown"
            self.journal.info("stopped", task=task_id, reason=reason)
            if reason == "shutdown":
                self.machine.fire(TaskId(task_id), "recover", message="stopped by shutdown")
            elif reason == "moved" and self._status(task_id) in (None, "done", "discarded"):
                with contextlib.suppress(WorkspaceError):
                    await self.vcs.remove_workspace(task_id)
        except Exception as e:  # a bug in Samba itself: do not lose the task
            await self.run_task.crashed(task_id, e)

    async def shutdown(self) -> None:
        if not self.running:
            return
        for entry in self.running.values():
            if entry.stop_reason is None:
                entry.stop_reason = "shutdown"
            entry.task.cancel()
        await asyncio.gather(*list(self._workers.values()), return_exceptions=True)

    async def wait_all(self) -> None:
        """Wait for the workers running now to end (tests)."""
        await asyncio.gather(*list(self._workers.values()))
