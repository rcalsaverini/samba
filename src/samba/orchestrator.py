"""The poll loop, dispatch, and per-task workers (spec: orchestrator)."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import re
from pathlib import Path

from samba.adapters.claude_cli import ClaudeCliRunner
from samba.adapters.git_workspaces import GitWorkspaces
from samba.adapters.markdown_tasks import MarkdownTasks
from samba.adapters.repo_lock import FileRepoLock
from samba.adapters.system import SystemClock, UuidGenerator
from samba.app.machine import Machine
from samba.app.tick import Notes, Running, Tick, running_folder, stage_of
from samba.app.turn import TurnFlow, TurnSetup
from samba.config import Config
from samba.domain.policy import Fail, Retry, RetryPolicy, should_reflect
from samba.logfmt import kv
from samba.ports import (
    AgentRunner,
    Clock,
    IdGenerator,
    StoreError,
    Tasks,
    WorkspaceError,
)
from samba.proc import git, run_shell
from samba.prompts import (
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
from samba.template import TemplateError, render
from samba.workspace import branch_name

log = logging.getLogger("samba")


class StartupError(Exception):
    pass


class Orchestrator:
    def __init__(self, config: Config, clock: Clock | None = None,
                 ids: IdGenerator | None = None, agent: AgentRunner | None = None,
                 tasks: Tasks | None = None) -> None:
        self.config = config
        self.policy = config.policy
        self.layout = config.layout
        self.prompts = config.prompts
        self.validation = config.validation
        self.clock: Clock = clock or SystemClock()
        self.ids: IdGenerator = ids or UuidGenerator()
        self.sym = config.layout.samba_dir
        self.tasks: Tasks = tasks or MarkdownTasks(self.sym / "tasks", self.sym / "state",
                                                    self.clock)
        self.runs_dir = self.sym / "runs"
        self.agent: AgentRunner = agent or ClaudeCliRunner(
            config.agent, (self.sym / "tasks").resolve(), self.runs_dir, config.layout.repo)
        self.workspaces = GitWorkspaces(config.layout, config.hooks, config.validation.shell)
        self.turns = TurnFlow(self.agent, self.ids, self.tasks, self.clock)
        self.running: dict[str, Running] = {}
        self.machine = Machine(self.tasks, self.clock, self._guard)
        self.notes = Notes(self.tasks, self.running)  # `## Log` lines held while an agent runs
        self.ticker = Tick(self.tasks, self.clock, FileRepoLock(self.sym), self.workspaces,
                           self.machine, self.policy.max_concurrent, self.running, self.notes,
                           self._spawn)

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
        layout = self.layout
        try:
            self.tasks.prepare()
        except StoreError as e:
            raise StartupError(str(e)) from e
        top = await git(layout.repo, "rev-parse", "--show-toplevel")
        if not top.ok or Path(top.output.strip()).resolve() != layout.repo:
            raise StartupError(f"{layout.repo} is not the root of a git repository")
        base = await git(layout.repo, "rev-parse", "--verify", "--quiet",
                         f"refs/heads/{layout.base_branch}")
        if not base.ok:
            raise StartupError(f"base_branch '{layout.base_branch}' does not exist")
        readiness = await self.agent.ready()
        if not readiness.ok:
            raise StartupError(
                f"claude auth status says not logged in; run `claude auth login`. {readiness.detail}")
        for w in self.config.warnings:
            log.warning(kv("config_warning", message=w))

        self.runs_dir.mkdir(parents=True, exist_ok=True)
        await self._exclude_samba_dir()

        for stage in ("plan", "work"):
            for task in self.tasks.list(running_of(stage)):
                if self.machine.fire(task.id, "recover", message="recovered at startup"):
                    log.info(kv("recovered", task=task.id, to=todo_of(stage)))

    async def _exclude_samba_dir(self) -> None:
        try:
            rel = self.sym.relative_to(self.layout.repo)
        except ValueError:
            return  # samba_dir outside the repo: nothing to exclude
        res = await git(self.layout.repo, "rev-parse", "--git-path", "info/exclude")
        if not res.ok:
            return
        exclude = Path(res.output.strip())
        if not exclude.is_absolute():
            exclude = self.layout.repo / exclude
        entry = f"/{rel.as_posix()}/"
        existing = exclude.read_text() if exclude.exists() else ""
        if entry not in existing.splitlines() and f"{rel.as_posix()}/" not in existing.splitlines():
            exclude.parent.mkdir(parents=True, exist_ok=True)
            sep = "" if not existing or existing.endswith("\n") else "\n"
            exclude.write_text(existing + sep + entry + "\n")

    # ---- loop ---------------------------------------------------------------------------

    async def run(self, exit_when_idle: bool = False) -> None:
        await self.startup()
        log.info(kv("started", repo=self.layout.repo, max_concurrent=self.policy.max_concurrent))
        try:
            while True:
                await self.tick()
                if exit_when_idle and not self.running and not self.ticker.runnable_todo():
                    await self.cleanup_workspaces()
                    log.info(kv("idle_exit"))
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
            log.info(kv("stopped", task=task_id, reason=reason))
            if reason == "shutdown":
                self.machine.fire(TaskId(task_id), "recover", message="stopped by shutdown")
            elif reason == "moved" and self._status(task_id) in (None, "done", "discarded"):
                with contextlib.suppress(WorkspaceError):
                    await self.workspaces.remove(task_id)
        except Exception as e:  # a bug in Samba itself: do not lose the task
            log.exception(kv("worker_crashed", task=task_id, error=e))
            task = self.tasks.get(TaskId(task_id))
            if task is not None:
                await self._fail(task, f"internal error: {e}")

    async def _work(self, task_id: str) -> None:
        task = self.tasks.get(TaskId(task_id))
        if task is None:
            return
        try:
            ws, created = await self.workspaces.ensure(task_id)
        except WorkspaceError as e:
            await self._fail(task, str(e))
            return
        if created:
            log.info(kv("workspace_created", task=task_id, path=ws))
        task.workspace = str(ws)
        task.branch = branch_name(task_id)
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

        async def validate() -> tuple[bool, str]:
            return await self._validate(task, ws)

        result = await self.turns.run(task, setup, validate, on_turn)
        if isinstance(result, Fail):
            await self._fail(task, result.error)
        else:
            await self._finish(task, result.event, result.what, result.summary)

    def _setup(self, task: Task, ws: Path, stage: Stage) -> TurnSetup:
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
                stage="plan", system_prompt=system_prompt, location=str(ws),
                prompt=self._prompt("plan_revise", variables) if resume else first,
                resume=resume, first_prompt=first, continue_prompt="",
                validate_failed=lambda tail: "", max_turns=1, validate_enabled=False,
                max_cost_usd=cap)
        first = render(self.prompts.template, variables)
        resume = bool(task.session_id)
        failed = self._prompt("validate_failed", variables)
        return TurnSetup(
            stage="work", system_prompt=self._system_prompt(variables, task), location=str(ws),
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

    async def _validate(self, task: Task, ws: Path) -> tuple[bool, str]:
        val = self.validation
        assert val.command
        task_id = task.id
        res = await run_shell(val.shell, val.command, ws, val.timeout_s)
        out_path = self.runs_dir / task_id / f"validate-{task.turns_total:03d}.log"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(res.output)
        lines = res.output.rstrip().splitlines()
        tail = "\n".join(lines[-val.tail_lines:])
        if res.timed_out:
            tail = (tail + "\n" if tail else "") + f"(timed out after {val.timeout_s}s)"
        log.info(kv("validate", task=task_id, ok=res.ok, code=res.code))
        return res.ok, tail

    # ---- transitions --------------------------------------------------------------------

    async def _finish(self, task: Task, event: str, what: str, summary: str = "") -> None:
        msg = f"{what} (turns {task.turns_total}, ${task.cost_usd_total:.2f})"
        if summary:
            msg += f": {summary}"
        moved = self.machine.fire(task.id, event, task=task, message=msg)
        log.info(kv("finished", task=task.id, transition=event, moved=moved))

    async def _fail(self, task: Task, error: str) -> None:
        policy = self.policy
        task_id = task.id
        stage = stage_of(task)
        decision = RetryPolicy(policy.max_attempts, policy.retry_base_s,
                               policy.max_retry_backoff_s).decide(task.attempts)
        attempts = decision.attempts
        log.warning(kv("attempt_failed", task=task_id, attempt=attempts, error=error))
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
                ws = Path(task.workspace or self.workspaces.path(task_id))
                variables = self._variables(task, ws)
                await self.turns.invoke(
                    task, stage="work", prompt=self._prompt("give_up", variables),
                    resume=True, system_prompt=self._system_prompt(variables, task),
                    location=str(ws), max_cost_usd=policy.max_cost_usd_per_task)
        self.machine.fire(task_id, "give_up", task=task, error=error,
                          message=f"gave up after {attempts} failed attempts: {error}")

    # ---- helpers ------------------------------------------------------------------------

    def _variables(self, task: Task, ws: Path) -> dict[str, str]:
        return {
            "task.id": task.id,
            "task.title": task.title,
            "task.body": task.body,
            "task.path": self.tasks.location(task.id),
            "workspace": str(ws),
            "branch": branch_name(task.id),
            "base_branch": self.layout.base_branch,
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

