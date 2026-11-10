"""Task dependencies: the guard behind `dispatch_plan` and `dispatch_work` (spec: orchestrator, Dependencies).

Pure: `evaluate` reads a snapshot of the tasks, it never touches a store.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from samba.domain.states import State
from samba.domain.task import Task
from samba.domain.task_id import TaskId


@dataclass(frozen=True)
class DepStatus:
    kind: Literal["ready", "waiting", "discarded", "cycle"]
    waiting: tuple[str, ...] = ()  # ids not yet in `done` (includes unknown ids)
    unknown: tuple[str, ...] = ()  # ids with no task file anywhere


@dataclass(frozen=True)
class TaskRef:
    """What dependency evaluation needs to know about a task."""
    id: str
    status: State
    depends_on: tuple[str, ...] = ()


Snapshot = Mapping[str, TaskRef]  # task id -> ref; an id that is absent is an unknown task


def deps_snapshot(task: Task, get: Callable[[TaskId], Task | None]) -> dict[str, TaskRef]:
    """The task and everything reachable through `depends_on`, for `evaluate`. Ids `get` does not
    know are left out (unknown). A done task's own dependencies are not followed: they cannot
    take part in a cycle."""
    snap: dict[str, TaskRef] = {task.id: TaskRef(task.id, task.status, task.depends_on)}
    stack = list(task.depends_on)
    while stack:
        dep_id = stack.pop()
        if dep_id in snap:
            continue
        dep = get(dep_id)
        if dep is None:
            continue
        snap[dep_id] = TaskRef(dep.id, dep.status, dep.depends_on)
        if dep.status != "done":
            stack.extend(dep.depends_on)
    return snap


def _in_cycle(snapshot: Snapshot, task: TaskRef) -> bool:
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
        dep = snapshot.get(dep_id)
        if dep is not None and dep.status != "done":
            stack.extend(dep.depends_on)
    return False


def evaluate(snapshot: Snapshot, task_id: str) -> DepStatus:
    task = snapshot[task_id]
    if not task.depends_on:
        return DepStatus("ready")
    if _in_cycle(snapshot, task):
        return DepStatus("cycle")
    waiting: list[str] = []
    unknown: list[str] = []
    discarded = False
    for dep_id in task.depends_on:
        dep = snapshot.get(dep_id)
        if dep is not None and dep.status == "done":
            continue
        waiting.append(dep_id)
        if dep is None:
            unknown.append(dep_id)
        elif dep.status == "discarded":
            discarded = True
    if discarded:
        return DepStatus("discarded", tuple(waiting), tuple(unknown))
    if waiting:
        return DepStatus("waiting", tuple(waiting), tuple(unknown))
    return DepStatus("ready")
