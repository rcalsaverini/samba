"""`Machine`: the single `fire` path that moves a task (spec: states).

The table, the effects and the row helpers are pure and live in `samba.domain.transitions`. This
module is the file IO around them: the rename, the sidecar save and the `## Log` line.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable

from samba.domain.sidecar import Sidecar
from samba.domain.transitions import (
    EVENTS,
    Transition,
    apply_row,
    entry_line,
    find_row,
    stage_guard_ok,
)
from samba.logfmt import kv
from samba.ports import Clock
from samba.tasks import SidecarStore, TaskStore

log = logging.getLogger("samba")

# Test-only knob (spec: implementation-notes): seconds `fire` sleeps between the rename and the sidecar save.
DEBUG_FIRE_DELAY = float(os.environ.get("SAMBA_DEBUG_FIRE_DELAY") or 0)

GuardFn = Callable[[str, str, Sidecar], bool]  # (guard name, task id, sidecar) -> holds?


class Machine:
    """Applies table rows. `fire` is the only way Samba moves a task."""

    def __init__(self, tasks: TaskStore, sidecars: SidecarStore, clock: Clock,
                 guard: GuardFn | None = None) -> None:
        self.tasks = tasks
        self.sidecars = sidecars
        self.guard = guard
        self.clock = clock

    def _guard_holds(self, name: str, task_id: str, side: Sidecar) -> bool:
        if name.startswith("last_stage="):
            return stage_guard_ok(name, side)
        return self.guard is not None and self.guard(name, task_id, side)

    def fire(self, task_id: str, event: str, *, side: Sidecar | None = None, message: str = "",
             **ctx: object) -> bool:
        """Fire `event` for a task: rename, sidecar effects, `## Log` line. Synchronous, so no
        other tick step can observe it half done. False if no row applies to the task's current
        folder (for example a human moved the file meanwhile) or a guard fails."""
        if event not in EVENTS:
            raise KeyError(f"unknown event {event!r}")
        folder = self.tasks.state_of(task_id)
        if folder is None:
            return False
        side = side if side is not None else self.sidecars.load(task_id)
        row = find_row(event, folder, lambda g: self._guard_holds(g, task_id, side))
        if row is None:
            return False
        if not self.tasks.move(task_id, row.src, row.dst):
            return False
        if DEBUG_FIRE_DELAY:
            time.sleep(DEBUG_FIRE_DELAY)  # test-only: widens the window the repo lock covers
        changed = apply_row(row, side, ctx, self.clock)
        self.sidecars.save(task_id, side)
        if changed:  # `## Questions` is a view of the records (spec: task-files, Write discipline)
            self.tasks.render_questions(task_id, side.questions)
        self.tasks.append_log(task_id, entry_line(row, message, self.clock))
        log.info(kv("transition", task=task_id, transition=row.event, src=row.src, dst=row.dst,
                    actor=row.actor))
        return True

    def observe(self, task_id: str, row: Transition, side: Sidecar) -> str:
        """Apply a human row for a move already made by hand. Returns the `## Log` line, which
        the caller writes (or defers while an agent runs, spec: task-files, Write discipline)."""
        changed = apply_row(row, side, {}, self.clock)
        self.sidecars.save(task_id, side)
        if changed:  # the task came from question/, where no agent runs
            self.tasks.render_questions(task_id, side.questions)
        log.info(kv("transition", task=task_id, transition=row.event, src=row.src, dst=row.dst,
                    actor=row.actor, observed=True))
        return entry_line(row, "observed hand move", self.clock)
