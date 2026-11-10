"""The `Task` aggregate: everything the core knows about one task (spec: states, Task aggregate).

A plain mutable record. The `Tasks` port (`samba.ports`) loads and saves it; where and how it is
stored is the adapter's business. Pure: the clock is a parameter.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from samba.domain import questions as qs
from samba.domain.questions import Question
from samba.domain.states import BlockedCause, LastOutcome, Stage, State
from samba.domain.task_id import TaskId
from samba.ports import Clock

TODO_STATES: tuple[State, ...] = ("plan-todo", "work-todo")


@dataclass(frozen=True)
class FeedbackRound:
    number: int
    text: str


@dataclass(frozen=True)
class ObservedMove:
    """A move a human made by hand that the store noticed."""
    task_id: TaskId
    src: State
    dst: State


@dataclass(eq=False)
class Task:
    id: TaskId
    title: str
    body: str
    priority: int | None
    depends_on: tuple[TaskId, ...]
    status: State
    attempts: int = 0
    turns_total: int = 0
    cost_usd_total: float = 0.0
    input_tokens_total: int = 0
    output_tokens_total: int = 0
    session_id: str | None = None
    plan_session_id: str | None = None
    plan_approved: bool = False
    last_stage: Stage | None = None
    blocked_cause: BlockedCause | None = None
    last_outcome: LastOutcome | None = None
    last_error: str | None = None
    not_before: float | None = None
    first_dispatched_at: float | None = None
    queued_at: float | None = None
    branch: str | None = None
    workspace: str | None = None
    plan: str = ""
    assumptions: str = ""
    feedback: tuple[FeedbackRound, ...] = ()
    log: tuple[str, ...] = ()
    questions: tuple[Question, ...] = field(default_factory=lambda: ())

    @staticmethod
    def new(id: TaskId, title: str, body: str, priority: int | None,
            depends_on: tuple[TaskId, ...], status: State, clock: Clock) -> Task:
        return Task(id=id, title=title, body=body, priority=priority, depends_on=depends_on,
                    status=status, queued_at=clock.time())

    def add_log(self, line: str) -> None:
        self.log = self.log + (line,)

    def add_feedback(self, text: str) -> int:
        """A new feedback round. Returns its number: one more than the highest so far."""
        n = max((f.number for f in self.feedback), default=0) + 1
        self.feedback = self.feedback + (FeedbackRound(n, text),)
        return n

    def add_questions(self, stage: Stage, items: list[tuple[str, str]], clock: Clock) -> None:
        self.questions = qs.add_questions(self.questions, stage, items, clock)

    def answer_question(self, qid: str, text: str, clock: Clock) -> None:
        self.questions = qs.answer_question(self.questions, qid, text, clock)

    def dismiss_open(self, clock: Clock) -> None:
        self.questions = qs.dismiss_open(self.questions, clock)
