"""`Machine`: the single `fire` path that moves a task (spec: states).

The table, the effects and the row helpers are pure and live in `samba.domain.transitions`. This
use case loads the task through the `Tasks` port, applies a row to it and saves it. Where the
status is stored, and how a lost race is detected, is the port's business.
"""

from __future__ import annotations

from collections.abc import Callable

from samba.domain.task import ObservedMove, Task
from samba.domain.task_id import TaskId
from samba.domain.transitions import (
    EVENTS,
    Transition,
    apply_row,
    entry_line,
    find_row,
    stage_guard_ok,
)
from samba.domain.ports import Clock, Journal, Tasks

GuardFn = Callable[[str, Task], bool]  # (guard name, task) -> holds?


class Machine:
    """Applies table rows. `fire` is the only way Samba moves a task."""

    def __init__(self, tasks: Tasks, clock: Clock, journal: Journal,
                 guard: GuardFn | None = None) -> None:
        self.tasks = tasks
        self.journal = journal
        self.guard = guard
        self.clock = clock

    def _guard_holds(self, name: str, task: Task) -> bool:
        if name.startswith("last_stage="):
            return stage_guard_ok(name, task)
        return self.guard is not None and self.guard(name, task)

    def fire(self, task_id: TaskId, event: str, *, task: Task | None = None, message: str = "",
             **ctx: object) -> bool:
        """Fire `event` for a task: the row's effects, the status change and the `## Log` line,
        in one `save`. `task` is the caller's working copy (the effects land on it, so its own
        unsaved changes are saved too); without it a fresh one is loaded. False if no row applies
        to the stored status (for example a human moved the file meanwhile), a guard fails or the
        save lost the race. After a False the caller must not reuse its copy."""
        if event not in EVENTS:
            raise KeyError(f"unknown event {event!r}")
        fresh = self.tasks.get(task_id)
        if fresh is None:
            return False
        target = task if task is not None else fresh
        row = find_row(event, fresh.status, lambda g: self._guard_holds(g, target))
        if row is None:
            return False
        apply_row(row, target, ctx, self.clock)
        target.add_log(entry_line(row, message, self.clock))
        if not self.tasks.save(target):
            return False
        self.journal.info("transition", task=task_id, transition=row.event, src=row.src,
                          dst=row.dst, actor=row.actor)
        return True

    def observe(self, move: ObservedMove, row: Transition, task: Task) -> str:
        """Apply the human `row` for a move already made by hand and accept the move. Returns the
        `## Log` line, which the caller writes (or defers while an agent runs, spec: task-files,
        Write discipline). `task` is freshly loaded, in the destination status."""
        apply_row(row, task, {}, self.clock)
        self.tasks.save(task)
        self.tasks.accept_move(move)
        self.journal.info("transition", task=move.task_id, transition=row.event, src=row.src,
                          dst=row.dst, actor=row.actor, observed=True)
        return entry_line(row, "observed hand move", self.clock)
