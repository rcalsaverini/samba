"""The Claude Code CLI as an AgentRunner (spec: running-claude).

The only module that reads Claude's stream-json. It maps one run into an `AgentReport`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from samba.config import AgentSettings
from samba.domain.agent import (
    AgentReport,
    AgentRequest,
    Failure,
    Outcome,
    QuestionDraft,
    Readiness,
)
from samba.domain.ports import Journal
from samba.proc import kill_group, run_cmd
from samba.prompts import OUTCOME_SCHEMA_JSON, PLAN_OUTCOME_SCHEMA_JSON

LINE_LIMIT = 10 * 1024 * 1024
STDERR_KEEP = 20_000

MEMORY_FILE_NAMES = ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md", ".claude/CLAUDE.local.md")


def ancestor_memory_files(cwd: Path) -> list[str]:
    """CLAUDE.md paths in every parent directory of `cwd` (spec: running-claude, User config isolation).

    Claude Code loads these from each ancestor of its working directory, outside the reach of
    `--setting-sources`. A worktree under the home directory would otherwise load the user's own
    `~/.claude/CLAUDE.md`. The worktree's own files are not listed, so the repo's CLAUDE.md loads.
    """
    return [str(parent / name) for parent in cwd.resolve().parents for name in MEMORY_FILE_NAMES]


def build_argv(cfg: AgentSettings, req: AgentRequest, tasks_dir: Path, cwd: Path) -> list[str]:
    # The prompt comes right after -p: several flags below are variadic and would swallow a
    # positional argument placed after them.
    argv = [*cfg.command, "-p", req.prompt, "--output-format", "stream-json", "--verbose"]
    argv += ["--resume", req.session_id] if req.resume else ["--session-id", req.session_id]
    argv += ["--add-dir", str(tasks_dir)]
    argv += ["--append-system-prompt", req.system_prompt]
    plan = req.kind == "plan"
    argv += ["--json-schema", PLAN_OUTCOME_SCHEMA_JSON if plan else OUTCOME_SCHEMA_JSON]
    argv += ["--permission-mode", "dontAsk" if plan else cfg.permission_mode]
    allow = cfg.planning_allow if plan else cfg.allow
    if allow:
        argv += ["--allowedTools", *allow]
    model = (cfg.planning_model or cfg.model) if plan else cfg.model
    if model:
        argv += ["--model", model]
    if req.max_budget_usd is not None:
        argv += ["--max-budget-usd", f"{req.max_budget_usd:.4f}"]
    if cfg.isolate_user_config:
        argv += ["--setting-sources", "project,local", "--strict-mcp-config"]
        excludes = {"claudeMdExcludes": ancestor_memory_files(cwd)}
        argv += ["--settings", json.dumps(excludes, separators=(",", ":"))]
    argv += cfg.args
    return argv


@dataclass
class _RunResult:
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
    def outcome(self) -> Outcome:
        structured = (self.result or {}).get("structured_output")
        if isinstance(structured, dict):
            value = cast(dict[str, Any], structured).get("outcome")
            if value == "done" or value == "blocked" or value == "continue" or value == "planned":
                return value
        return "missing"

    def structured_text(self, key: str) -> str:
        structured = (self.result or {}).get("structured_output")
        if isinstance(structured, dict):
            value = cast(dict[str, Any], structured).get(key)
            if isinstance(value, str):
                return value
        return ""

    @property
    def question_items(self) -> tuple[QuestionDraft, ...]:
        """The `questions` of the outcome. Malformed entries are dropped."""
        structured = (self.result or {}).get("structured_output")
        raw = cast(dict[str, Any], structured).get("questions") if isinstance(structured, dict) else None
        items: list[QuestionDraft] = []
        if isinstance(raw, list):
            for item in cast(list[object], raw):
                if not isinstance(item, dict):
                    continue
                d = cast(dict[str, Any], item)
                text, context = d.get("text"), d.get("context")
                if isinstance(text, str) and text.strip():
                    items.append(QuestionDraft(
                        text.strip(), context.strip() if isinstance(context, str) else ""))
        return tuple(items)

    def failure(self) -> Failure | None:
        if self.ok:
            return None
        if self.stalled:
            return Failure("stalled", "agent stalled (no output)")
        if self.timed_out:
            return Failure("timeout", "turn timeout")
        if self.result is None:
            tail = self.stderr.strip().splitlines()[-1:] or [""]
            return Failure(
                "error", f"claude exited {self.exit_code} without a result {tail[0][:200]}".strip())
        if self.result.get("is_error"):
            text = self.result.get("result")
            return Failure("error", f"claude reported an error: {str(text)[:300]}")
        return Failure("error", f"claude exited {self.exit_code}")


def _to_report(res: _RunResult) -> AgentReport:
    tin, tout = res.tokens()
    summary = " ".join(res.structured_text("summary").split())
    return AgentReport(
        outcome=res.outcome,
        summary=summary,
        plan=res.structured_text("plan").strip(),
        assumptions=res.structured_text("assumptions").strip(),
        questions=res.question_items,
        denials=tuple(res.denials),
        cost_usd=res.cost_usd,
        input_tokens=tin,
        output_tokens=tout,
        failure=res.failure(),
        session_missing=res.session_missing,
    )


class ClaudeCliRunner:
    """Runs `claude -p` per request. Stream logs go to `<runs_dir>/<request.log_name>.jsonl`."""

    def __init__(self, cfg: AgentSettings, tasks_dir: Path,
                 runs_dir: Path, check_dir: Path, journal: Journal) -> None:
        self.journal = journal
        self.cfg = cfg
        self.tasks_dir = tasks_dir
        self.runs_dir = runs_dir
        self.check_dir = check_dir
        self._logged_init = False

    async def run(self, request: AgentRequest) -> AgentReport:
        cwd = Path(request.location)
        stream_log = self.runs_dir / f"{request.log_name}.jsonl"
        argv = build_argv(self.cfg, request, self.tasks_dir, cwd)
        res = await _run_claude(self.cfg, argv, cwd, stream_log)
        task = request.log_name.split("/", 1)[0]
        if res.init and not self._logged_init:
            self._logged_init = True
            init = res.init
            self.journal.info("claude_context", permission_mode=init.get("permissionMode"),
                              skills=len(init.get("skills") or []),
                              plugins=len(init.get("plugins") or []),
                              mcp_servers=len(init.get("mcp_servers") or []))
        if res.malformed_lines:
            self.journal.warning("malformed_lines", task=task, count=res.malformed_lines)
        if res.stderr.strip():
            self.journal.debug("claude_stderr", task=task, text=res.stderr.strip()[-2000:])
        return _to_report(res)

    async def ready(self) -> Readiness:
        res = await run_cmd([*self.cfg.command, "auth", "status"], self.check_dir, timeout=60)
        try:
            raw: Any = json.loads(res.output)
            if isinstance(raw, dict) and cast(dict[str, Any], raw).get("loggedIn") is True:
                return Readiness(True)
        except ValueError:
            pass
        return Readiness(False, res.output.strip()[:500])


async def _run_claude(cfg: AgentSettings, argv: list[str], cwd: Path, stream_log: Path) -> _RunResult:
    """Run one Claude process. Cancelling the coroutine kills the process group."""
    res = _RunResult()
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
        with stream_log.open("ab") as log_file:
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
                log_file.write(line)
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


def _handle_line(line: bytes, res: _RunResult) -> None:
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
