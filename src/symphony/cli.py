"""Command line: `symphony run | status | new | task list|show | list | show` (SPEC §11)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

from symphony.config import Config, ConfigError, load_config
from symphony.lock import repo_lock
from symphony.orchestrator import Orchestrator, StartupError
from symphony.prompts import TASK_TEMPLATE
from symphony.tasks import STATES, SidecarStore, State, TaskStore
from symphony.transitions import Machine, human_events, render_markdown_table
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


def _edit_feedback() -> str | None:
    """Collect text in `$EDITOR` (then `$VISUAL`, then `vi`). None if the editor failed."""
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "feedback.md"
        path.write_text("")
        try:
            res = subprocess.run([*shlex.split(editor), str(path)])
        except OSError as e:
            print(f"symphony: cannot run editor {editor!r}: {e}", file=sys.stderr)
            return None
        if res.returncode != 0:
            print(f"symphony: editor exited with {res.returncode}; nothing changed",
                  file=sys.stderr)
            return None
        return path.read_text().strip()


def cmd_transition(config: Config, text: str, event: str, label: str, *,
                   feedback: str | None = None, edit: bool = False,
                   takes_feedback: bool = False) -> int:
    """The command pattern (SPEC §11): resolve, check the event is legal, do the outside effect
    (feedback text), then `Machine.fire`. Nothing else moves a task. Holds the repo lock."""
    tasks = TaskStore(config.symphony_dir / "tasks")
    sidecars = SidecarStore(config.symphony_dir / "state")

    def legal(task_id: str) -> State | None:
        """The task's state if `event` is legal there, else report and return None."""
        state = tasks.state_of(task_id)
        if state is None:
            print(f"symphony: task {task_id!r} has no file", file=sys.stderr)
            return None
        events = [r.event for r in human_events(state, sidecars.load(task_id))]
        if event in events:
            return state
        names = ", ".join(events) or "none"
        print(f"symphony: {task_id} is in {state}; {label} not allowed. Legal events: {names}",
              file=sys.stderr)
        return None

    try:
        task_id = resolve_task_id(tasks, text)
    except ResolveError as e:
        print(f"symphony: {e.render()}", file=sys.stderr)
        return 2
    if legal(task_id) is None:
        return 1
    if takes_feedback and edit:  # before the lock: editing can take long
        feedback = _edit_feedback()
        if feedback is None:
            return 1
    feedback = (feedback or "").strip()
    if takes_feedback and not feedback:
        print("warning: rejecting without feedback", file=sys.stderr)

    with repo_lock(config.symphony_dir) as held:
        if not held:
            print("symphony: another command or the orchestrator holds .symphony/lock; "
                  "try again", file=sys.stderr)
            return 1
        if legal(task_id) is None:  # re-check: a hand move may have raced in
            return 1
        tasks.ensure()  # the destination folder may not exist yet
        message = ""
        if feedback:
            n = tasks.append_feedback(task_id, feedback)
            message = f"feedback round {n}"
        if not Machine(tasks, sidecars).fire(task_id, event, message=message):
            note = "; the feedback was already written" if feedback else ""
            print(f"symphony: {event} did not apply to {task_id}{note}", file=sys.stderr)
            return 1
    state = tasks.state_of(task_id)
    if state is not None:
        print(tasks.path(task_id, state))
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

    def add_reject_args(p: argparse.ArgumentParser, fresh: bool = False) -> None:
        p.add_argument("id", help="task id or unique prefix")
        group = p.add_mutually_exclusive_group()
        group.add_argument("--feedback", metavar="TEXT", help="feedback for the agent")
        group.add_argument("--edit", action="store_true", help="write the feedback in $EDITOR")
        if fresh:
            p.add_argument("--fresh", action="store_true",
                           help="also clear the session so rework starts a fresh conversation")

    p_plan = sub.add_parser("plan", help="plan review commands: accept, reject")
    plan_sub = p_plan.add_subparsers(dest="plan_command", required=True)
    p_pacc = plan_sub.add_parser("accept", help="approve the plan; the task goes to work-todo")
    p_pacc.add_argument("id", help="task id or unique prefix")
    p_prej = plan_sub.add_parser("reject", help="send the plan back; the task goes to plan-todo")
    add_reject_args(p_prej)
    p_work = sub.add_parser("work", help="work review commands: reject")
    work_sub = p_work.add_subparsers(dest="work_command", required=True)
    p_wrej = work_sub.add_parser("reject", help="send the work back; the task goes to work-todo")
    add_reject_args(p_wrej, fresh=True)
    for p in (p_run, p_status, p_new, p_trans, p_list, p_show, p_tlist, p_tshow, p_pacc, p_prej,
              p_wrej):
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
    if command == "plan":
        verb = str(args.plan_command)
        return cmd_transition(config, str(args.id), f"plan.{verb}", f"plan.{verb}",
                              feedback=cast(str | None, getattr(args, "feedback", None)),
                              edit=bool(getattr(args, "edit", False)),
                              takes_feedback=verb == "reject")
    if command == "work":
        fresh = bool(args.fresh)
        return cmd_transition(config, str(args.id), "work.reject_fresh" if fresh else "work.reject",
                              "work.reject", feedback=cast(str | None, args.feedback),
                              edit=bool(args.edit), takes_feedback=True)
    if command == "task":
        command = str(args.task_command)
    if command == "status":
        return cmd_task_list(config, [])
    if command == "list":
        return cmd_task_list(config, cast(list[str], args.states))
    if command == "show":
        return cmd_task_show(config, str(args.id))
    return cmd_new(config, args.title, args.priority, args.plan)
