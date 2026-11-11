"""Question records (spec: states, Questions). Pure: the clock is a parameter.

`Question` is frozen and the helpers work on tuples and return new tuples.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from samba.domain.states import Stage
from samba.domain.ports import Clock

QuestionStatus = Literal["open", "answered", "dismissed"]


@dataclass(frozen=True)
class Question:
    id: str
    round: int
    stage: Stage
    status: QuestionStatus
    text: str
    context: str = ""
    asked_at: str = ""
    answer: str | None = None
    answered_at: str | None = None


def question_number(q: Question) -> int:
    return int(q.id[1:]) if q.id[1:].isdigit() else 0


def latest_round(questions: tuple[Question, ...]) -> int:
    return max((q.round for q in questions), default=0)


def round_questions(questions: tuple[Question, ...]) -> tuple[Question, ...]:
    """The questions of the latest blocking round."""
    n = latest_round(questions)
    return tuple(q for q in questions if q.round == n) if n else ()


def open_questions(questions: tuple[Question, ...]) -> tuple[Question, ...]:
    return tuple(q for q in questions if q.status == "open")


def add_questions(questions: tuple[Question, ...], stage: Stage, items: list[tuple[str, str]],
                  clock: Clock) -> tuple[Question, ...]:
    """Open records for one blocking event appended: ids continue after the highest ever used,
    the round is one more than the latest."""
    n = max((question_number(q) for q in questions), default=0)
    rnd = latest_round(questions) + 1
    new: list[Question] = []
    for text, context in items:
        n += 1
        new.append(Question(id=f"q{n}", round=rnd, stage=stage, status="open", text=text,
                            context=context, asked_at=clock.iso_seconds()))
    return questions + tuple(new)


def answer_question(questions: tuple[Question, ...], qid: str, text: str,
                    clock: Clock) -> tuple[Question, ...]:
    """The question `qid` answered. An unknown id leaves the tuple as it is."""
    return tuple(replace(q, status="answered", answer=text, answered_at=clock.iso_seconds())
                 if q.id == qid else q for q in questions)


def dismiss_open(questions: tuple[Question, ...], clock: Clock) -> tuple[Question, ...]:
    """Every open question dismissed. The same tuple object if none was open."""
    if not any(q.status == "open" for q in questions):
        return questions
    return tuple(replace(q, status="dismissed", answered_at=clock.iso_seconds())
                 if q.status == "open" else q for q in questions)


def merge_questions(snapshot: tuple[Question, ...], mine: tuple[Question, ...],
                    stored: tuple[Question, ...]) -> tuple[Question, ...]:
    """The stale-save merge of question records, by id (spec: architecture, Ports). `snapshot` is
    what the caller loaded, `mine` what it holds now, `stored` what is stored now. A question only
    the caller changed takes the caller's version; one the stored side changed, or both changed,
    keeps the stored one, so a human answer is not lost. Questions only the caller added are added."""
    snap_by = {q.id: q for q in snapshot}
    stored_ids = {q.id for q in stored}
    mine_by = {q.id: q for q in mine}
    out: list[Question] = []
    for s in stored:
        m = mine_by.get(s.id)
        base = snap_by.get(s.id)
        out.append(m if m is not None and base is not None and m != base and s == base else s)
    out.extend(q for q in mine if q.id not in stored_ids and q.id not in snap_by)
    return tuple(out)


def round_pairs(questions: tuple[Question, ...]) -> str:
    """The latest round as question and answer pairs, for the resume prompt (spec: prompts, Which prompt is sent)."""
    out: list[str] = []
    for q in round_questions(questions):
        out.append(f"{q.id} ({q.status}): {q.text.strip()}")
        if q.status == "answered":
            out.append(f"Answer: {(q.answer or '').strip()}")
        elif q.status == "dismissed":
            out.append("The human dismissed this question without answering.")
        out.append("")
    return "\n".join(out).strip()
