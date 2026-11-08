"""Read-only views shared by the CLI commands (SPEC §10, §11): table, state and id matching, show."""

from __future__ import annotations

import time
from collections.abc import Iterable

from symphony.deps import evaluate
from symphony.tasks import (
    STATES,
    Sidecar,
    SidecarStore,
    State,
    Task,
    TaskStore,
    open_questions,
    qstr,
)
from symphony.transitions import human_events

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


def resolve_task_id(store: TaskStore, text: str) -> str:
    """An exact id, else a unique prefix of an id in any state folder."""
    if store.state_of(text) is not None:
        return text
    ids = sorted({i for s in STATES for i in store.ids(s) if text and i.startswith(text)})
    if len(ids) == 1:
        return ids[0]
    if not ids:
        raise ResolveError(f"unknown task {text!r}")
    raise ResolveError(f"ambiguous task id {text!r}; candidates:", tuple(ids))


def task_rows(tasks: TaskStore, sidecars: SidecarStore,
              states: Iterable[State] = STATES) -> list[list[str]]:
    rows: list[list[str]] = [list(HEADER)]
    now = time.time()
    for state in states:
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
    return rows


QUESTION_HEADER = ["TASK", "QID", "STAGE", "ASKED", "QUESTION"]


def question_rows(tasks: TaskStore, sidecars: SidecarStore, width: int) -> list[list[str]]:
    """Every open question of every task, QUESTION truncated so rows fit in `width` columns.
    QID is the full name `<task>/<qid>`, ready to paste into `question answer`."""
    rows: list[list[str]] = []
    for task_id in tasks.ids("question"):
        for q in open_questions(sidecars.load(task_id).questions):
            rows.append([task_id, f"{task_id}/{qstr(q, 'id')}", qstr(q, "stage"),
                         qstr(q, "asked_at")[:16].replace("T", " "),
                         " ".join(qstr(q, "text").split())])
    fixed = [QUESTION_HEADER, *rows]
    used = sum(max(len(r[i]) for r in fixed) + 2 for i in range(4))
    room = max(width - used, 20)
    for r in rows:
        if len(r[4]) > room:
            r[4] = r[4][:room - 3] + "..."
    return [QUESTION_HEADER, *rows]


def print_table(rows: list[list[str]]) -> None:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())


def render_show(tasks: TaskStore, task: Task, side: Sidecar) -> list[str]:
    def v(x: object) -> str:
        return "-" if x is None or x == "" else str(x)

    now = time.time()
    lines = [
        f"id: {task.id}",
        f"title: {task.title}",
        f"state: {task.state}",
        f"blocked_cause: {v(side.blocked_cause)}",
        f"priority: {v(task.priority)}",
        f"attempts: {side.attempts}",
        f"turns: {side.turns_total}",
        f"cost: ${side.cost_usd_total:.2f}",
        f"last_outcome: {v(side.last_outcome)}",
        f"last_error: {v(side.last_error)}",
    ]
    if side.not_before and side.not_before > now:
        lines.append(f"retry_in: {side.not_before - now:.0f}s")
    lines.append("depends_on:" if task.depends_on else "depends_on: -")
    for dep_id in task.depends_on:
        lines.append(f"  {dep_id} ({tasks.state_of(dep_id) or 'unknown'})")
    if task.depends_on and task.state in ("plan-todo", "work-todo"):
        dep = evaluate(tasks, task)
        if dep.kind != "ready":
            held = f" on {', '.join(dep.waiting)}" if dep.waiting else ""
            lines.append(f"dependency_status: {dep.kind}{held}")
    lines.append(f"open_questions: {len(open_questions(side.questions))}")
    lines += [
        f"branch: {v(side.branch)}",
        f"worktree: {v(side.workspace)}",
        f"session_id: {v(side.session_id)}",
        f"plan_session_id: {v(side.plan_session_id)}",
    ]
    events = human_events(task.state, side)
    if events:
        lines.append("events:")
        lines += [f"  {r.event} -> {r.dst}" for r in events]
    else:
        lines.append("events: (none)")
    return lines
