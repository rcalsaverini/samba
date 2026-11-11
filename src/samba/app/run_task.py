"""`RunTask`: the run of one task, from workspace to the finishing transition (spec: orchestrator, Workers)."""

from __future__ import annotations

from collections.abc import Callable

from samba.app.finish import Finisher
from samba.app.prompt_builder import PromptBuilder
from samba.app.tick import stage_of
from samba.app.turn import TurnFlow
from samba.domain.policy import Fail
from samba.domain.ports import Journal, Tasks, Vcs, WorkspaceError
from samba.domain.task_id import TaskId
from samba.domain.template import TemplateError


class RunTask:
    def __init__(self, tasks: Tasks, vcs: Vcs, turns: TurnFlow, builder: PromptBuilder,
                 finisher: Finisher, journal: Journal) -> None:
        self.tasks = tasks
        self.vcs = vcs
        self.turns = turns
        self.builder = builder
        self.finisher = finisher
        self.journal = journal

    async def run(self, task_id: str, on_turn: Callable[[int], None]) -> None:
        task = self.tasks.get(TaskId(task_id))
        if task is None:
            return
        try:
            workspace = await self.vcs.ensure_workspace(task_id)
        except WorkspaceError as e:
            await self.finisher.fail(task, str(e))
            return
        ws = workspace.location
        if workspace.created:
            self.journal.info("workspace_created", task=task_id, path=ws)
        task.workspace = ws
        task.branch = self.vcs.branch_name(task_id)
        self.tasks.save(task)

        stage = stage_of(task)
        try:
            setup = self.builder.setup(task, ws, stage)
        except TemplateError as e:
            await self.finisher.fail(task, str(e))
            return

        result = await self.turns.run(task, setup, on_turn)
        if isinstance(result, Fail):
            await self.finisher.fail(task, result.error)
        else:
            await self.finisher.finish(task, result.event, result.what, result.summary)

    async def crashed(self, task_id: str, error: Exception) -> None:
        """A bug in Samba itself: do not lose the task."""
        self.journal.exception("worker_crashed", task=task_id, error=error)
        task = self.tasks.get(TaskId(task_id))
        if task is not None:
            await self.finisher.fail(task, f"internal error: {error}")
