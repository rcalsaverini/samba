"""In-process tests of the use cases over fakes (domain and app only, no adapter)."""

from __future__ import annotations

import pytest
from samba.app.answer_question import AnswerQuestion, Answered
from samba.app.change_state import ChangeState, StateChanged, check_legal, NotAllowed, Legal
from samba.app.confirm import confirm
from samba.app.machine import Machine
from samba.app.results import Refused
from samba.domain.states import State
from samba.domain.task import Task
from samba.domain.task_id import TaskId
from samba.ports import EditResult

from fake_tasks import FakeTasks
from fake_terminal import FakeLock, FakeTerminal
from test_scenarios import FakeClock


def make(status: State, tid: str = "t1") -> tuple[FakeTasks, TaskId]:
    tasks = FakeTasks()
    task_id = TaskId(tid)
    tasks.create(Task.new(task_id, "T", "", 3, (), status, FakeClock()))
    return tasks, task_id


def change_state(tasks: FakeTasks, terminal: FakeTerminal | None = None,
                 lock: FakeLock | None = None) -> ChangeState:
    return ChangeState(tasks, Machine(tasks, FakeClock()), terminal or FakeTerminal(),
                       lock or FakeLock())


def messages(r: Refused) -> str:
    return "\n".join(r.messages)


# --- the legality check -----------------------------------------------------------------------

def test_check_legal_ok_missing_and_illegal() -> None:
    tasks, tid = make("plan-review")
    assert isinstance(check_legal(tasks, tid, "plan.accept", "plan.accept"), Legal)
    bad = check_legal(tasks, tid, "task.retry", "task.retry")
    assert isinstance(bad, NotAllowed)
    assert "t1 is in plan-review; task.retry not allowed. Legal events: " in bad.message
    assert "plan.accept" in bad.message
    gone = check_legal(tasks, TaskId("nope"), "plan.accept", "plan.accept")
    assert isinstance(gone, NotAllowed) and gone.message == "task 'nope' has no file"


# --- ChangeState ------------------------------------------------------------------------------

def test_legal_event_fires() -> None:
    tasks, tid = make("plan-review")
    res = change_state(tasks).run(tid, "plan.accept", "plan.accept")
    assert res == StateChanged("fake://t1")
    assert tasks.records[tid].status == "work-todo"


def test_illegal_event_is_refused_and_names_the_legal_ones() -> None:
    tasks, tid = make("work-todo")
    res = change_state(tasks).run(tid, "plan.accept", "plan.accept")
    assert isinstance(res, Refused) and res.kind == "refused"
    assert messages(res).startswith("samba: t1 is in work-todo; plan.accept not allowed.")
    assert tasks.records[tid].status == "work-todo"


def test_feedback_is_written_before_the_move_with_a_round_log() -> None:
    tasks, tid = make("plan-review")
    res = change_state(tasks).run(tid, "plan.reject", "plan.reject", feedback=" more detail ",
                                  feedback_mode="optional")
    assert isinstance(res, StateChanged)
    rec = tasks.records[tid]
    assert rec.status == "plan-todo"
    assert [f.text for f in rec.feedback] == ["more detail"]
    assert any("feedback round 1" in line for line in rec.log)


def test_empty_feedback_warns_when_optional_and_fails_when_required() -> None:
    tasks, tid = make("plan-review")
    res = change_state(tasks).run(tid, "plan.reject", "plan.reject", feedback_mode="optional")
    assert isinstance(res, StateChanged)
    assert res.notes == ("warning: rejecting without feedback",)
    tasks, tid = make("plan-review")
    req = change_state(tasks).run(tid, "plan.reject", "plan.reject", feedback_mode="required")
    assert isinstance(req, Refused) and req.kind == "usage"
    assert messages(req) == "samba: plan.reject needs text (argument or --edit); nothing changed"


def test_edit_failure_refuses_and_edit_text_is_used() -> None:
    tasks, tid = make("plan-review")
    term = FakeTerminal(edits=[EditResult(error="editor exited with 1; nothing changed")])
    res = change_state(tasks, term).run(tid, "plan.reject", "plan.reject", edit=True,
                                        feedback_mode="optional")
    assert isinstance(res, Refused)
    assert messages(res) == "samba: editor exited with 1; nothing changed"
    term = FakeTerminal(edits=[EditResult(text="  from editor\n")])
    ok = change_state(tasks, term).run(tid, "plan.reject", "plan.reject", edit=True,
                                       feedback_mode="optional")
    assert isinstance(ok, StateChanged)
    assert [f.text for f in tasks.records[tid].feedback] == ["from editor"]


def test_retry_hint_from_the_blocked_cause() -> None:
    tasks, tid = make("stuck")
    tasks.records[tid].blocked_cause = "budget"
    res = change_state(tasks).run(tid, "task.retry", "task.retry", hints=True)
    assert isinstance(res, StateChanged)
    assert res.notes and res.notes[0].startswith("hint: raise the budget cap")


def test_lock_busy_refuses_without_moving() -> None:
    tasks, tid = make("plan-review")
    res = change_state(tasks, lock=FakeLock(held=False)).run(tid, "plan.accept", "plan.accept")
    assert isinstance(res, Refused)
    assert "holds .samba/lock" in messages(res)
    assert tasks.records[tid].status == "plan-review"


