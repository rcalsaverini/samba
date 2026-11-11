"""`Startup`: the checks and the recovery before the first tick (spec: orchestrator, Startup)."""

from __future__ import annotations

from samba.app.machine import Machine
from samba.domain.ports import AgentRunner, Journal, StoreError, Tasks, Vcs
from samba.domain.states import running_of, todo_of


class StartupError(Exception):
    pass


class Startup:
    def __init__(self, config_warnings: list[str], tasks: Tasks, vcs: Vcs, agent: AgentRunner,
                 machine: Machine, journal: Journal) -> None:
        self.config_warnings = config_warnings
        self.tasks = tasks
        self.vcs = vcs
        self.agent = agent
        self.machine = machine
        self.journal = journal

    async def run(self) -> None:
        try:
            self.tasks.prepare()
        except StoreError as e:
            raise StartupError(str(e)) from e
        problem = await self.vcs.repository_problem()
        if problem:
            raise StartupError(problem)
        readiness = await self.agent.ready()
        if not readiness.ok:
            raise StartupError(
                f"claude auth status says not logged in; run `claude auth login`. {readiness.detail}")
        for w in self.config_warnings:
            self.journal.warning("config_warning", message=w)

        await self.vcs.exclude_samba_dir()

        for stage in ("plan", "work"):
            for task in self.tasks.list(running_of(stage)):
                if self.machine.fire(task.id, "recover", message="recovered at startup"):
                    self.journal.info("recovered", task=task.id, to=todo_of(stage))
