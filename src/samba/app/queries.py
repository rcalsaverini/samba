"""The read-only commands as use cases (spec: cli, observability): `task list`, `task show`,
`question list`, `question show`. They return rows or text; the CLI prints them."""

from __future__ import annotations

from collections.abc import Iterable

from samba.app.resolve import ResolveError, resolve_task_id
from samba.app.results import Refused, Table, Text, usage
from samba.domain.deps import deps_snapshot, evaluate
from samba.domain.questions import open_questions, round_questions
from samba.domain.states import STATES, State
from samba.domain.task import Task
from samba.domain.transitions import human_events
from samba.domain.ports import Clock, Tasks

HEADER = ("ID", "STATE", "ATTEMPTS", "TURNS", "COST", "LAST", "ERROR")
QUESTION_HEADER = ("TASK", "QID", "STAGE", "ASKED", "QUESTION")


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


class ListTasks:
    """`task list [STATE...]`."""

    def __init__(self, tasks: Tasks, clock: Clock) -> None:
        self._tasks = tasks
        self._clock = clock

    def run(self, states: list[str]) -> Table | Refused:
        try:
            chosen = resolve_states(states) if states else STATES
        except ResolveError as e:
            return usage(e.render())
        rows: list[tuple[str, ...]] = [HEADER]
        now = self._clock.time()
        for state in chosen:
            for task in self._tasks.list(state):
                last = task.last_outcome or "-"
                if state in ("plan-todo", "work-todo"):
                    if task.not_before and task.not_before > now:
                        last += f" (retry in {task.not_before - now:.0f}s)"
                    else:
                        dep = evaluate(deps_snapshot(task, self._tasks.get), task.id)
                        if dep.kind == "waiting":
                            last = f"waiting on {', '.join(dep.waiting)}"
                shown = state
                if state in ("question", "stuck") and task.blocked_cause:
                    shown = f"{state} ({task.blocked_cause})"
                rows.append((task.id, shown, str(task.attempts), str(task.turns_total),
                             f"${task.cost_usd_total:.2f}", last,
                             " ".join((task.last_error or "").split())))
        return Table(tuple(rows), flex=6)


class ShowTask:
    """`task show ID`."""

    def __init__(self, tasks: Tasks, clock: Clock) -> None:
        self._tasks = tasks
        self._clock = clock

    def run(self, text: str) -> Text | Refused:
        try:
            task = self._tasks.get(resolve_task_id(self._tasks, text))
        except ResolveError as e:
            return usage(e.render())
        if task is None:
            return usage(f"unknown task {text!r}")
        return Text("\n".join(self._lines(task)) + "\n")

    def _lines(self, task: Task) -> list[str]:
        def v(x: object) -> str:
            return "-" if x is None or x == "" else str(x)

        now = self._clock.time()
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
            dep = self._tasks.get(dep_id)
            lines.append(f"  {dep_id} ({dep.status if dep else 'unknown'})")
        if task.depends_on and task.status in ("plan-todo", "work-todo"):
            dep_status = evaluate(deps_snapshot(task, self._tasks.get), task.id)
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


class ListQuestions:
    """`question list`: every open question of every task. QID is the full name
    `<task>/<qid>`, ready to paste into `question answer`."""

    def __init__(self, tasks: Tasks) -> None:
        self._tasks = tasks

    def run(self) -> Table:
        rows: list[tuple[str, ...]] = [QUESTION_HEADER]
        for task in self._tasks.list("question"):
            for q in open_questions(task.questions):
                rows.append((task.id, f"{task.id}/{q.id}", q.stage,
                             q.asked_at[:16].replace("T", " "), " ".join(q.text.split())))
        return Table(tuple(rows), flex=4)


def split_target(target: str) -> tuple[str, str | None]:
    """`TASK` or `TASK/QID`. Task ids never contain a slash."""
    task, sep, qid = target.rpartition("/")
    return (task, qid) if sep else (target, None)


class ShowQuestion:
    """`question show TASK[/QID]`: one question, or the latest round of a task."""

    def __init__(self, tasks: Tasks) -> None:
        self._tasks = tasks

    def run(self, target: str) -> Text | Refused:
        name, qid = split_target(target)
        try:
            task_id = resolve_task_id(self._tasks, name)
        except ResolveError as e:
            return usage(e.render())
        task = self._tasks.get(task_id)
        questions = task.questions if task is not None else ()
        shown = [q for q in questions if q.id == qid] if qid else round_questions(questions)
        if not shown:
            return usage(f"unknown question {task_id}/{qid}" if qid
                         else f"{task_id} has no questions")
        blocks: list[str] = []
        for q in shown:
            lines = [f"{task_id}/{q.id}  stage: {q.stage}  round: {q.round}"
                     f"  status: {q.status}  asked: {q.asked_at}", "", q.text]
            if q.context:
                lines += ["", "Context: " + q.context]
            if q.status == "answered":
                lines += ["", "Answer: " + (q.answer or "")]
            blocks.append("\n".join(lines))
        return Text("\n\n".join(blocks) + "\n")
