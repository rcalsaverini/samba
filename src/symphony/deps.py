"""Task dependencies: the guard behind `dispatch_plan` and `dispatch_work` (SPEC §15)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from symphony.tasks import Task, TaskStore


@dataclass(frozen=True)
class DepStatus:
    kind: Literal["ready", "waiting", "discarded", "cycle"]
    waiting: tuple[str, ...] = ()  # ids not yet in `done` (includes unknown ids)
    unknown: tuple[str, ...] = ()  # ids with no task file anywhere


def _in_cycle(store: TaskStore, task: Task) -> bool:
    """True if `task` can reach itself through `depends_on` edges of tasks that are not done."""
    seen: set[str] = set()
    stack = list(task.depends_on)
    while stack:
        dep_id = stack.pop()
        if dep_id == task.id:
            return True
        if dep_id in seen:
            continue
        seen.add(dep_id)
        dep = store.find(dep_id)
        if dep is not None and dep.state != "done":
            stack.extend(dep.depends_on)
    return False


def evaluate(store: TaskStore, task: Task) -> DepStatus:
    if not task.depends_on:
        return DepStatus("ready")
    if _in_cycle(store, task):
        return DepStatus("cycle")
    waiting: list[str] = []
    unknown: list[str] = []
    discarded = False
    for dep_id in task.depends_on:
        state = store.state_of(dep_id)
        if state == "done":
            continue
        waiting.append(dep_id)
        if state is None:
            unknown.append(dep_id)
        elif state == "discarded":
            discarded = True
    if discarded:
        return DepStatus("discarded", tuple(waiting), tuple(unknown))
    if waiting:
        return DepStatus("waiting", tuple(waiting), tuple(unknown))
    return DepStatus("ready")
