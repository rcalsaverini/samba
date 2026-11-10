"""Question records (spec: states, Sidecar state and Questions). Pure: the clock is a parameter."""

from __future__ import annotations

from samba.ports import Clock

Question = dict[str, object]


def qint(q: Question, key: str) -> int:
    v = q.get(key)
    return v if isinstance(v, int) else 0


def qstr(q: Question, key: str) -> str:
    v = q.get(key)
    return v if isinstance(v, str) else ""


def question_number(q: Question) -> int:
    qid = qstr(q, "id")
    return int(qid[1:]) if qid[1:].isdigit() else 0


def latest_round(questions: list[Question]) -> int:
    return max((qint(q, "round") for q in questions), default=0)


def round_questions(questions: list[Question]) -> list[Question]:
    """The questions of the latest blocking round."""
    n = latest_round(questions)
    return [q for q in questions if qint(q, "round") == n] if n else []


def open_questions(questions: list[Question]) -> list[Question]:
    return [q for q in questions if q.get("status") == "open"]


def add_questions(questions: list[Question], stage: str, items: list[tuple[str, str]],
                  clock: Clock) -> None:
    """Append open records for one blocking event: ids continue after the highest ever used,
    the round is one more than the latest."""
    n = max((question_number(q) for q in questions), default=0)
    rnd = latest_round(questions) + 1
    for text, context in items:
        n += 1
        questions.append({"id": f"q{n}", "round": rnd, "stage": stage, "status": "open",
                          "text": text, "context": context, "asked_at": clock.iso_seconds(),
                          "answer": None, "answered_at": None})


def answer_question(q: Question, text: str, clock: Clock) -> None:
    q["status"], q["answer"], q["answered_at"] = "answered", text, clock.iso_seconds()


def dismiss_open(questions: list[Question], clock: Clock) -> None:
    for q in open_questions(questions):
        q["status"], q["answered_at"] = "dismissed", clock.iso_seconds()


def render_questions(questions: list[Question]) -> str:
    blocks: list[str] = []
    for q in questions:
        parts = [f"### {qstr(q, 'id')} (round {qint(q, 'round')}, {qstr(q, 'status')})",
                 qstr(q, "text").strip()]
        if qstr(q, "context").strip():
            parts.append("Context: " + qstr(q, "context").strip())
        if q.get("status") == "answered":
            parts.append("Answer: " + qstr(q, "answer").strip())
        blocks.append("\n\n".join(parts))
    return "\n\n".join(blocks)


def round_pairs(questions: list[Question]) -> str:
    """The latest round as question and answer pairs, for the resume prompt (spec: prompts, Which prompt is sent)."""
    out: list[str] = []
    for q in round_questions(questions):
        status = qstr(q, "status")
        out.append(f"{qstr(q, 'id')} ({status}): {qstr(q, 'text').strip()}")
        if status == "answered":
            out.append(f"Answer: {qstr(q, 'answer').strip()}")
        elif status == "dismissed":
            out.append("The human dismissed this question without answering.")
        out.append("")
    return "\n".join(out).strip()
