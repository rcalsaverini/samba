"""The poll loop, dispatch, and per-task workers (spec: orchestrator)."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from samba.claude import Invocation, RunResult, logged_in, run_claude
from samba.config import Config
from samba.proc import git, run_shell
from samba.prompts import (
    APPROVED_PLAN_RULE,
    DEFAULT_PROMPTS,
    PLAN_PROTOCOL,
    PROTOCOL,
    allowed_tools_note,
    validate_note,
)
from samba.deps import evaluate
from samba.lock import repo_lock
from samba.tasks import (
    STATES,
    Sidecar,
    SidecarStore,
    Stage,
    State,
    Task,
    TaskStore,
    add_questions,
    open_questions,
    round_pairs,
    running_of,
    todo_of,
)
from samba.template import TemplateError, render
from samba.transitions import Machine, human_row, kv, log_line
from samba.workspace import WorkspaceError, Workspaces, branch_name

log = logging.getLogger("samba")

StopReason = Literal["moved", "shutdown"]
STATE_BY_NAME: dict[str, State] = {s: s for s in STATES}

# Where a task file of an old-layout folder goes (spec: orchestrator, Startup). Shown in the refusal message.
LEGACY_MOVES: dict[str, str] = {
    "plan": "plan-todo",
    "todo": "work-todo",
    "running": "work-todo   (plan-todo for tasks that were being planned)",
    "review": "work-review",
    "blocked": "question    (stuck for tasks that failed or hit the budget)",
}


class StartupError(Exception):
    pass


def stage_of(side: Sidecar) -> Stage:
    return "plan" if side.last_stage == "plan" else "work"


@dataclass
class Running:
    task: asyncio.Task[None]
    started_at: float
    folder: State  # the running folder the task was claimed into
    turn: int = 0
    stop_reason: StopReason | None = None


class Orchestrator:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.sym = config.samba_dir
        self.tasks = TaskStore(self.sym / "tasks")
        self.sidecars = SidecarStore(self.sym / "state")
        self.runs_dir = self.sym / "runs"
        self.workspaces = Workspaces(config)
        self.running: dict[str, Running] = {}
        self.logged_init = False
        self.warned_invalid: set[str] = set()
        self.warned_deps: set[tuple[str, str]] = set()
        self.machine = Machine(self.tasks, self.sidecars, self._guard)
        self.pending_notes: dict[str, list[str]] = {}  # `## Log` lines held while an agent runs
        self.held: dict[str, tuple[str, ...]] = {}  # todo tasks waiting on dependencies

    def _guard(self, name: str, task_id: str, side: Sidecar) -> bool:
        if name == "plan_required":
            return self.config.planning.require_plan and not side.plan_approved
        if name == "deps_met":
            task = self.tasks.find(task_id)
            return task is not None and evaluate(self.tasks, task).kind == "ready"
        return False

    # ---- startup ------------------------------------------------------------------------

    def _refuse_legacy_layout(self) -> None:
        old = self.tasks.legacy_nonempty()
        if not old:
            return
        root = self.tasks.root
        lines = [f"old task folders still hold tasks: {', '.join(old)}. Move them to the new "
                 "layout (spec: layout), then start again:", f"  mkdir -p {root}/work-todo "
                 f"{root}/plan-todo {root}/work-review {root}/question {root}/stuck"]
        for folder in old:
            lines.append(f"  mv {root}/{folder}/*.md {root}/{LEGACY_MOVES[folder]}")
        raise StartupError("\n".join(lines))

    async def startup(self) -> None:
        cfg = self.config
        self._refuse_legacy_layout()
        top = await git(cfg.repo, "rev-parse", "--show-toplevel")
        if not top.ok or Path(top.output.strip()).resolve() != cfg.repo:
            raise StartupError(f"{cfg.repo} is not the root of a git repository")
        base = await git(cfg.repo, "rev-parse", "--verify", "--quiet",
                         f"refs/heads/{cfg.base_branch}")
        if not base.ok:
            raise StartupError(f"base_branch '{cfg.base_branch}' does not exist")
        ok, detail = await logged_in(cfg.claude, cfg.repo)
        if not ok:
            raise StartupError(
                f"claude auth status says not logged in; run `claude auth login`. {detail}")
        for w in cfg.warnings:
            log.warning(kv("config_warning", message=w))

        self.tasks.ensure()
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
        return [tid for folder in ("plan-todo", "work-todo") for tid in self.tasks.ids(folder)
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
            self.tasks.append_log(task_id, line)

    def observe(self) -> None:
        """Interpret hand moves: a task in another folder than its sidecar `state` (spec: states)."""
        for folder in STATES:
            for task_id in self.tasks.ids(folder):
                side = self.sidecars.load(task_id)
                src = STATE_BY_NAME.get(side.state or "")
                if src is None:
                    side.state = folder  # first sight: record, fire nothing
                    self.sidecars.save(task_id, side)
                    continue
                if src == folder:
                    continue
                row = human_row(src, folder, side)
                if row is not None:
                    self._note(task_id, self.machine.observe(task_id, row, side))
                    continue
                if self.tasks.path(task_id, src).exists() or not self.tasks.move(task_id, folder,
                                                                                 src):
                    continue
                log.warning(kv("illegal_move", task=task_id, src=src, dst=folder))
                self._note(task_id, log_line(
                    f"illegal move: {src} -> {folder}, moved back to {src}"))

    def reconcile(self) -> None:
        for task_id, entry in list(self.running.items()):
            if entry.stop_reason is None and self.tasks.state_of(task_id) != entry.folder:
                entry.stop_reason = "moved"
                entry.task.cancel()
                log.info(kv("stopping", task=task_id, reason=f"task file left {entry.folder}/",
                            now=self.tasks.state_of(task_id) or "deleted"))

    async def cleanup_workspaces(self) -> None:
        for task_id in self.workspaces.existing_ids():
            if task_id in self.running:
                continue
            state = self.tasks.state_of(task_id)
            if state in (None, "done", "discarded"):
                try:
                    await self.workspaces.remove(task_id)
                    log.info(kv("workspace_removed", task=task_id))
                except WorkspaceError as e:
                    log.warning(kv("workspace_remove_failed", task=task_id, error=e))

    def dispatch(self) -> None:
        for folder in ("plan-todo", "work-todo"):
            for name in self.tasks.invalid_names(folder):
                if name not in self.warned_invalid:
                    self.warned_invalid.add(name)
                    log.warning(kv("invalid_task_name", file=name,
                                   hint="use only letters, digits, '.', '_' and '-'"))
        now = time.time()
        self.held = {}
        candidates: list[tuple[Task, Sidecar, State]] = []
        for folder in ("plan-todo", "work-todo"):
            for task in self.tasks.list(folder):
                if task.id in self.running or not self._deps_ready(task):
                    continue
                side = self.sidecars.load(task.id)
                if side.not_before is not None and side.not_before > now:
                    continue
                candidates.append((task, side, folder))
        candidates.sort(key=lambda c: (c[0].priority is None, c[0].priority or 0,
                                       c[0].mtime, c[0].id))
        for task, side, folder in candidates:
            if len(self.running) >= self.config.max_concurrent:
                break
            if folder == "work-todo" and self.machine.fire(task.id, "route_to_plan", side=side):
                folder = "plan-todo"
            if not self.machine.fire(task.id, "dispatch_plan" if folder == "plan-todo"
                                     else "dispatch_work", side=side):
                continue
            stage = stage_of(side)
            running_folder = running_of(stage)
            log.info(kv("dispatch", task=task.id, attempt=side.attempts, stage=stage,
                        resume=bool(side.plan_session_id if stage == "plan"
                                    else side.session_id)))
            worker = asyncio.create_task(self.work(task.id))
            self.running[task.id] = Running(task=worker, started_at=time.monotonic(),
                                            folder=running_folder)
            worker.add_done_callback(functools.partial(self._on_worker_done, task.id))

    def _deps_ready(self, task: Task) -> bool:
        """The dependency guard of the dispatch rows (spec: dependencies). Fires the stuck rows."""
        status = evaluate(self.tasks, task)
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
        for line in self.pending_notes.pop(task_id, []):
            self.tasks.append_log(task_id, line)

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
                self.machine.fire(task_id, "recover", message="stopped by shutdown")
            elif reason == "moved" and self.tasks.state_of(task_id) in (None, "done",
                                                                        "discarded"):
                with contextlib.suppress(WorkspaceError):
                    await self.workspaces.remove(task_id)
        except Exception as e:  # a bug in Samba itself: do not lose the task
            log.exception(kv("worker_crashed", task=task_id, error=e))
            side = self.sidecars.load(task_id)
            await self._fail(task_id, side, f"internal error: {e}")

    async def _work(self, task_id: str) -> None:
        cfg = self.config
        side = self.sidecars.load(task_id)
        try:
            ws, created = await self.workspaces.ensure(task_id)
        except WorkspaceError as e:
            await self._fail(task_id, side, str(e))
            return
        if created:
            log.info(kv("workspace_created", task=task_id, path=ws))
        side.workspace = str(ws)
        side.branch = branch_name(task_id)
        self.sidecars.save(task_id, side)

        task = self.tasks.find(task_id)
        if task is None:
            return
        if stage_of(side) == "plan":
            await self._plan(task, side, ws)
            return
        try:
            variables = self._variables(task, ws, side)
            system_prompt = self._system_prompt(variables, side)
            if side.session_id:
                prompt, resume = self._prompt("resume", variables), True
            else:
                prompt, resume = render(cfg.prompt_template, variables), False
        except TemplateError as e:
            await self._fail(task_id, side, str(e))
            return

        for turn in range(1, cfg.max_turns + 1):
            entry = self.running.get(task_id)
            if entry:
                entry.turn = turn
            if self._budget_left(side) is not None and (self._budget_left(side) or 0) <= 0:
                await self._finish(task_id, side, "budget",
                                   f"budget exceeded (${side.cost_usd_total:.2f})")
                return
            res = await self._invoke(task_id, side, ws, prompt, resume, system_prompt)
            if res.session_missing:
                log.info(kv("session_missing", task=task_id))
                side.session_id = None
                prompt, resume = render(cfg.prompt_template, variables), False
                res = await self._invoke(task_id, side, ws, prompt, resume, system_prompt)
            for denial in res.denials:
                self.tasks.append_log(task_id, log_line(f"permission denied: {denial}"))
            if not res.ok:
                await self._fail(task_id, side, res.error())
                return
            left = self._budget_left(side)
            if left is not None and left <= 0:
                await self._finish(task_id, side, "budget",
                                   f"budget exceeded (${side.cost_usd_total:.2f})", res.summary)
                return

            outcome = res.outcome
            if outcome is None:
                log.warning(kv("no_structured_output", task=task_id))
            log.info(kv("turn_end", task=task_id, turn=turn, outcome=outcome or "missing",
                        cost=f"{res.cost_usd:.4f}"))
            if outcome == "done":
                if not cfg.validate_command:
                    await self._finish(task_id, side, "done", "done", res.summary)
                    return
                ok, tail = await self._validate(task_id, side, ws)
                if ok:
                    await self._finish(task_id, side, "done", "validation passed", res.summary)
                    return
                prompt = self._prompt("validate_failed", variables) + "\n\n```\n" + tail + "\n```"
            elif outcome == "blocked":
                self._ask(task_id, side, "work", res)
                await self._finish(task_id, side, "work_blocked", "blocked", res.summary)
                return
            else:
                prompt = self._prompt("continue", variables)
            resume = True

        await self._fail(task_id, side, f"max_turns ({cfg.max_turns}) exhausted")

    async def _plan(self, task: Task, side: Sidecar, ws: Path) -> None:
        """One planning invocation (spec: planning, The planning run)."""
        cfg = self.config
        task_id = task.id
        try:
            variables = self._variables(task, ws, side)
            system_prompt = render(PLAN_PROTOCOL, {
                **variables,
                "allowed_tools": allowed_tools_note(cfg.planning.allow, "dontAsk"),
            })
            first = self._first_plan_prompt(variables)
            if side.plan_session_id:
                prompt, resume = self._prompt("plan_revise", variables), True
            else:
                prompt, resume = first, False
        except TemplateError as e:
            await self._fail(task_id, side, str(e))
            return
        entry = self.running.get(task_id)
        if entry:
            entry.turn = 1
        left = self._budget_left(side)
        if left is not None and left <= 0:
            await self._finish(task_id, side, "budget",
                               f"budget exceeded (${side.cost_usd_total:.2f})")
            return
        res = await self._invoke(task_id, side, ws, prompt, resume, system_prompt, planning=True)
        if res.session_missing:
            log.info(kv("session_missing", task=task_id))
            side.plan_session_id = None
            res = await self._invoke(task_id, side, ws, first, False, system_prompt,
                                     planning=True)
        for denial in res.denials:
            self.tasks.append_log(task_id, log_line(f"permission denied: {denial}"))
        if not res.ok:
            await self._fail(task_id, side, res.error())
            return
        left = self._budget_left(side)
        if left is not None and left <= 0:
            await self._finish(task_id, side, "budget",
                               f"budget exceeded (${side.cost_usd_total:.2f})", res.summary)
            return
        outcome = res.outcome
        log.info(kv("turn_end", task=task_id, turn=1, outcome=outcome or "missing",
                    cost=f"{res.cost_usd:.4f}"))
        if outcome not in ("planned", "blocked") or not res.plan_text:
            await self._fail(task_id, side, "planning run returned no valid outcome and plan")
            return
        self.tasks.set_section(task_id, "Plan", res.plan_text)
        if res.assumptions:
            self.tasks.set_section(task_id, "Assumptions", res.assumptions)
        if outcome == "planned":
            await self._finish(task_id, side, "planned", "planned", res.summary)
        else:
            self._ask(task_id, side, "plan", res)
            await self._finish(task_id, side, "plan_blocked", "blocked", res.summary)

    def _first_plan_prompt(self, variables: dict[str, str]) -> str:
        override = self.config.prompts.get("plan")
        if override:
            return render(override, variables)
        return render(self.config.prompt_template, variables) + "\n\n" + DEFAULT_PROMPTS["plan"]

    def _running_folder(self, task_id: str) -> State:
        return running_of(stage_of(self.sidecars.load(task_id)))

    async def _invoke(self, task_id: str, side: Sidecar, ws: Path, prompt: str, resume: bool,
                      system_prompt: str, planning: bool = False) -> RunResult:
        session = side.plan_session_id if planning else side.session_id
        if not resume or not session:
            session = str(uuid.uuid4())
            resume = False
        if planning:
            side.plan_session_id = session
        else:
            side.session_id = session
        side.turns_total += 1
        self.sidecars.save(task_id, side)
        inv = Invocation(prompt=prompt, session_id=session, resume=resume,
                         tasks_dir=self.tasks.root.resolve(), system_prompt=system_prompt,
                         max_budget_usd=self._budget_left(side),
                         planning=self.config.planning if planning else None)
        stream_log = self.runs_dir / task_id / f"{side.turns_total:03d}.jsonl"
        log.info(kv("turn_start", task=task_id, n=side.turns_total, resume=resume,
                    session=session, phase="plan" if planning else None))
        res = await run_claude(self.config.claude, inv, ws, stream_log)
        side.cost_usd_total += res.cost_usd
        tin, tout = res.tokens()
        side.input_tokens_total += tin
        side.output_tokens_total += tout
        self.sidecars.save(task_id, side)
        if res.init and not self.logged_init:
            self.logged_init = True
            init = res.init
            log.info(kv("claude_context", permission_mode=init.get("permissionMode"),
                        skills=len(init.get("skills") or []),
                        plugins=len(init.get("plugins") or []),
                        mcp_servers=len(init.get("mcp_servers") or [])))
        if res.malformed_lines:
            log.warning(kv("malformed_lines", task=task_id, count=res.malformed_lines))
        if res.stderr.strip():
            log.debug(kv("claude_stderr", task=task_id, text=res.stderr.strip()[-2000:]))
        return res

    async def _validate(self, task_id: str, side: Sidecar, ws: Path) -> tuple[bool, str]:
        cfg = self.config
        assert cfg.validate_command
        res = await run_shell(cfg.shell, cfg.validate_command, ws, cfg.validate_timeout_s)
        out_path = self.runs_dir / task_id / f"validate-{side.turns_total:03d}.log"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(res.output)
        lines = res.output.rstrip().splitlines()
        tail = "\n".join(lines[-cfg.validate_tail_lines:])
        if res.timed_out:
            tail = (tail + "\n" if tail else "") + f"(timed out after {cfg.validate_timeout_s}s)"
        log.info(kv("validate", task=task_id, ok=res.ok, code=res.code))
        return res.ok, tail

    # ---- transitions --------------------------------------------------------------------

    async def _finish(self, task_id: str, side: Sidecar, event: str, what: str,
                      summary: str = "") -> None:
        msg = f"{what} (turns {side.turns_total}, ${side.cost_usd_total:.2f})"
        if summary:
            msg += f": {summary}"
        moved = self.machine.fire(task_id, event, side=side, message=msg)
        log.info(kv("finished", task=task_id, transition=event, moved=moved))

    async def _fail(self, task_id: str, side: Sidecar, error: str) -> None:
        cfg = self.config
        attempts = side.attempts + 1
        log.warning(kv("attempt_failed", task=task_id, attempt=attempts, error=error))
        if attempts < cfg.max_attempts:
            delay = min(cfg.retry_base_s * 2 ** (attempts - 1), cfg.max_retry_backoff_s)
            self.machine.fire(
                task_id, "retry_plan" if stage_of(side) == "plan" else "retry_work", side=side,
                message=f"attempt {attempts} failed: {error}; retry in {delay:.0f}s",
                error=error, delay=delay)
            return

        if (cfg.reflect_on_give_up and side.session_id and stage_of(side) != "plan"
                and self.tasks.state_of(task_id) == self._running_folder(task_id)):
            task = self.tasks.find(task_id)
            if task is not None:
                with contextlib.suppress(TemplateError):
                    ws = Path(side.workspace or self.workspaces.path(task_id))
                    variables = self._variables(task, ws, side)
                    await self._invoke(task_id, side, ws, self._prompt("give_up", variables),
                                       True, self._system_prompt(variables, side))
        self.machine.fire(task_id, "give_up", side=side, error=error,
                          message=f"gave up after {attempts} failed attempts: {error}")

    # ---- helpers ------------------------------------------------------------------------

    def _variables(self, task: Task, ws: Path, side: Sidecar) -> dict[str, str]:
        return {
            "task.id": task.id,
            "task.title": task.title,
            "task.body": task.body,
            "task.path": str(self.tasks.path(task.id, running_of(stage_of(side))).resolve()),
            "workspace": str(ws),
            "branch": branch_name(task.id),
            "base_branch": self.config.base_branch,
            "attempt": str(side.attempts),
            "validate_command": self.config.validate_command or "",
            # The answered round, for the first run after a question (spec: prompts, Which prompt is sent).
            "questions": (round_pairs(side.questions)
                          if side.last_outcome == "blocked" and not open_questions(side.questions)
                          else ""),
        }

    def _system_prompt(self, variables: dict[str, str], side: Sidecar) -> str:
        cfg = self.config
        text = render(PROTOCOL, {
            **variables,
            "validate_note": validate_note(cfg.validate_command),
            "allowed_tools": allowed_tools_note(cfg.claude.allow, cfg.claude.permission_mode),
        })
        if side.plan_approved:
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

    def _ask(self, task_id: str, side: Sidecar, stage: str, res: RunResult) -> None:
        """Record the questions of a blocked run (spec: states, Questions). A blocked run without a valid
        question (for example a permission denial) gets one synthesized from its summary."""
        items = res.question_items
        if not items:
            context = "Samba synthesized this question: the agent reported blocked without one."
            if res.denials:
                context += " Permission denied: " + ", ".join(res.denials) + "."
            items = [(res.summary or "The agent reported blocked without a question", context)]
        add_questions(side.questions, stage, items)
        self.tasks.render_questions(task_id, side.questions)

    def _budget_left(self, side: Sidecar) -> float | None:
        cap = self.config.max_cost_usd_per_task
        return None if cap is None else cap - side.cost_usd_total
