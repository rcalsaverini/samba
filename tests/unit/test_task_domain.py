"""Pure tests of the Task aggregate types: TaskId rules, Question helpers, Task methods, deps_snapshot."""

from __future__ import annotations

import pytest

from samba.domain.deps import deps_snapshot, evaluate
from samba.domain.questions import (
    Question,
    add_questions,
    answer_question,
    dismiss_open,
    latest_round,
    merge_questions,
    open_questions,
    round_pairs,
    round_questions,
)
from samba.domain.task import Task
from samba.domain.task_id import AmbiguousTask, InvalidTaskId, TaskId, UnknownTask, resolve


class Clk:
    def time(self) -> float:
        return 1000.0

    def monotonic(self) -> float:
        return 1.0

    def iso_seconds(self) -> str:
        return "2026-01-01T00:00:00+00:00"

    def log_stamp(self) -> str:
        return "2026-01-01 00:00"


CLK = Clk()


@pytest.mark.parametrize("text", ["a", "A-b_c.d", "x" * 80, "..a", "a.."])
def test_valid_ids(text: str) -> None:
    assert TaskId(text) == text


@pytest.mark.parametrize("text", ["", ".", "..", "a b", "a/b", "é", "a\n"])
def test_invalid_ids(text: str) -> None:
    with pytest.raises(InvalidTaskId):
        TaskId(text)


@pytest.mark.parametrize("title,slug", [
    ("Add the thing!", "add-the-thing"),
    ("  --Hello,   World--  ", "hello-world"),
    ("!!!", "task"),
    ("", "task"),
    ("x" * 100, "x" * 60),
    ("a" * 59 + " b", "a" * 59),
])
def test_slug(title: str, slug: str) -> None:
    assert TaskId.slug(title) == slug


KNOWN = [TaskId("alpha"), TaskId("alphabet"), TaskId("beta"), TaskId("beta-2")]


def test_resolve_exact_wins_over_prefix() -> None:
    assert resolve(KNOWN, "alpha") == "alpha"
    assert TaskId.resolve(KNOWN, "beta") == "beta"


def test_resolve_unique_prefix() -> None:
    assert resolve(KNOWN, "alphab") == "alphabet"
    assert resolve(KNOWN, "beta-") == "beta-2"


def test_resolve_ambiguous_and_unknown() -> None:
    with pytest.raises(AmbiguousTask) as e:
        resolve(KNOWN, "al" + "")
    assert e.value.candidates == ("alpha", "alphabet")
    with pytest.raises(UnknownTask):
        resolve(KNOWN, "zzz")
    with pytest.raises(UnknownTask):
        resolve(KNOWN, "")


def test_add_questions_numbers_and_rounds() -> None:
    qs = add_questions((), "plan", [("a?", "ctx"), ("b?", "")], CLK)
    assert [(q.id, q.round, q.status, q.stage) for q in qs] == [
        ("q1", 1, "open", "plan"), ("q2", 1, "open", "plan")]
    qs2 = add_questions(qs, "work", [("c?", "")], CLK)
    assert qs2[-1].id == "q3" and qs2[-1].round == 2
    assert qs == qs2[:2]  # new tuple, the old one is untouched
    assert latest_round(qs2) == 2
    assert [q.id for q in round_questions(qs2)] == ["q3"]


def test_answer_and_dismiss_return_new_tuples() -> None:
    qs = add_questions((), "plan", [("a?", ""), ("b?", "")], CLK)
    answered = answer_question(qs, "q1", "yes", CLK)
    assert answered[0].status == "answered" and answered[0].answer == "yes"
    assert qs[0].status == "open"
    assert [q.id for q in open_questions(answered)] == ["q2"]
    dismissed = dismiss_open(answered, CLK)
    assert [q.status for q in dismissed] == ["answered", "dismissed"]
    assert dismiss_open(dismissed, CLK) is dismissed
    assert answer_question(qs, "q9", "x", CLK) == qs


def test_round_pairs() -> None:
    qs = add_questions((), "plan", [("a?", ""), ("b?", "")], CLK)
    qs = dismiss_open(answer_question(qs, "q1", "yes", CLK), CLK)
    assert round_pairs(qs) == ("q1 (answered): a?\nAnswer: yes\n\n"
                               "q2 (dismissed): b?\nThe human dismissed this question without answering.")


def test_question_is_frozen() -> None:
    q = Question(id="q1", round=1, stage="plan", status="open", text="t")
    with pytest.raises(AttributeError):
        q.status = "answered"  # type: ignore[misc]


def test_merge_questions_by_id() -> None:
    snap = add_questions((), "plan", [("a?", ""), ("b?", "")], CLK)
    mine = answer_question(snap, "q1", "mine", CLK)
    stored = answer_question(snap, "q2", "theirs", CLK)
    merged = merge_questions(snap, mine, stored)
    assert [(q.id, q.answer) for q in merged] == [("q1", "mine"), ("q2", "theirs")]
    both = answer_question(snap, "q1", "theirs", CLK)  # both changed q1: the stored one wins
    assert merge_questions(snap, mine, both)[0].answer == "theirs"
    added = add_questions(mine, "work", [("c?", "")], CLK)
    assert [q.id for q in merge_questions(snap, added, stored)] == ["q1", "q2", "q3"]


def test_task_methods() -> None:
    t = Task.new(TaskId("t"), "T", "body", 3, (), "plan-todo", CLK)
    assert t.queued_at == 1000.0 and t.status == "plan-todo"
    t.add_log("one")
    t.add_log("two")
    assert t.log == ("one", "two")
    assert t.add_feedback("a") == 1 and t.add_feedback("b") == 2
    t.add_questions("plan", [("q?", "")], CLK)
    t.answer_question("q1", "yes", CLK)
    assert t.questions[0].status == "answered"
    t.add_questions("plan", [("r?", "")], CLK)
    t.dismiss_open(CLK)
    assert t.questions[1].status == "dismissed"


def test_deps_snapshot() -> None:
    def mk(i: str, status: str, deps: tuple[str, ...] = ()) -> Task:
        return Task(id=TaskId(i), title=i, body="", priority=None,
                    depends_on=tuple(TaskId(d) for d in deps), status=status)  # type: ignore[arg-type]
    tasks = {t.id: t for t in [mk("a", "work-todo", ("b", "ghost")), mk("b", "done", ("a",)),
                               mk("c", "stuck")]}
    snap = deps_snapshot(tasks[TaskId("a")], tasks.get)
    assert set(snap) == {"a", "b"}  # ghost is unknown, a done task's deps are not followed
    assert evaluate(snap, "a").unknown == ("ghost",)
