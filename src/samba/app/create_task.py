"""`CreateTask`: `task new` (spec: cli). Flags give every field; on a terminal the missing ones
are asked through the `Terminal` port."""

from __future__ import annotations

from dataclasses import dataclass

from samba.app.resolve import ResolveError, resolve_deps
from samba.app.results import Refused, refused, usage
from samba.domain.task import Task
from samba.domain.task_id import TaskId
from samba.ports import Clock, Tasks, Terminal

DEPENDS_PROMPT = "Depends on (ids or prefixes, comma separated, empty for none): "


@dataclass(frozen=True)
class Created:
    """Done. `location` goes to stdout."""

    task_id: TaskId
    location: str


class CreateTask:
    def __init__(self, tasks: Tasks, terminal: Terminal, clock: Clock) -> None:
        self.tasks = tasks
        self.terminal = terminal
        self.clock = clock

    def run(self, title: str | None, body: str | None, depends: str | None, priority: int,
            skip_plan: bool) -> Created | Refused:
        tasks = self.tasks
        terminal = self.terminal
        tty = terminal.is_interactive()
        if title is None and not tty:
            return usage("task new needs a TITLE (or run it on a terminal to be asked); "
                         "usage: samba task new TITLE [--body TEXT] [--depends-on IDS] "
                         "[--priority N] [--skip-plan]")
        dep_ids: list[TaskId] = []
        if depends is not None:  # by flag: errors are fatal
            try:
                dep_ids = resolve_deps(tasks, depends)
            except ResolveError as e:
                return usage(e.render())
        if tty:
            try:
                while not (title or "").strip():
                    title = terminal.ask("Title: ").strip()
                if body is None:
                    body = "\n".join(terminal.read_block("Description (end with an empty line):"))
                if depends is None:
                    while True:
                        try:
                            dep_ids = resolve_deps(tasks, terminal.ask(DEPENDS_PROMPT))
                            break
                        except ResolveError as e:
                            terminal.warn(f"samba: {e.render()}")
                if not skip_plan:
                    skip_plan = terminal.ask("Plan first? [Y/n] ").strip().lower() in ("n", "no")
            except EOFError:
                return refused("input ended; nothing created")
        assert title is not None
        title = title.strip()
        base = TaskId.slug(title)
        task_id, n = base, 2
        while tasks.get(task_id) is not None:
            task_id, n = TaskId(f"{base}-{n}"), n + 1
        tasks.create(Task.new(task_id, title, body or "", priority, tuple(dep_ids),
                              "work-todo" if skip_plan else "plan-todo", self.clock))
        return Created(task_id, tasks.location(task_id))
