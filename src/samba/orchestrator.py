"""The poll loop, dispatch, and per-task workers (spec: orchestrator)."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from samba.adapters.claude_cli import ClaudeCliRunner
from samba.adapters.markdown_tasks import MarkdownTasks
from samba.adapters.system import SystemClock, UuidGenerator
from samba.app.machine import Machine
from samba.app.turn import TurnFlow, TurnSetup
from samba.config import Config
from samba.domain.policy import Fail, Retry, RetryPolicy, should_reflect
from samba.logfmt import kv
from samba.ports import AgentRunner, Clock, IdGenerator, StoreError, Tasks
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
from samba.domain.transitions import human_row, log_line
from samba.lock import repo_lock
from samba.template import TemplateError, render
from samba.workspace import WorkspaceError, Workspaces, branch_name

log = logging.getLogger("samba")

StopReason = Literal["moved", "shutdown"]


class StartupError(Exception):
    pass


def stage_of(task: Task) -> Stage:
    return "plan" if task.last_stage == "plan" else "work"


@dataclass
class Running:
    task: asyncio.Task[None]
    started_at: float
    folder: State  # the running folder the task was claimed into
    turn: int = 0
    stop_reason: StopReason | None = None


class Orchestrator:
    def __init__(self, config: Config, clock: Clock | None = None,
                 ids: IdGenerator | None = None, agent: AgentRunner | None = None,
                 tasks: Tasks | None = None) -> None:
        self.config = config
        self.clock: Clock = clock or SystemClock()
        self.ids: IdGenerator = ids or UuidGenerator()
        self.sym = config.samba_dir
        self.tasks: Tasks = tasks or MarkdownTasks(self.sym / "tasks", self.sym / "state",
                                                    self.clock)
        self.runs_dir = self.sym / "runs"
        self.agent: AgentRunner = agent or ClaudeCliRunner(
            config.claude, config.planning, (self.sym / "tasks").resolve(), self.runs_dir,
            config.repo)
        self.workspaces = Workspaces(config)
        self.turns = TurnFlow(self.agent, self.ids, self.tasks, self.clock)
        self.running: dict[str, Running] = {}
        self.warned_invalid: set[str] = set()
        self.warned_deps: set[tuple[str, str]] = set()
        self.machine = Machine(self.tasks, self.clock, self._guard)
        self.pending_notes: dict[str, list[str]] = {}  # `## Log` lines held while an agent runs
        self.held: dict[str, tuple[str, ...]] = {}  # todo tasks waiting on dependencies

    def _guard(self, name: str, task: Task) -> bool:
        if name == "plan_required":
            return self.config.planning.require_plan and not task.plan_approved
        if name == "deps_met":
            return evaluate(deps_snapshot(task, self.tasks.get), task.id).kind == "ready"
        return False

    def _status(self, task_id: str) -> State | None:
        task = self.tasks.get(TaskId(task_id))
        return task.status if task is not None else None

    def _append_log(self, task_id: str, line: str) -> None:
        task = self.tasks.get(TaskId(task_id))
        if task is not None:
            task.add_log(line)
            self.tasks.save(task)

    # ---- startup ------------------------------------------------------------------------

    async def startup(self) -> None:
        cfg = self.config
        try:
            self.tasks.prepare()
        except StoreError as e:
            raise StartupError(str(e)) from e
        top = await git(cfg.repo, "rev-parse", "--show-toplevel")
        if not top.ok or Path(top.output.strip()).resolve() != cfg.repo:
            raise StartupError(f"{cfg.repo} is not the root of a git repository")
        base = await git(cfg.repo, "rev-parse", "--verify", "--quiet",
                         f"refs/heads/{cfg.base_branch}")
        if not base.ok:
            raise StartupError(f"base_branch '{cfg.base_branch}' does not exist")
        readiness = await self.agent.ready()
        if not readiness.ok:
            raise StartupError(
                f"claude auth status says not logged in; run `claude auth login`. {readiness.detail}")
        for w in cfg.warnings:
            log.warning(kv("config_warning", message=w))

        self.runs_dir.mkdir(parents=True, exist_ok=True)
        await self._exclude_samba_dir()

        for stage in ("plan", "work"):
            for task in self.tasks.list(running_of(stage)):
                if self.machine.fire(task.id, "recover", message="recovered at startup"):
                    log.info(kv("recovered", task=task.id, to=todo_of(stage)))

    async def _exclude_samba_dir(self) -> None:
        try:
            rel = self.sym.relative_to(self.config.repo)
        except ValueError:
            return  # samba_dir outside the repo: nothing to exclude
        res = await git(self.config.repo, "rev-parse", "--git-path", "info/exclude")
        if not res.ok:
            return
        exclude = Path(res.output.strip())
        if not exclude.is_absolute():
            exclude = self.config.repo / exclude
        entry = f"/{rel.as_posix()}/"
        existing = exclude.read_text() if exclude.exists() else ""
        if entry not in existing.splitlines() and f"{rel.as_posix()}/" not in existing.splitlines():
            exclude.parent.mkdir(parents=True, exist_ok=True)
            sep = "" if not existing or existing.endswith("\n") else "\n"
            exclude.write_text(existing + sep + entry + "\n")

    # ---- loop ---------------------------------------------------------------------------

    async def run(self, exit_when_idle: bool = False) -> None:
        await self.startup()
        log.info(kv("started", repo=self.config.repo, max_concurrent=self.config.max_concurrent))
        try:
            while True:
                await self.tick()
                if exit_when_idle and not self.running and not self._runnable_todo():
                    await self.cleanup_workspaces()
                    log.info(kv("idle_exit"))
                    return
                await asyncio.sleep(self.config.poll_interval_s)
        finally:
            await self.shutdown()

    def _runnable_todo(self) -> list[str]:
        """Todo tasks that will run eventually: not held only by dependencies (spec: cli)."""
        return [tid for status in ("plan-todo", "work-todo") for tid in self.tasks.ids(status)
                if tid not in self.held]

    async def tick(self) -> None:
        # A state-changing command holds the repo lock for its whole rename + sidecar + log
        # sequence (spec: task-files, Write discipline). Skip the tick while it does: observe() would misread the half-done
        # move as a hand move, and dispatch could claim the task before the command saved.
        with repo_lock(self.sym, blocking=False) as held:
            if not held:
                log.debug(kv("tick_skipped", reason="repo lock held"))
                return
            self.observe()
            self.reconcile()
            await self.cleanup_workspaces()
            self.dispatch()

    def _note(self, task_id: str, line: str) -> None:
        """Append to `## Log`, or hold the line until the agent stops (spec: task-files, Write discipline)."""
        if task_id in self.running:
            self.pending_notes.setdefault(task_id, []).append(line)
        else:
            self._append_log(task_id, line)

    def observe(self) -> None:
        """Interpret hand moves: a task in another status than the store last knew (spec: states)."""
        for move in self.tasks.observe_moves():
            task = self.tasks.get(move.task_id)
            if task is None:
                continue
            row = human_row(move.src, move.dst, task)
            if row is not None:
                self._note(move.task_id, self.machine.observe(move, row, task))
                continue
            if not self.tasks.revert_move(move):
                continue
            log.warning(kv("illegal_move", task=move.task_id, src=move.src, dst=move.dst))
            self._note(move.task_id, log_line(
                f"illegal move: {move.src} -> {move.dst}, moved back to {move.src}", self.clock))

    def reconcile(self) -> None:
        for task_id, entry in list(self.running.items()):
            status = self._status(task_id)
            if entry.stop_reason is None and status != entry.folder:
                entry.stop_reason = "moved"
                entry.task.cancel()
                log.info(kv("stopping", task=task_id, reason=f"task file left {entry.folder}/",
                            now=status or "deleted"))

    async def cleanup_workspaces(self) -> None:
        for task_id in self.workspaces.existing_ids():
            if task_id in self.running:
                continue
            state = self._status(task_id)
            if state in (None, "done", "discarded"):
                try:
                    await self.workspaces.remove(task_id)
                    log.info(kv("workspace_removed", task=task_id))
                except WorkspaceError as e:
                    log.warning(kv("workspace_remove_failed", task=task_id, error=e))

    def dispatch(self) -> None:
        for status in ("plan-todo", "work-todo"):
            for name in self.tasks.rejected_names(status):
                if name not in self.warned_invalid:
                    self.warned_invalid.add(name)
                    log.warning(kv("invalid_task_name", file=name,
                                   hint="use only letters, digits, '.', '_' and '-'"))
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
            if len(self.running) >= self.config.max_concurrent:
                break
            if task.status == "work-todo":
                self.machine.fire(task.id, "route_to_plan", task=task)  # to plan-todo, if it applies
            if not self.machine.fire(task.id, "dispatch_plan" if task.status == "plan-todo"
                                     else "dispatch_work", task=task):
                continue
            stage = stage_of(task)
            running_folder = running_of(stage)
            log.info(kv("dispatch", task=task.id, attempt=task.attempts, stage=stage,
                        resume=bool(task.plan_session_id if stage == "plan"
                                    else task.session_id)))
            worker = asyncio.create_task(self.work(task.id))
            self.running[task.id] = Running(task=worker, started_at=self.clock.monotonic(),
                                            folder=running_folder)
            worker.add_done_callback(functools.partial(self._on_worker_done, task.id))

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
                    log.warning(kv("unknown_dependency", task=task.id, dependency=dep_id))
        return False

    def _on_worker_done(self, task_id: str, _worker: asyncio.Task[None]) -> None:
        self.running.pop(task_id, None)
        lines = self.pending_notes.pop(task_id, [])
        task = self.tasks.get(TaskId(task_id)) if lines else None
        if task is not None:
            for line in lines:
                task.add_log(line)
            self.tasks.save(task)

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
        cfg = self.config
        variables = self._variables(task, ws)
        cap = cfg.max_cost_usd_per_task
        if stage == "plan":
            system_prompt = render(PLAN_PROTOCOL, {
                **variables,
                "allowed_tools": allowed_tools_note(cfg.planning.allow, "dontAsk"),
            })
            first = self._first_plan_prompt(variables)
            resume = bool(task.plan_session_id)
            return TurnSetup(
                stage="plan", system_prompt=system_prompt, location=str(ws),
                prompt=self._prompt("plan_revise", variables) if resume else first,
                resume=resume, first_prompt=first, continue_prompt="",
                validate_failed=lambda tail: "", max_turns=1, validate_enabled=False,
                max_cost_usd=cap)
        first = render(cfg.prompt_template, variables)
        resume = bool(task.session_id)
        failed = self._prompt("validate_failed", variables)
        return TurnSetup(
            stage="work", system_prompt=self._system_prompt(variables, task), location=str(ws),
            prompt=self._prompt("resume", variables) if resume else first, resume=resume,
            first_prompt=first, continue_prompt=self._prompt("continue", variables),
            validate_failed=lambda tail: failed + "\n\n```\n" + tail + "\n```",
            max_turns=cfg.max_turns, validate_enabled=bool(cfg.validate_command),
            max_cost_usd=cap)

    def _first_plan_prompt(self, variables: dict[str, str]) -> str:
        override = self.config.prompts.get("plan")
        if override:
            return render(override, variables)
        return render(self.config.prompt_template, variables) + "\n\n" + DEFAULT_PROMPTS["plan"]

    async def _validate(self, task: Task, ws: Path) -> tuple[bool, str]:
        cfg = self.config
        assert cfg.validate_command
        task_id = task.id
        res = await run_shell(cfg.shell, cfg.validate_command, ws, cfg.validate_timeout_s)
        out_path = self.runs_dir / task_id / f"validate-{task.turns_total:03d}.log"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(res.output)
        lines = res.output.rstrip().splitlines()
        tail = "\n".join(lines[-cfg.validate_tail_lines:])
        if res.timed_out:
            tail = (tail + "\n" if tail else "") + f"(timed out after {cfg.validate_timeout_s}s)"
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
        cfg = self.config
        task_id = task.id
        stage = stage_of(task)
        decision = RetryPolicy(cfg.max_attempts, cfg.retry_base_s,
                               cfg.max_retry_backoff_s).decide(task.attempts)
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
        if should_reflect(cfg.reflect_on_give_up, task.session_id, stage, in_running):
            with contextlib.suppress(TemplateError):
                ws = Path(task.workspace or self.workspaces.path(task_id))
                variables = self._variables(task, ws)
                await self.turns.invoke(
                    task, stage="work", prompt=self._prompt("give_up", variables),
                    resume=True, system_prompt=self._system_prompt(variables, task),
                    location=str(ws), max_cost_usd=cfg.max_cost_usd_per_task)
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
            "base_branch": self.config.base_branch,
            "attempt": str(task.attempts),
            "validate_command": self.config.validate_command or "",
            # The answered round, for the first run after a question (spec: prompts, Which prompt is sent).
            "questions": (round_pairs(task.questions)
                          if task.last_outcome == "blocked" and not open_questions(task.questions)
                          else ""),
        }

    def _system_prompt(self, variables: dict[str, str], task: Task) -> str:
        cfg = self.config
        text = render(PROTOCOL, {
            **variables,
            "validate_note": validate_note(cfg.validate_command),
            "allowed_tools": allowed_tools_note(cfg.claude.allow, cfg.claude.permission_mode),
        })
        if task.plan_approved:
            text = text.rstrip("\n") + "\n" + APPROVED_PLAN_RULE
        return text

    def _prompt(self, key: str, variables: dict[str, str]) -> str:
        template = self.config.prompts.get(key) or DEFAULT_PROMPTS[key]
        text = render(template, variables).rstrip()
        questions = variables.get("questions", "")
        # A custom prompt without {{ questions }} must not lose the answers.
        if key in ("resume", "plan_revise") and questions and "questions" not in re.findall(
                r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}", template):
            text += "\n\n" + questions
        return text

