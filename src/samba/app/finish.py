"""`Finisher`: finish a run, or fail it and decide to retry, reflect or give up (spec: orchestrator, Retries)."""

from __future__ import annotations

import contextlib

from samba.app.machine import Machine
from samba.app.prompt_builder import PromptBuilder
from samba.app.tick import stage_of
from samba.app.turn import TurnFlow
from samba.domain.policy import Retry, RetryPolicy, should_reflect
from samba.domain.ports import Journal, Tasks, Vcs
from samba.domain.settings import Policy
from samba.domain.states import running_of
from samba.domain.task import Task
from samba.domain.task_id import TaskId
from samba.domain.template import TemplateError


class Finisher:
    def __init__(self, policy: Policy, machine: Machine, turns: TurnFlow, builder: PromptBuilder,
                 tasks: Tasks, vcs: Vcs, journal: Journal) -> None:
        self.policy = policy
        self.machine = machine
        self.turns = turns
        self.builder = builder
        self.tasks = tasks
        self.vcs = vcs
        self.journal = journal

    async def finish(self, task: Task, event: str, what: str, summary: str = "") -> None:
        msg = f"{what} (turns {task.turns_total}, ${task.cost_usd_total:.2f})"
        if summary:
            msg += f": {summary}"
        moved = self.machine.fire(task.id, event, task=task, message=msg)
        self.journal.info("finished", task=task.id, transition=event, moved=moved)

    async def fail(self, task: Task, error: str) -> None:
        policy = self.policy
        task_id = task.id
        stage = stage_of(task)
        decision = RetryPolicy(policy.max_attempts, policy.retry_base_s,
                               policy.max_retry_backoff_s).decide(task.attempts)
        attempts = decision.attempts
        self.journal.warning("attempt_failed", task=task_id, attempt=attempts, error=error)
        if isinstance(decision, Retry):
            delay = decision.delay
            self.machine.fire(
                task_id, "retry_plan" if stage == "plan" else "retry_work", task=task,
                message=f"attempt {attempts} failed: {error}; retry in {delay:.0f}s",
                error=error, delay=delay)
            return

        current = self.tasks.get(TaskId(task_id))
        in_running = (current.status if current is not None else None) == running_of(stage)
        if should_reflect(policy.reflect_on_give_up, task.session_id, stage, in_running):
            with contextlib.suppress(TemplateError):
                ws = task.workspace or self.vcs.workspace_location(task_id)
                variables = self.builder.variables(task, ws)
                await self.turns.invoke(
                    task, stage="work", prompt=self.builder.prompt("give_up", variables),
                    resume=True, system_prompt=self.builder.system_prompt(variables, task),
                    location=ws, max_cost_usd=policy.max_cost_usd_per_task)
        self.machine.fire(task_id, "give_up", task=task, error=error,
                          message=f"gave up after {attempts} failed attempts: {error}")
