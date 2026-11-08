"""Command line: `symphony run | status | new` (SPEC §11)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import signal
import sys
import time
from pathlib import Path

from symphony.config import Config, ConfigError, load_config
from symphony.deps import evaluate
from symphony.orchestrator import Orchestrator, StartupError
from symphony.prompts import TASK_TEMPLATE
from symphony.tasks import STATES, SidecarStore, TaskStore
from symphony.transitions import render_markdown_table


def _setup_logging(config: Config) -> None:
    config.symphony_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger("symphony")
    root.setLevel(logging.DEBUG)
    file_handler = logging.FileHandler(config.symphony_dir / "symphony.log")
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    console.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console)


def cmd_run(config: Config, exit_when_idle: bool) -> int:
    _setup_logging(config)
    orch = Orchestrator(config)

    async def main() -> None:
        loop = asyncio.get_running_loop()
        current = asyncio.current_task()
        assert current is not None
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, current.cancel)
        await orch.run(exit_when_idle=exit_when_idle)

    try:
        asyncio.run(main())
    except StartupError as e:
        print(f"symphony: {e}", file=sys.stderr)
        return 1
    except asyncio.CancelledError:
        print("symphony: stopped", file=sys.stderr)
    return 0


def cmd_status(config: Config) -> int:
    tasks = TaskStore(config.symphony_dir / "tasks")
    sidecars = SidecarStore(config.symphony_dir / "state")
    rows: list[list[str]] = [["ID", "STATE", "ATTEMPTS", "TURNS", "COST", "LAST", "ERROR"]]
    now = time.time()
    for state in STATES:
        for task in tasks.list(state):
            s = sidecars.load(task.id)
            last = s.last_outcome or "-"
            if state in ("plan-todo", "work-todo"):
                if s.not_before and s.not_before > now:
                    last += f" (retry in {s.not_before - now:.0f}s)"
                else:
                    dep = evaluate(tasks, task)
                    if dep.kind == "waiting":
                        last = f"waiting on {', '.join(dep.waiting)}"
            shown = state
            if state in ("question", "stuck") and s.blocked_cause:
                shown = f"{state} ({s.blocked_cause})"
            rows.append([task.id, shown, str(s.attempts), str(s.turns_total),
                         f"${s.cost_usd_total:.2f}", last, (s.last_error or "")[:60]])
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
    return 0


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60].strip("-") or "task"


def cmd_new(config: Config, title: str, priority: int | None, plan: bool = False) -> int:
    tasks = TaskStore(config.symphony_dir / "tasks")
    tasks.ensure()
    base = slugify(title)
    task_id, n = base, 2
    while tasks.state_of(task_id) is not None:
        task_id, n = f"{base}-{n}", n + 1
    front = f"---\npriority: {priority}\n---\n" if priority is not None else ""
    path = tasks.path(task_id, "plan-todo" if plan else "work-todo")
    path.write_text(TASK_TEMPLATE.format(front=front, title=title))
    print(path)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="symphony")
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run", help="run the orchestrator loop")
    p_run.add_argument("--exit-when-idle", action="store_true",
                       help="exit once nothing is running and plan-todo/ and work-todo/ are empty")
    p_status = sub.add_parser("status", help="show tasks and their state")
    p_new = sub.add_parser("new", help="create a task in work-todo/")
    p_new.add_argument("title")
    p_new.add_argument("--priority", type=int)
    p_new.add_argument("--plan", action="store_true", help="create the task in plan-todo/ instead")
    p_trans = sub.add_parser("transitions",
                             help="print the transition table as Markdown (SPEC §4.1)")
    for p in (p_run, p_status, p_new, p_trans):
        p.add_argument("--repo", type=Path, default=Path.cwd(),
                       help="repository root (default: current directory)")
    args = parser.parse_args(argv)

    if args.command == "transitions":
        print(render_markdown_table())
        return 0

    try:
        config = load_config(args.repo)
    except ConfigError as e:
        print(f"symphony: config error: {e}", file=sys.stderr)
        return 2

    if args.command == "run":
        return cmd_run(config, args.exit_when_idle)
    if args.command == "status":
        return cmd_status(config)
    return cmd_new(config, args.title, args.priority, args.plan)
