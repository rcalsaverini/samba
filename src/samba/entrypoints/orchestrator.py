"""The poll loop, dispatch, and per-task workers (spec: orchestrator)."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import re

from samba.app.machine import Machine
from samba.app.tick import Notes, Running, Tick, running_folder, stage_of
from samba.app.turn import TurnFlow, TurnSetup
from samba.domain.settings import Config
from samba.domain.policy import Fail, Retry, RetryPolicy, should_reflect
from samba.domain.ports import (
    AgentRunner,
    Clock,
    IdGenerator,
    Journal,
    Lock,
    StoreError,
    Tasks,
    Validator,
    Vcs,
    WorkspaceError,
)
from samba.domain.prompts import (
    APPROVED_PLAN_RULE,
    DEFAULT_PROMPTS,
    PLAN_PROTOCOL,
    PROTOCOL,
    allowed_tools_note,
    validate_note,
)
from samba.domain.deps import deps_snapshot, evaluate
from samba.domain.questions import open_questions, round_pairs
from samba.domain.states import Stage, State, running_of, todo_of
from samba.domain.task import Task
from samba.domain.task_id import TaskId
from samba.domain.template import TemplateError, render


class StartupError(Exception):
    pass


class Orchestrator:
    def __init__(self, config: Config, clock: Clock, ids: IdGenerator, agent: AgentRunner,
                 tasks: Tasks, vcs: Vcs, validator: Validator, lock: Lock,
                 journal: Journal) -> None:
        """Every port is passed in; the bootstrap (`samba.bootstrap`) builds them."""
        self.journal = journal
        self.config = config
        self.policy = config.policy
        self.prompts = config.prompts
        self.validation = config.validation
        self.clock: Clock = clock
        self.ids: IdGenerator = ids
        self.tasks: Tasks = tasks
        self.agent: AgentRunner = agent
        self.vcs = vcs
        self.turns = TurnFlow(self.agent, self.ids, self.tasks, self.clock, validator, journal)
        self.running: dict[str, Running] = {}
        self.machine = Machine(self.tasks, self.clock, journal, self._guard)
        self.notes = Notes(self.tasks, self.running)  # `## Log` lines held while an agent runs
        self.ticker = Tick(self.tasks, self.clock, lock, self.vcs,
                           self.machine, self.policy.max_concurrent, self.running, self.notes,
                           self._spawn, journal)

    def _guard(self, name: str, task: Task) -> bool:
        if name == "plan_required":
            return self.policy.require_plan and not task.plan_approved
        if name == "deps_met":
            return evaluate(deps_snapshot(task, self.tasks.get), task.id).kind == "ready"
        return False

    def _status(self, task_id: str) -> State | None:
        task = self.tasks.get(TaskId(task_id))
        return task.status if task is not None else None

    # ---- startup ------------------------------------------------------------------------

    async def startup(self) -> None:
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
        for w in self.config.warnings:
            self.journal.warning("config_warning", message=w)

        await self.vcs.exclude_samba_dir()

        for stage in ("plan", "work"):
            for task in self.tasks.list(running_of(stage)):
                if self.machine.fire(task.id, "recover", message="recovered at startup"):
                    self.journal.info("recovered", task=task.id, to=todo_of(stage))

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

    def _spawn(self, task: Task) -> None:
        """Start the worker of a task the tick just claimed."""
        worker = asyncio.create_task(self.work(task.id))
        self.running[task.id] = Running(task=worker, started_at=self.clock.monotonic(),
                                        folder=running_folder(task))
        worker.add_done_callback(functools.partial(self._on_worker_done, task.id))

    def _on_worker_done(self, task_id: str, _worker: asyncio.Task[None]) -> None:
        self.running.pop(task_id, None)
        self.notes.release(task_id)

    async def shutdown(self) -> None:
        if not self.running:
            return
        for entry in self.running.values():
            if entry.stop_reason is None:
                entry.stop_reason = "shutdown"
            entry.task.cancel()
        await asyncio.gather(*(e.task for e in list(self.running.values())),
                             return_exceptions=True)

    # ---- worker -------------------------------------------------------------------------

    async def work(self, task_id: str) -> None:
        try:
            await self._work(task_id)
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
            self.journal.exception("worker_crashed", task=task_id, error=e)
            task = self.tasks.get(TaskId(task_id))
            if task is not None:
                await self._fail(task, f"internal error: {e}")

    async def _work(self, task_id: str) -> None:
        task = self.tasks.get(TaskId(task_id))
        if task is None:
            return
        try:
            workspace = await self.vcs.ensure_workspace(task_id)
        except WorkspaceError as e:
            await self._fail(task, str(e))
            return
        ws = workspace.location
        if workspace.created:
            self.journal.info("workspace_created", task=task_id, path=ws)
        task.workspace = ws
        task.branch = self.vcs.branch_name(task_id)
        self.tasks.save(task)

        stage = stage_of(task)
        try:
            setup = self._setup(task, ws, stage)
        except TemplateError as e:
            await self._fail(task, str(e))
            return

        def on_turn(n: int) -> None:
            entry = self.running.get(task_id)
            if entry:
                entry.turn = n

        result = await self.turns.run(task, setup, on_turn)
        if isinstance(result, Fail):
            await self._fail(task, result.error)
        else:
            await self._finish(task, result.event, result.what, result.summary)

    def _setup(self, task: Task, ws: str, stage: Stage) -> TurnSetup:
        """The prompts and limits of a run (spec: prompts, Which prompt is sent)."""
        variables = self._variables(task, ws)
        cap = self.policy.max_cost_usd_per_task
        if stage == "plan":
            system_prompt = render(PLAN_PROTOCOL, {
                **variables,
                "allowed_tools": allowed_tools_note(self.config.agent.planning_allow, "dontAsk"),
            })
            first = self._first_plan_prompt(variables)
            resume = bool(task.plan_session_id)
            return TurnSetup(
                stage="plan", system_prompt=system_prompt, location=ws,
                prompt=self._prompt("plan_revise", variables) if resume else first,
                resume=resume, first_prompt=first, continue_prompt="",
                validate_failed=lambda tail: "", max_turns=1, validate_enabled=False,
                max_cost_usd=cap)
        first = render(self.prompts.template, variables)
        resume = bool(task.session_id)
        failed = self._prompt("validate_failed", variables)
        return TurnSetup(
            stage="work", system_prompt=self._system_prompt(variables, task), location=ws,
            prompt=self._prompt("resume", variables) if resume else first, resume=resume,
            first_prompt=first, continue_prompt=self._prompt("continue", variables),
            validate_failed=lambda tail: failed + "\n\n```\n" + tail + "\n```",
            max_turns=self.policy.max_turns, validate_enabled=bool(self.validation.command),
            max_cost_usd=cap)

    def _first_plan_prompt(self, variables: dict[str, str]) -> str:
        override = self.prompts.overrides.get("plan")
        if override:
            return render(override, variables)
        return render(self.prompts.template, variables) + "\n\n" + DEFAULT_PROMPTS["plan"]

    # ---- transitions --------------------------------------------------------------------

    async def _finish(self, task: Task, event: str, what: str, summary: str = "") -> None:
        msg = f"{what} (turns {task.turns_total}, ${task.cost_usd_total:.2f})"
        if summary:
            msg += f": {summary}"
        moved = self.machine.fire(task.id, event, task=task, message=msg)
        self.journal.info("finished", task=task.id, transition=event, moved=moved)

    async def _fail(self, task: Task, error: str) -> None:
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

        in_running = self._status(task_id) == running_of(stage)
        if should_reflect(policy.reflect_on_give_up, task.session_id, stage, in_running):
            with contextlib.suppress(TemplateError):
                ws = task.workspace or self.vcs.workspace_location(task_id)
                variables = self._variables(task, ws)
                await self.turns.invoke(
                    task, stage="work", prompt=self._prompt("give_up", variables),
                    resume=True, system_prompt=self._system_prompt(variables, task),
                    location=ws, max_cost_usd=policy.max_cost_usd_per_task)
        self.machine.fire(task_id, "give_up", task=task, error=error,
                          message=f"gave up after {attempts} failed attempts: {error}")

    # ---- helpers ------------------------------------------------------------------------

    def _variables(self, task: Task, ws: str) -> dict[str, str]:
        return {
            "task.id": task.id,
            "task.title": task.title,
            "task.body": task.body,
            "task.path": self.tasks.location(task.id),
            "workspace": ws,
            "branch": self.vcs.branch_name(task.id),
            "base_branch": self.config.repository.base_branch,
            "attempt": str(task.attempts),
            "validate_command": self.validation.command or "",
            # The answered round, for the first run after a question (spec: prompts, Which prompt is sent).
            "questions": (round_pairs(task.questions)
                          if task.last_outcome == "blocked" and not open_questions(task.questions)
                          else ""),
        }

    def _system_prompt(self, variables: dict[str, str], task: Task) -> str:
        agent = self.config.agent
        text = render(PROTOCOL, {
            **variables,
            "validate_note": validate_note(self.validation.command),
            "allowed_tools": allowed_tools_note(agent.allow, agent.permission_mode),
        })
        if task.plan_approved:
            text = text.rstrip("\n") + "\n" + APPROVED_PLAN_RULE
        return text

    def _prompt(self, key: str, variables: dict[str, str]) -> str:
        template = self.prompts.overrides.get(key) or DEFAULT_PROMPTS[key]
        text = render(template, variables).rstrip()
        questions = variables.get("questions", "")
        # A custom prompt without {{ questions }} must not lose the answers.
        if key in ("resume", "plan_revise") and questions and "questions" not in re.findall(
                r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}", template):
            text += "\n\n" + questions
        return text