def test_discard_asks_after_legality_and_before_the_lock() -> None:
    tasks, tid = make("work-todo")
    lock = FakeLock()
    term = FakeTerminal(lines=["n"])
    res = change_state(tasks, term, lock).run(tid, "task.discard", "task.discard",
                                              confirm_plan="Discard task {id}")
    assert isinstance(res, Refused) and res.kind == "refused"
    assert term.prompts == ["Discard task t1? [y/N] "]
    assert lock.entered == 0
    term = FakeTerminal(lines=["yes"])
    ok = change_state(tasks, term, lock).run(tid, "task.discard", "task.discard",
                                             confirm_plan="Discard task {id}")
    assert isinstance(ok, StateChanged) and tasks.records[tid].status == "discarded"
    # an illegal event never reaches the prompt
    term = FakeTerminal()
    change_state(tasks, term).run(tid, "task.discard", "task.discard", confirm_plan="x")
    assert term.prompts == []


# --- the confirmation policy ------------------------------------------------------------------

def test_confirm_policy() -> None:
    assert confirm(FakeTerminal(interactive=False), "P", "cmd", yes=True) is None
    no_tty = confirm(FakeTerminal(interactive=False), "P", "cmd", yes=False)
    assert no_tty is not None and no_tty.kind == "usage"
    assert messages(no_tty) == ("samba: cmd needs confirmation: run it on a terminal or pass "
                                "--yes; nothing changed")
    assert confirm(FakeTerminal(lines=["y"]), "P", "cmd", yes=False) is None
    assert confirm(FakeTerminal(lines=[" YES "]), "P", "cmd", yes=False) is None
    for answer in (["maybe"], [""], []):
        declined = confirm(FakeTerminal(lines=answer), "P", "cmd", yes=False)
        assert declined is not None and declined.kind == "refused"
        assert messages(declined) == "samba: not confirmed; nothing changed"


# --- AnswerQuestion ---------------------------------------------------------------------------

def asking(*texts: str) -> tuple[FakeTasks, TaskId]:
    tasks, tid = make("question")
    task = tasks.records[tid]
    task.add_questions("plan", [(t, "") for t in texts], FakeClock())
    return tasks, tid


def answer_uc(tasks: FakeTasks, terminal: FakeTerminal | None = None,
              lock: FakeLock | None = None) -> AnswerQuestion:
    clock = FakeClock()
    return AnswerQuestion(tasks, Machine(tasks, clock), terminal or FakeTerminal(),
                          lock or FakeLock(), clock)


def test_single_open_question_is_answered_and_the_task_resumes() -> None:
    tasks, tid = asking("why?")
    res = answer_uc(tasks).run(tid, None, " because ", False)
    assert isinstance(res, Answered) and res.notes == ()
    rec = tasks.records[tid]
    assert rec.status == "plan-todo"
    assert rec.questions[0].answer == "because"
    assert any("question.answer: t1/" in line and "answered" in line for line in rec.log)


def test_several_open_questions_need_a_qid_and_the_task_waits_for_the_rest() -> None:
    tasks, tid = asking("a?", "b?")
    uc = answer_uc(tasks)
    res = uc.run(tid, None, "x", False)
    assert isinstance(res, Refused) and res.kind == "usage"
    assert "has 2 open questions" in messages(res) and "  t1/" in messages(res)
    first = tasks.records[tid].questions[0].id
    part = uc.run(tid, first, "x", False)
    assert isinstance(part, Answered)
    assert part.notes and "1 question(s) still open" in part.notes[0]
    assert tasks.records[tid].status == "question"
    again = uc.run(tid, first, "y", False)
    assert isinstance(again, Refused) and again.kind == "refused"
    assert "is answered, not open; nothing changed" in messages(again)


def test_answer_errors() -> None:
    tasks, tid = asking("a?")
    uc = answer_uc(tasks)
    unknown = uc.run(tid, "q99", "x", False)
    assert isinstance(unknown, Refused) and unknown.kind == "usage"
    assert messages(unknown) == "samba: unknown question t1/q99"
    empty = uc.run(tid, None, "  ", False)
    assert isinstance(empty, Refused) and empty.kind == "usage"
    assert "needs text" in messages(empty)
    wrong = make("work-todo")
    bad = answer_uc(wrong[0]).run(wrong[1], None, "x", False)
    assert isinstance(bad, Refused) and "question.answer not allowed" in messages(bad)
    none_open, nid = make("question")
    res = answer_uc(none_open).run(nid, None, "x", False)
    assert isinstance(res, Refused)
    assert messages(res) == "samba: t1 has no open question; nothing changed"


def test_answer_from_the_editor_quotes_the_question_and_strips_comments() -> None:
    tasks, tid = asking("why?")
    term = FakeTerminal(edits=[EditResult(text="# t: why?\n#\n\nthe answer\n")])
    res = answer_uc(tasks, term).run(tid, None, None, True)
    assert isinstance(res, Answered)
    assert term.edit_initials[0].startswith("# ") and "why?" in term.edit_initials[0]
    assert tasks.records[tid].questions[0].answer == "the answer"


@pytest.mark.parametrize("held", [False])
def test_answer_lock_busy(held: bool) -> None:
    tasks, tid = asking("why?")
    res = answer_uc(tasks, lock=FakeLock(held=held)).run(tid, None, "x", False)
    assert isinstance(res, Refused)
    assert tasks.records[tid].questions[0].status == "open"
