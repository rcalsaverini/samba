"""Read-only views shared by the CLI commands (spec: observability, cli): table, state and id matching, show."""

from __future__ import annotations

import time
from collections.abc import Iterable

from samba.domain.deps import deps_snapshot, evaluate
from samba.domain.questions import open_questions
from samba.domain.states import STATES, State
from samba.domain.task import Task
from samba.domain.task_id import AmbiguousTask, TaskId, UnknownTask
from samba.domain.transitions import human_events
from samba.ports import Tasks

HEADER = ["ID", "STATE", "ATTEMPTS", "TURNS", "COST", "LAST", "ERROR"]


class ResolveError(Exception):
    """A state or task id argument did not resolve. `candidates` lists the valid or close names."""

    def __init__(self, message: str, candidates: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.candidates = candidates

    def render(self) -> str:
        text = str(self)
        if self.candidates:
            text += "\n" + "\n".join(f"  {c}" for c in self.candidates)
        return text


def resolve_states(args: Iterable[str]) -> tuple[State, ...]:
    """Each argument is an exact state name or a prefix, which expands to every state it
    matches (`work` is the three work states). A prefix matching nothing is an error. Result is
    in canonical STATES order."""
    wanted: set[State] = set()
    for arg in args:
        exact: list[State] = [s for s in STATES if s == arg]
        matches: list[State] = exact or [s for s in STATES if arg and s.startswith(arg)]
        if not matches:
            raise ResolveError(f"unknown state {arg!r}; valid states:", STATES)
        wanted.update(matches)
    return tuple(s for s in STATES if s in wanted)


def resolve_task_id(tasks: Tasks, text: str) -> TaskId:
    """An exact id, else a unique prefix of an id in any status (`TaskId.resolve`)."""
    try:
        return TaskId.resolve(tasks.ids(), text)
    except UnknownTask:
        raise ResolveError(f"unknown task {text!r}") from None
    except AmbiguousTask as e:
        raise ResolveError(f"ambiguous task id {text!r}; candidates:", e.candidates) from None


def task_rows(tasks: Tasks, states: Iterable[State] = STATES) -> list[list[str]]:
    rows: list[list[str]] = [list(HEADER)]
    now = time.time()
    for state in states:
        for task in tasks.list(state):
            last = task.last_outcome or "-"
            if state in ("plan-todo", "work-todo"):
                if task.not_before and task.not_before > now:
                    last += f" (retry in {task.not_before - now:.0f}s)"
                else:
                    dep = evaluate(deps_snapshot(task, tasks.get), task.id)
                    if dep.kind == "waiting":
                        last = f"waiting on {', '.join(dep.waiting)}"
            shown = state
            if state in ("question", "stuck") and task.blocked_cause:
                shown = f"{state} ({task.blocked_cause})"
            rows.append([task.id, shown, str(task.attempts), str(task.turns_total),
                         f"${task.cost_usd_total:.2f}", last,
                         " ".join((task.last_error or "").split())])
    return rows


QUESTION_HEADER = ["TASK", "QID", "STAGE", "ASKED", "QUESTION"]


def question_rows(tasks: Tasks) -> list[list[str]]:
    """Every open question of every task. QID is the full name `<task>/<qid>`, ready to paste
    into `question answer`."""
    rows: list[list[str]] = []
    for task in tasks.list("question"):
        for q in open_questions(task.questions):
            rows.append([task.id, f"{task.id}/{q.id}", q.stage, q.asked_at[:16].replace("T", " "),
                         " ".join(q.text.split())])
    return [QUESTION_HEADER, *rows]


MIN_FLEX = 20


def print_table(rows: list[list[str]], width: int | None = None, flex: int | None = None) -> None:
    """Print left-aligned columns separated by two spaces. With `flex` (a column index), that
    column gets the room left in `width` and longer cells are cut with `...`; other columns are
    never cut. The flex column is at least MIN_FLEX wide."""
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    if flex is not None and width is not None:
        used = sum(w + 2 for i, w in enumerate(widths) if i != flex)
        room = max(width - used, MIN_FLEX)
        if widths[flex] > room:
            widths[flex] = room
            rows = [r[:flex] + [r[flex] if len(r[flex]) <= room else r[flex][:room - 3] + "..."]
                    + r[flex + 1:] for r in rows]
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())


def render_show(tasks: Tasks, task: Task) -> list[str]:
    def v(x: object) -> str:
        return "-" if x is None or x == "" else str(x)

    now = time.time()
    lines = [
        f"id: {task.id}",
        f"title: {task.title}",
        f"state: {task.status}",
        f"blocked_cause: {v(task.blocked_cause)}",
        f"priority: {v(task.priority)}",
        f"attempts: {task.attempts}",
        f"turns: {task.turns_total}",
        f"cost: ${task.cost_usd_total:.2f}",
        f"last_outcome: {v(task.last_outcome)}",
        f"last_error: {v(task.last_error)}",
    ]
    if task.not_before and task.not_before > now:
        lines.append(f"retry_in: {task.not_before - now:.0f}s")
    lines.append("depends_on:" if task.depends_on else "depends_on: -")
    for dep_id in task.depends_on:
        dep = tasks.get(dep_id)
        lines.append(f"  {dep_id} ({dep.status if dep else 'unknown'})")
    if task.depends_on and task.status in ("plan-todo", "work-todo"):
        dep_status = evaluate(deps_snapshot(task, tasks.get), task.id)
        if dep_status.kind != "ready":
            held = f" on {', '.join(dep_status.waiting)}" if dep_status.waiting else ""
            lines.append(f"dependency_status: {dep_status.kind}{held}")
    lines.append(f"open_questions: {len(open_questions(task.questions))}")
    lines += [
        f"branch: {v(task.branch)}",
        f"worktree: {v(task.workspace)}",
        f"session_id: {v(task.session_id)}",
        f"plan_session_id: {v(task.plan_session_id)}",
    ]
    events = human_events(task.status, task)
    if events:
        lines.append("events:")
        lines += [f"  {r.event} -> {r.dst}" for r in events]
    else:
        lines.append("events: (none)")
    return lines
