"""Question rounds and old question tasks, through the question use cases (spec: task-files, cli)."""

from __future__ import annotations

import asyncio

from fake_journal import FakeJournal
from fake_tasks import FakeTasks
from fake_terminal import FakeLock, FakeTerminal
from fake_clock import FakeClock
from test_tick import Rig

from samba.app.answer_question import AnswerQuestion
from samba.app.machine import Machine
from samba.app.queries import ListQuestions, ShowQuestion
from samba.app.results import Done, Refused, Table, Text
from samba.domain.ports import EditResult
from samba.domain.questions import Question, add_questions, answer_question
from samba.domain.task import Task
from samba.domain.task_id import TaskId

CLOCK = FakeClock(100.0)
T1 = TaskId("t1")


def store_with(questions: tuple[Question, ...] | None) -> FakeTasks:
    tasks = FakeTasks()
    task = Task.new(T1, "t1", "", 3, (), "question", CLOCK)
    task.blocked_cause = "question"
    task.last_stage = "work"
    if questions is not None:
        task.questions = questions
    tasks.create(task)
    return tasks


def two_rounds() -> FakeTasks:
    first = add_questions((), "work", [("Which db?", "storage"), ("Which port?", "net")], CLOCK)
    first = answer_question(first, "q1", "postgres", CLOCK)
    first = answer_question(first, "q2", "5432", CLOCK)
    both = add_questions(first, "work", [("Which schema?", "a second block")], CLOCK)
    return store_with(both)


def test_a_second_block_continues_the_ids_in_a_new_round() -> None:
    q3 = two_rounds().records[T1].questions[-1]
    assert (q3.id, q3.round, q3.status) == ("q3", 2, "open")


def test_show_by_task_is_the_latest_round_and_by_qid_is_one_question_with_its_answer() -> None:
    tasks = two_rounds()
    latest = ShowQuestion(tasks).run("t1")
    assert isinstance(latest, Text)
    assert "t1/q3" in latest.text and "round: 2" in latest.text and "t1/q1" not in latest.text
    one = ShowQuestion(tasks).run("t1/q1")
    assert isinstance(one, Text)
    assert "Which db?" in one.text and "Context: storage" in one.text
    assert "Answer: postgres" in one.text


def test_an_unknown_qid_is_a_usage_error() -> None:
    res = ShowQuestion(two_rounds()).run("t1/q9")
    assert isinstance(res, Refused) and res.kind == "usage"
    assert res.messages == ("samba: unknown question t1/q9",)


def test_an_old_question_task_without_questions_lists_nothing_and_refuses_an_answer() -> None:
    tasks = store_with(None)
    listed = ListQuestions(tasks).run()
    assert isinstance(listed, Table) and len(listed.rows) == 1  # the header only
    answer = AnswerQuestion(tasks, Machine(tasks, CLOCK, FakeJournal()), FakeTerminal(),
                            FakeLock(), CLOCK)
    res = answer.run("t1", "an answer", False)
    assert isinstance(res, Refused)
    assert "no open question" in "\n".join(res.messages)
    assert tasks.records[T1].status == "question"


def test_an_old_question_task_still_runs_after_a_hand_move() -> None:
    rig = Rig()
    task = rig.add("t1", status="question")
    assert task.questions == ()
    rig.tasks.hand_move(T1, "work-todo")
    asyncio.run(rig.tick.run())
    assert rig.spawned == ["t1"]  # the move was accepted (an illegal one is moved back)
    assert rig.status("t1") == "work-running"


def test_answering_is_recorded_and_resumes_the_task() -> None:
    tasks = store_with(add_questions((), "work", [("Which db?", "")], CLOCK))
    answer = AnswerQuestion(tasks, Machine(tasks, CLOCK, FakeJournal()), FakeTerminal(),
                            FakeLock(), CLOCK)
    assert isinstance(answer.run("t1", "postgres", False), Done)
    task = tasks.records[T1]
    assert task.status == "work-todo" and task.questions[0].answer == "postgres"


def test_the_editor_shows_the_question_and_its_context_as_comments() -> None:
    tasks = store_with(add_questions((), "work", [("Which db?", "the cache layer")], CLOCK))
    terminal = FakeTerminal(edits=[EditResult(text="# ignored\npostgres\n")])
    answer = AnswerQuestion(tasks, Machine(tasks, CLOCK, FakeJournal()), terminal, FakeLock(), CLOCK)
    assert isinstance(answer.run("t1", None, True), Done)
    assert terminal.edit_initials == ["# q1: Which db?\n#\n# Context: the cache layer\n\n"]
    assert tasks.records[T1].questions[0].answer == "postgres"
