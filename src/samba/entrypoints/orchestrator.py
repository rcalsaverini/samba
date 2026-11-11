"""The poll loop and the asyncio workers; every rule is delegated to `app/` (spec: orchestrator).

Step 1 of ADR 0015: the rules live in `Startup`, `RunTask` (with `PromptBuilder` and `Finisher`)
and `Guard`. The next step moves the workers out and leaves a thin loop here.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools

from samba.app.finish import Finisher
from samba.app.guard import Guard
from samba.app.machine import Machine
from samba.app.prompt_builder import PromptBuilder
from samba.app.run_task import RunTask
from samba.app.startup import Startup
from samba.app.tick import Notes, Running, Tick, running_folder
from samba.app.turn import TurnFlow
from samba.domain.settings import Config
from samba.domain.ports import (
    AgentRunner,
    Clock,
    IdGenerator,
    Journal,
    Lock,
    Tasks,
    Validator,
    Vcs,
    WorkspaceError,
)
from samba.domain.states import State
from samba.domain.task import Task
from samba.domain.task_id import TaskId


class Orchestrator:
    def __init__(self, config: Config, clock: Clock, ids: IdGenerator, agent: AgentRunner,
                 tasks: Tasks, vcs: Vcs, validator: Validator, lock: Lock,
                 journal: Journal) -> None:
        """Every port is passed in; the bootstrap (`samba.bootstrap`) builds them."""
        self.journal = journal
        self.policy = config.policy
        self.clock: Clock = clock
        self.tasks: Tasks = tasks
        self.vcs = vcs
        self.running: dict[str, Running] = {}
        self._workers: dict[str, asyncio.Task[None]] = {}
        turns = TurnFlow(agent, ids, tasks, clock, validator, journal)
        self.machine = Machine(tasks, clock, journal, Guard(config.policy.require_plan, tasks))
        self.notes = Notes(tasks, self.running)  # `## Log` lines held while an agent runs
        builder = PromptBuilder(config, tasks, vcs)
        finisher = Finisher(config.policy, self.machine, turns, builder, tasks, vcs, journal)
        self.run_task = RunTask(tasks, vcs, turns, builder, finisher, journal)
        self.startup_check = Startup(config.warnings, tasks, vcs, agent, self.machine, journal)
        self.ticker = Tick(tasks, clock, lock, vcs, self.machine, self.policy.max_concurrent,
                           self.running, self.notes, self._spawn, journal)

    def _status(self, task_id: str) -> State | None:
        task = self.tasks.get(TaskId(task_id))
        return task.status if task is not None else None

    async def startup(self) -> None:
        await self.startup_check.run()

    # ---- loop ---------------------------------------------------------------------------

    async def run(self, exit_when_idle: bool = False) -> None:
        await self.startup()
        self.journal.info("started", repo=self.vcs.checkout_location(),
                          max_concurrent=self.policy.max_concurrent)
        try:
            while True:
                await self.tick()
                if exit_when_idle and not self.running and not self.ticker.runnable_todo():
                    await self.cleanup_workspaces()
                    self.journal.info("idle_exit")
                    return
                await asyncio.sleep(self.policy.poll_interval_s)
        finally:
            await self.shutdown()

    async def tick(self) -> None:
        await self.ticker.run()

    async def cleanup_workspaces(self) -> None:
        await self.ticker.cleanup_workspaces()

    # ---- workers ------------------------------------------------------------------------

    def _spawn(self, task: Task) -> None:
        """Start the worker of a task the tick just claimed."""
        worker = asyncio.create_task(self.work(task.id))
        self._workers[task.id] = worker
        self.running[task.id] = Running(task=worker, started_at=self.clock.monotonic(),
                                        folder=running_folder(task))
        worker.add_done_callback(functools.partial(self._on_worker_done, task.id))

    def _on_worker_done(self, task_id: str, _worker: asyncio.Task[None]) -> None:
        self.running.pop(task_id, None)
        self._workers.pop(task_id, None)
        self.notes.release(task_id)

    async def wait_workers(self) -> None:
        """Wait for the workers running now to end."""
        await asyncio.gather(*list(self._workers.values()))

    async def shutdown(self) -> None:
        if not self.running:
            return
        for entry in self.running.values():
            if entry.stop_reason is None:
                entry.stop_reason = "shutdown"
            entry.task.cancel()
        await asyncio.gather(*list(self._workers.values()), return_exceptions=True)

    async def work(self, task_id: str) -> None:
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
