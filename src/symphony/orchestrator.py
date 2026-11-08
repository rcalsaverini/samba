"""The poll loop, dispatch, and per-task workers (SPEC §5)."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from symphony.claude import Invocation, RunResult, logged_in, run_claude
from symphony.config import Config
from symphony.proc import git, run_shell
from symphony.prompts import DEFAULT_PROMPTS, PROTOCOL, allowed_tools_note, validate_note
from symphony.tasks import Sidecar, SidecarStore, State, Task, TaskStore
from symphony.template import TemplateError, render
from symphony.workspace import WorkspaceError, Workspaces, branch_name

log = logging.getLogger("symphony")

StopReason = Literal["moved", "shutdown"]


class StartupError(Exception):
    pass


def kv(event: str, **fields: object) -> str:
    parts = [f"event={event}"]
    for k, v in fields.items():
        if v is None:
            continue
        s = str(v)
        if any(c.isspace() for c in s) or "=" in s or '"' in s:
            s = '"' + s.replace('"', "'") + '"'
        parts.append(f"{k}={s}")
    return " ".join(parts)


@dataclass
class Running:
    task: asyncio.Task[None]
    started_at: float
    turn: int = 0
    stop_reason: StopReason | None = None


class Orchestrator:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.sym = config.symphony_dir
        self.tasks = TaskStore(self.sym / "tasks")
        self.sidecars = SidecarStore(self.sym / "state")
        self.runs_dir = self.sym / "runs"
        self.workspaces = Workspaces(config)
        self.running: dict[str, Running] = {}
        self.logged_init = False
        self.warned_invalid: set[str] = set()

    # ---- startup ------------------------------------------------------------------------

    async def startup(self) -> None:
        cfg = self.config
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
        await self._exclude_symphony_dir()

        for task in self.tasks.list("running"):
            if self.tasks.move(task.id, "running", "todo"):
                log.info(kv("recovered", task=task.id))

    async def _exclude_symphony_dir(self) -> None:
        try:
            rel = self.sym.relative_to(self.config.repo)
        except ValueError:
            return  # symphony_dir outside the repo: nothing to exclude
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
                if exit_when_idle and not self.running and not self.tasks.list("todo"):
                    await self.cleanup_workspaces()
                    log.info(kv("idle_exit"))
                    return
                await asyncio.sleep(self.config.poll_interval_s)
        finally:
            await self.shutdown()

    async def tick(self) -> None:
        self.reconcile()
        await self.cleanup_workspaces()
        self.dispatch()

    def reconcile(self) -> None:
        for task_id, entry in list(self.running.items()):
            if entry.stop_reason is None and self.tasks.state_of(task_id) != "running":
                entry.stop_reason = "moved"
                entry.task.cancel()
                log.info(kv("stopping", task=task_id, reason="task file left running/",
                            now=self.tasks.state_of(task_id) or "deleted"))

    async def cleanup_workspaces(self) -> None:
        for task_id in self.workspaces.existing_ids():
            if task_id in self.running:
                continue
            state = self.tasks.state_of(task_id)
            if state is None or state == "done":
                try:
                    await self.workspaces.remove(task_id)
                    log.info(kv("workspace_removed", task=task_id))
                except WorkspaceError as e:
                    log.warning(kv("workspace_remove_failed", task=task_id, error=e))

    def dispatch(self) -> None:
        for name in self.tasks.invalid_names("todo"):
            if name not in self.warned_invalid:
                self.warned_invalid.add(name)
                log.warning(kv("invalid_task_name", file=name,
                               hint="use only letters, digits, '.', '_' and '-'"))
        now = time.time()
        candidates: list[tuple[Task, Sidecar]] = []
        for task in self.tasks.list("todo"):
            if task.id in self.running:
                continue
            side = self.sidecars.load(task.id)
            if side.not_before is not None and side.not_before > now:
                continue
            candidates.append((task, side))
        candidates.sort(key=lambda ts: (ts[0].priority is None, ts[0].priority or 0,
                                        ts[0].mtime, ts[0].id))
        for task, side in candidates:
            if len(self.running) >= self.config.max_concurrent:
                break
            if not self.tasks.move(task.id, "todo", "running"):
                continue
            if side.last_outcome in ("blocked", "failed"):
                side.attempts = 0  # the human sent it back
            side.not_before = None
            if side.first_dispatched_at is None:
                side.first_dispatched_at = time.time()
            self.sidecars.save(task.id, side)
            log.info(kv("dispatch", task=task.id, attempt=side.attempts,
                        resume=bool(side.session_id)))
            worker = asyncio.create_task(self.work(task.id))
            self.running[task.id] = Running(task=worker, started_at=time.monotonic())
            worker.add_done_callback(functools.partial(self._on_worker_done, task.id))

    def _on_worker_done(self, task_id: str, _worker: asyncio.Task[None]) -> None:
        self.running.pop(task_id, None)

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
            if reason == "shutdown" and self.tasks.move(task_id, "running", "todo"):
                self.tasks.append_log(task_id, self._log_line("stopped by shutdown, back to todo"))
            elif reason == "moved" and self.tasks.state_of(task_id) in (None, "done"):
                with contextlib.suppress(WorkspaceError):
                    await self.workspaces.remove(task_id)
        except Exception as e:  # a bug in Symphony itself: do not lose the task
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
        try:
            variables = self._variables(task, ws, side)
            system_prompt = self._system_prompt(variables)
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
                await self._finish(task_id, side, "blocked", "blocked",
                                   f"budget exceeded (${side.cost_usd_total:.2f})")
                return
            res = await self._invoke(task_id, side, ws, prompt, resume, system_prompt)
            if res.session_missing:
                log.info(kv("session_missing", task=task_id))
                side.session_id = None
                prompt, resume = render(cfg.prompt_template, variables), False
                res = await self._invoke(task_id, side, ws, prompt, resume, system_prompt)
            for denial in res.denials:
                self.tasks.append_log(task_id, self._log_line(f"permission denied: {denial}"))
            if not res.ok:
                await self._fail(task_id, side, res.error())
                return
            left = self._budget_left(side)
            if left is not None and left <= 0:
                await self._finish(task_id, side, "blocked", "blocked",
                                   f"budget exceeded (${side.cost_usd_total:.2f})", res.summary)
                return

            outcome = res.outcome
            if outcome is None:
                log.warning(kv("no_structured_output", task=task_id))
            log.info(kv("turn_end", task=task_id, turn=turn, outcome=outcome or "missing",
                        cost=f"{res.cost_usd:.4f}"))
            if outcome == "done":
                if not cfg.validate_command:
                    await self._finish(task_id, side, "review", "done", "done", res.summary)
                    return
                ok, tail = await self._validate(task_id, side, ws)
                if ok:
                    await self._finish(task_id, side, "review", "done", "validation passed",
                                       res.summary)
                    return
                prompt = self._prompt("validate_failed", variables) + "\n\n```\n" + tail + "\n```"
            elif outcome == "blocked":
                await self._finish(task_id, side, "blocked", "blocked", "blocked", res.summary)
                return
            else:
                prompt = self._prompt("continue", variables)
            resume = True

        await self._fail(task_id, side, f"max_turns ({cfg.max_turns}) exhausted")

    async def _invoke(self, task_id: str, side: Sidecar, ws: Path, prompt: str, resume: bool,
                      system_prompt: str) -> RunResult:
        if not resume or not side.session_id:
            side.session_id = str(uuid.uuid4())
            resume = False
        side.turns_total += 1
        self.sidecars.save(task_id, side)
        inv = Invocation(prompt=prompt, session_id=side.session_id, resume=resume,
                         tasks_dir=self.tasks.root.resolve(), system_prompt=system_prompt,
                         max_budget_usd=self._budget_left(side))
        stream_log = self.runs_dir / task_id / f"{side.turns_total:03d}.jsonl"
        log.info(kv("turn_start", task=task_id, n=side.turns_total, resume=resume,
                    session=side.session_id))
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

    async def _finish(self, task_id: str, side: Sidecar, to: State, outcome: str, what: str,
                      summary: str = "") -> None:
        side.last_outcome = outcome
        if to == "review":
            side.attempts = 0
            side.last_error = None
        self.sidecars.save(task_id, side)
        moved = self.tasks.move(task_id, "running", to)
        msg = f"{what}, moved to {to}" if moved else what
        msg += f" (turns {side.turns_total}, ${side.cost_usd_total:.2f})"
        if summary:
            msg += f": {summary}"
        self.tasks.append_log(task_id, self._log_line(msg))
        log.info(kv("finished", task=task_id, to=to, outcome=outcome, moved=moved))

    async def _fail(self, task_id: str, side: Sidecar, error: str) -> None:
        cfg = self.config
        side.attempts += 1
        side.last_error = error
        log.warning(kv("attempt_failed", task=task_id, attempt=side.attempts, error=error))
        if side.attempts < cfg.max_attempts:
            delay = min(cfg.retry_base_s * 2 ** (side.attempts - 1), cfg.max_retry_backoff_s)
            side.not_before = time.time() + delay
            side.last_outcome = "retrying"
            self.sidecars.save(task_id, side)
            moved = self.tasks.move(task_id, "running", "todo")
            if moved:
                self.tasks.append_log(task_id, self._log_line(
                    f"attempt {side.attempts} failed: {error}; retry in {delay:.0f}s"))
            return

        if cfg.reflect_on_give_up and side.session_id and self.tasks.state_of(task_id) == "running":
            task = self.tasks.find(task_id)
            if task is not None:
                with contextlib.suppress(TemplateError):
                    ws = Path(side.workspace or self.workspaces.path(task_id))
                    variables = self._variables(task, ws, side)
                    await self._invoke(task_id, side, ws, self._prompt("give_up", variables),
                                       True, self._system_prompt(variables))
        side.last_outcome = "failed"
        self.sidecars.save(task_id, side)
        moved = self.tasks.move(task_id, "running", "blocked")
        if moved:
            self.tasks.append_log(task_id, self._log_line(
                f"gave up after {side.attempts} failed attempts: {error}; moved to blocked"))

    # ---- helpers ------------------------------------------------------------------------

    def _variables(self, task: Task, ws: Path, side: Sidecar) -> dict[str, str]:
        return {
            "task.id": task.id,
            "task.title": task.title,
            "task.body": task.body,
            "task.path": str(self.tasks.path(task.id, "running").resolve()),
            "workspace": str(ws),
            "branch": branch_name(task.id),
            "base_branch": self.config.base_branch,
            "attempt": str(side.attempts),
            "validate_command": self.config.validate_command or "",
        }

    def _system_prompt(self, variables: dict[str, str]) -> str:
        cfg = self.config
        return render(PROTOCOL, {
            **variables,
            "validate_note": validate_note(cfg.validate_command),
            "allowed_tools": allowed_tools_note(cfg.claude.allow, cfg.claude.permission_mode),
        })

    def _prompt(self, key: str, variables: dict[str, str]) -> str:
        return render(self.config.prompts.get(key) or DEFAULT_PROMPTS[key], variables)

    def _budget_left(self, side: Sidecar) -> float | None:
        cap = self.config.max_cost_usd_per_task
        return None if cap is None else cap - side.cost_usd_total

    @staticmethod
    def _log_line(message: str) -> str:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        return f"- {stamp} symphony: {message}"
