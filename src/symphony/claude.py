"""Run Claude Code headless and read its stream-json output (SPEC §9)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from symphony.config import ClaudeConfig, PlanningConfig
from symphony.proc import kill_group, run_cmd
from symphony.prompts import OUTCOME_SCHEMA_JSON, PLAN_OUTCOME_SCHEMA_JSON

Outcome = Literal["done", "blocked", "continue", "planned"]
LINE_LIMIT = 10 * 1024 * 1024
STDERR_KEEP = 20_000


@dataclass(frozen=True)
class Invocation:
    prompt: str
    session_id: str
    resume: bool
    tasks_dir: Path
    system_prompt: str
    max_budget_usd: float | None
    planning: PlanningConfig | None = None  # set for a planning run (SPEC §14.4)


def build_argv(cfg: ClaudeConfig, inv: Invocation) -> list[str]:
    # The prompt comes right after -p: several flags below are variadic and would swallow a
    # positional argument placed after them.
    argv = [*cfg.command, "-p", inv.prompt, "--output-format", "stream-json", "--verbose"]
    argv += ["--resume", inv.session_id] if inv.resume else ["--session-id", inv.session_id]
    argv += ["--add-dir", str(inv.tasks_dir)]
    argv += ["--append-system-prompt", inv.system_prompt]
    plan = inv.planning
    argv += ["--json-schema", PLAN_OUTCOME_SCHEMA_JSON if plan else OUTCOME_SCHEMA_JSON]
    argv += ["--permission-mode", "dontAsk" if plan else cfg.permission_mode]
    allow = plan.allow if plan else cfg.allow
    if allow:
        argv += ["--allowedTools", *allow]
    model = (plan.model or cfg.model) if plan else cfg.model
    if model:
        argv += ["--model", model]
    if inv.max_budget_usd is not None:
        argv += ["--max-budget-usd", f"{inv.max_budget_usd:.4f}"]
    if cfg.isolate_user_config:
        argv += ["--setting-sources", "project,local", "--strict-mcp-config"]
    argv += cfg.args
    return argv


@dataclass
class RunResult:
    exit_code: int | None = None
    init: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    timed_out: bool = False
    stalled: bool = False
    stderr: str = ""
    malformed_lines: int = 0
    events: int = 0
    duration_s: float = 0.0
    denials: list[str] = field(default_factory=lambda: [])

    @property
    def is_error(self) -> bool:
        return self.result is None or bool(self.result.get("is_error"))

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.is_error and not self.timed_out and not self.stalled

    @property
    def session_missing(self) -> bool:
        return (self.result is not None
                and self.result.get("subtype") == "error_during_execution"
                and "No conversation found" in self.stderr)

    @property
    def cost_usd(self) -> float:
        value = (self.result or {}).get("total_cost_usd")
        return float(value) if isinstance(value, (int, float)) else 0.0

    def tokens(self) -> tuple[int, int]:
        usage = (self.result or {}).get("usage")
        if not isinstance(usage, dict):
            return 0, 0
        u = cast(dict[str, Any], usage)
        i, o = u.get("input_tokens"), u.get("output_tokens")
        return (i if isinstance(i, int) else 0, o if isinstance(o, int) else 0)

    @property
    def outcome(self) -> Outcome | None:
        structured = (self.result or {}).get("structured_output")
        if isinstance(structured, dict):
            value = cast(dict[str, Any], structured).get("outcome")
            if value == "done" or value == "blocked" or value == "continue" or value == "planned":
                return value
        return None

    def _structured_text(self, key: str) -> str:
        structured = (self.result or {}).get("structured_output")
        if isinstance(structured, dict):
            value = cast(dict[str, Any], structured).get(key)
            if isinstance(value, str):
                return value
        return ""

    @property
    def plan_text(self) -> str:
        return self._structured_text("plan").strip()

    @property
    def questions(self) -> str:
        return self._structured_text("questions").strip()

    @property
    def summary(self) -> str:
        structured = (self.result or {}).get("structured_output")
        if isinstance(structured, dict):
            value = cast(dict[str, Any], structured).get("summary")
            if isinstance(value, str):
                return " ".join(value.split())
        return ""

    def error(self) -> str:
        if self.stalled:
            return "agent stalled (no output)"
        if self.timed_out:
            return "turn timeout"
        if self.result is None:
            tail = self.stderr.strip().splitlines()[-1:] or [""]
            return f"claude exited {self.exit_code} without a result {tail[0][:200]}".strip()
        if self.result.get("is_error"):
            text = self.result.get("result")
            return f"claude reported an error: {str(text)[:300]}"
        return f"claude exited {self.exit_code}"


async def run_claude(cfg: ClaudeConfig, inv: Invocation, cwd: Path, stream_log: Path) -> RunResult:
    """Run one Claude invocation. Cancelling the coroutine kills the process group."""
    argv = build_argv(cfg, inv)
    res = RunResult()
    started = time.monotonic()
    stream_log.parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, start_new_session=True, limit=LINE_LIMIT)
    assert proc.stdout is not None and proc.stderr is not None
    stderr_stream = proc.stderr
    stderr_chunks: list[bytes] = []

    async def drain_stderr() -> None:
        while chunk := await stderr_stream.read(65536):
            stderr_chunks.append(chunk)

    stderr_task = asyncio.create_task(drain_stderr())
    deadline = started + cfg.turn_timeout_s
    try:
        with stream_log.open("ab") as log:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    res.timed_out = True
                    break
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(),
                                                  min(remaining, cfg.stall_timeout_s))
                except asyncio.TimeoutError:
                    if time.monotonic() >= deadline:
                        res.timed_out = True
                    else:
                        res.stalled = True
                    break
                except ValueError:  # line longer than LINE_LIMIT
                    res.malformed_lines += 1
                    continue
                if not line:
                    break
                log.write(line)
                _handle_line(line, res)
        if res.timed_out or res.stalled:
            await kill_group(proc)
        else:
            try:
                await asyncio.wait_for(proc.wait(), 30)
            except asyncio.TimeoutError:
                await kill_group(proc)
        res.exit_code = proc.returncode
    finally:
        await kill_group(proc)
        with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(stderr_task, 5)
        res.stderr = b"".join(stderr_chunks).decode(errors="replace")[-STDERR_KEEP:]
        res.duration_s = time.monotonic() - started
    return res


def _handle_line(line: bytes, res: RunResult) -> None:
    try:
        raw: Any = json.loads(line)
    except ValueError:
        res.malformed_lines += 1
        return
    if not isinstance(raw, dict):
        res.malformed_lines += 1
        return
    event = cast(dict[str, Any], raw)
    res.events += 1
    if event.get("type") == "system" and event.get("subtype") == "init":
        res.init = event
    elif event.get("type") == "result":
        res.result = event
        denials = event.get("permission_denials")
        if isinstance(denials, list):
            for d in cast(list[Any], denials):
                if isinstance(d, dict):
                    entry = cast(dict[str, Any], d)
                    tool = str(entry.get("tool_name", "?"))
                    tool_input = entry.get("tool_input")
                    detail = ""
                    if isinstance(tool_input, dict):
                        ti = cast(dict[str, Any], tool_input)
                        cmd = ti.get("command") or ti.get("file_path")
                        if cmd:
                            detail = f" ({str(cmd)[:120]})"
                    res.denials.append(tool + detail)


async def logged_in(cfg: ClaudeConfig, cwd: Path) -> tuple[bool, str]:
    res = await run_cmd([*cfg.command, "auth", "status"], cwd, timeout=60)
    try:
        raw: Any = json.loads(res.output)
        if isinstance(raw, dict) and cast(dict[str, Any], raw).get("loggedIn") is True:
            return True, ""
    except ValueError:
        pass
    return False, res.output.strip()[:500]
