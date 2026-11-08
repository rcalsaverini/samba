"""Command line: `symphony run | status | new | task list|show | list | show` (SPEC §11)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import signal
import sys
from pathlib import Path
from typing import cast

from symphony.config import Config, ConfigError, load_config
from symphony.orchestrator import Orchestrator, StartupError
from symphony.prompts import TASK_TEMPLATE
from symphony.tasks import STATES, SidecarStore, TaskStore
from symphony.transitions import render_markdown_table
from symphony.views import ResolveError, print_table, render_show, resolve_states, resolve_task_id, task_rows


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


def cmd_task_list(config: Config, states: list[str]) -> int:
    """`task list [STATE...]`; `status` is the same with no filter."""
    try:
        chosen = resolve_states(states) if states else STATES
    except ResolveError as e:
        print(f"symphony: {e.render()}", file=sys.stderr)
        return 2
    tasks = TaskStore(config.symphony_dir / "tasks")
    sidecars = SidecarStore(config.symphony_dir / "state")
    print_table(task_rows(tasks, sidecars, chosen))
    return 0


def cmd_task_show(config: Config, text: str) -> int:
    tasks = TaskStore(config.symphony_dir / "tasks")
    sidecars = SidecarStore(config.symphony_dir / "state")
    try:
        task = tasks.find(resolve_task_id(tasks, text))
    except ResolveError as e:
        print(f"symphony: {e.render()}", file=sys.stderr)
        return 2
    if task is None:
        print(f"symphony: unknown task {text!r}", file=sys.stderr)
        return 2
    print("\n".join(render_show(tasks, task, sidecars.load(task.id))))
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
    p_status = sub.add_parser("status", help="show tasks and their state (task list, no filter)")

    def add_list_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("states", nargs="*", metavar="STATE",
                       help="state names or unique prefixes (default: all)")

    def add_show_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("id", help="task id or unique prefix")

    p_list = sub.add_parser("list", help="alias of `task list`")
    add_list_args(p_list)
    p_show = sub.add_parser("show", help="alias of `task show`")
    add_show_args(p_show)
    p_task = sub.add_parser("task", help="task commands: list, show")
    task_sub = p_task.add_subparsers(dest="task_command", required=True)
    p_tlist = task_sub.add_parser("list", help="list tasks, optionally filtered by state")
    add_list_args(p_tlist)
    p_tshow = task_sub.add_parser("show", help="show one task in detail")
    add_show_args(p_tshow)
    p_new = sub.add_parser("new", help="create a task in work-todo/")
    p_new.add_argument("title")
    p_new.add_argument("--priority", type=int)
    p_new.add_argument("--plan", action="store_true", help="create the task in plan-todo/ instead")
    p_trans = sub.add_parser("transitions",
                             help="print the transition table as Markdown (SPEC §4.1)")
    for p in (p_run, p_status, p_new, p_trans, p_list, p_show, p_tlist, p_tshow):
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
    command = str(args.command)
    if command == "task":
        command = str(args.task_command)
    if command == "status":
        return cmd_task_list(config, [])
    if command == "list":
        return cmd_task_list(config, cast(list[str], args.states))
    if command == "show":
        return cmd_task_show(config, str(args.id))
    return cmd_new(config, args.title, args.priority, args.plan)
