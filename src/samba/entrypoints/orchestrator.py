"""The orchestrator: wires the parts and runs the poll loop (spec: orchestrator, architecture).

It holds no rule. `Startup` checks and recovers, `Tick` observes, reconciles, cleans up and
dispatches, `RunTask` runs one task (with `PromptBuilder` and `Finisher`), `Workers` supervises
the asyncio workers (cancel, shutdown). `Tick` and `Workers` share one `running` dict and one
`Notes`.
"""

from __future__ import annotations

import asyncio

from samba.app.finish import Finisher
from samba.app.guard import Guard
from samba.app.machine import Machine
from samba.app.prompt_builder import PromptBuilder
from samba.app.run_task import RunTask
from samba.app.startup import Startup
from samba.app.tick import Notes, Running, Tick
from samba.app.turn import TurnFlow
from samba.domain.ports import (
    AgentRunner,
    Clock,
    IdGenerator,
    Journal,
    Lock,
    Tasks,
    Validator,
    Vcs,
)
from samba.domain.settings import Config
from samba.entrypoints.workers import Workers


class Orchestrator:
    def __init__(self, config: Config, clock: Clock, ids: IdGenerator, agent: AgentRunner,
                 tasks: Tasks, vcs: Vcs, validator: Validator, lock: Lock,
                 journal: Journal) -> None:
        """Every port is passed in; the bootstrap (`samba.bootstrap`) builds them."""
        self.journal = journal
        self.vcs = vcs
        self.policy = config.policy
        running: dict[str, Running] = {}
        notes = Notes(tasks, running)  # `## Log` lines held while an agent runs
        turns = TurnFlow(agent, ids, tasks, clock, validator, journal)
        machine = Machine(tasks, clock, journal, Guard(config.policy.require_plan, tasks))
        builder = PromptBuilder(config, tasks, vcs)
        finisher = Finisher(config.policy, machine, turns, builder, tasks, vcs, journal)
        run_task = RunTask(tasks, vcs, turns, builder, finisher, journal)
        self.running = running
        self.workers = Workers(run_task, machine, tasks, vcs, clock, journal, running, notes)
        self.startup_check = Startup(config.warnings, tasks, vcs, agent, machine, journal)
        self.ticker = Tick(tasks, clock, lock, vcs, machine, self.policy.max_concurrent,
                           running, notes, self.workers.spawn, journal)

    async def startup(self) -> None:
        await self.startup_check.run()

    async def tick(self) -> None:
        await self.ticker.run()

    async def cleanup_workspaces(self) -> None:
        await self.ticker.cleanup_workspaces()

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
            await self.workers.shutdown()
