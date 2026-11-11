"""Read-only queries behind shell completion (spec: cli, Shell completion). Each returns
`(value, help)` pairs of plain strings, never prints, and knows nothing of the shell. The states a
verb can act on come from the transition table, not from a list here."""

from __future__ import annotations

from samba.domain.ports import Adrs, Tasks
from samba.domain.questions import open_questions
from samba.domain.states import STATES, State
from samba.domain.transitions import find_row

Candidates = list[tuple[str, str]]

# command label -> human event of the transition table; `task show` has no event (every state)
TASK_EVENTS = {
    "plan accept": "plan.accept",
    "plan reject": "plan.reject",
    "work accept": "work.accept",
    "work reject": "work.reject",
    "task retry": "task.retry",
    "task stop": "task.stop",
    "task discard": "task.discard",
}

# ADR command -> the status it acts on (None: every ADR)
ADR_STATUS = {"accept": "proposed", "reject": "proposed", "supersede": "accepted", "show": None}


def source_states(event: str) -> tuple[State, ...]:
    """The states in which the table has a row for `event`."""
    return tuple(s for s in STATES if find_row(event, s, lambda _guard: True))


def one_line(text: str, width: int = 60) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[:width - 3] + "..."


class CompleteTaskIds:
    """Task ids the command can act on, filtered by the typed prefix."""

    def __init__(self, tasks: Tasks) -> None:
        self._tasks = tasks

    def run(self, command: str, incomplete: str) -> Candidates:
        event = TASK_EVENTS.get(command)
        states = source_states(event) if event else STATES
        found: Candidates = []
        for state in states:
            for task in self._tasks.list(state):
                if task.id.startswith(incomplete):
                    found.append((task.id, one_line(f"{state}  {task.title}")))
        return sorted(found)


class CompleteQuestions:
    """`task/qid` of every open question, filtered by the typed prefix."""

    def __init__(self, tasks: Tasks) -> None:
        self._tasks = tasks

    def run(self, incomplete: str) -> Candidates:
        found: Candidates = []
        for task in self._tasks.list("question"):
            for q in open_questions(task.questions):
                name = f"{task.id}/{q.id}"
                if name.startswith(incomplete):
                    found.append((name, one_line(q.text)))
        return found


class CompleteAdrs:
    """ADR numbers (`0003`) of the ADRs the command acts on, filtered by the typed prefix."""

    def __init__(self, adrs: Adrs) -> None:
        self._adrs = adrs

    def run(self, command: str, incomplete: str) -> Candidates:
        status = ADR_STATUS.get(command)
        return [(f"{a.number:04d}", one_line(a.title)) for a in self._adrs.load_all()
                if (status is None or a.status == status)
                and f"{a.number:04d}".startswith(incomplete)]
