"""`task list`, `task show` and `question list` as the query use cases build them (spec: cli)."""

from __future__ import annotations

import pytest
from fake_tasks import FakeTasks
from fake_clock import FakeClock

from samba.app.queries import HEADER, QUESTION_HEADER, ListQuestions, ListTasks, ShowTask
from samba.app.results import Table, Text
from samba.domain.questions import add_questions
from samba.domain.states import STATES, State
from samba.domain.task import Task
from samba.domain.task_id import TaskId
from samba.domain.transitions import human_events
from samba.entrypoints.table import print_table

CLOCK = FakeClock(1000.0)


def add(tasks: FakeTasks, tid: str, status: State = "work-todo", deps: tuple[str, ...] = (),
        **fields: object) -> Task:
    task = Task.new(TaskId(tid), f"Title of {tid}", "", 3, tuple(TaskId(d) for d in deps),
                    status, CLOCK)
    for key, value in fields.items():
        setattr(task, key, value)
    tasks.create(task)
    return task


def table(tasks: FakeTasks, states: list[str] | None = None) -> list[tuple[str, ...]]:
    res = ListTasks(tasks, CLOCK).run(states or [])
    assert isinstance(res, Table)
    return [tuple(r) for r in res.rows]


def show(tasks: FakeTasks, tid: str) -> list[str]:
    res = ShowTask(tasks, CLOCK).run(tid)
    assert isinstance(res, Text)
    return res.text.splitlines()


# ---- task list --------------------------------------------------------------------------------

def test_an_empty_list_is_the_header_only() -> None:
    assert table(FakeTasks()) == [HEADER]


def test_several_states_list_in_the_canonical_order_whatever_the_argument_order() -> None:
    tasks = FakeTasks()
    add(tasks, "a", "stuck", blocked_cause="budget")
    add(tasks, "b", "work-todo")
    rows = table(tasks, ["stuck", "work-todo"])
    assert [r[0] for r in rows[1:]] == ["b", "a"]
    assert STATES.index("work-todo") < STATES.index("stuck")


def test_question_and_stuck_show_their_cause_next_to_the_state() -> None:
    tasks = FakeTasks()
    add(tasks, "q", "question", blocked_cause="question")
    add(tasks, "s", "stuck", blocked_cause="budget")
    states = {r[0]: r[1] for r in table(tasks)[1:]}
    assert states == {"q": "question (question)", "s": "stuck (budget)"}


def test_a_held_task_shows_what_it_waits_on() -> None:
    tasks = FakeTasks()
    add(tasks, "a", "work-review")
    add(tasks, "b", "plan-todo")
    add(tasks, "t1", deps=("a", "b"))
    last = {r[0]: r[5] for r in table(tasks)[1:]}
    assert last["t1"] == "waiting on a, b"


def test_a_row_shows_the_outcome_the_cost_and_the_error_on_one_line() -> None:
    tasks = FakeTasks()
    add(tasks, "t1", "stuck", blocked_cause="budget", last_outcome="blocked",
        cost_usd_total=1.25, attempts=2, turns_total=7, last_error="first line\nsecond line")
    assert table(tasks)[1] == ("t1", "stuck (budget)", "2", "7", "$1.25", "blocked",
                               "first line second line")


# ---- task show --------------------------------------------------------------------------------

def test_show_prints_every_field_and_the_legal_events() -> None:
    tasks = FakeTasks()
    add(tasks, "t1", "plan-review", last_outcome="planned", attempts=1, turns_total=3,
        cost_usd_total=0.5, last_error="a long\nerror", branch="samba/t1", workspace="/ws/t1",
        session_id="s1", plan_session_id="p1")
    lines = show(tasks, "t1")
    for want in ("id: t1", "title: Title of t1", "state: plan-review", "blocked_cause: -",
                 "attempts: 1", "turns: 3", "cost: $0.50", "last_outcome: planned",
                 "last_error: a long", "branch: samba/t1",
                 "worktree: /ws/t1", "session_id: s1", "plan_session_id: p1",
                 "plan.accept -> work-todo", "plan.reject -> plan-todo"):
        assert any(want in line for line in lines), want


def test_show_of_a_done_task_has_no_events() -> None:
    tasks = FakeTasks()
    add(tasks, "t1", "done", last_outcome="done")
    lines = show(tasks, "t1")
    assert "state: done" in lines and "events: (none)" in lines


@pytest.mark.parametrize("status", STATES)
def test_show_lists_exactly_the_human_events_the_table_allows(status: State) -> None:
    tasks = FakeTasks()
    task = add(tasks, "t1", status, last_stage="work")
    lines = show(tasks, "t1")
    listed = [line.strip() for line in lines[lines.index("events:") + 1:]] if "events:" in lines \
        else []
    assert listed == [f"{r.event} -> {r.dst}" for r in human_events(status, task)]


def test_show_of_a_question_task_names_the_cause_and_where_the_answer_resumes() -> None:
    tasks = FakeTasks()
    add(tasks, "t1", "question", blocked_cause="question", last_stage="work",
        questions=add_questions((), "work", [("Which db?", ""), ("Which port?", "")], CLOCK))
    lines = show(tasks, "t1")
    assert "blocked_cause: question" in lines
    assert "  question.answer -> work-todo" in lines
    assert "open_questions: 2" in lines


def test_show_lists_dependencies_with_their_states_and_why_it_is_held() -> None:
    tasks = FakeTasks()
    add(tasks, "a", "done")
    add(tasks, "b", "work-review")
    add(tasks, "t1", deps=("a", "b", "ghost"))
    lines = show(tasks, "t1")
    assert "depends_on:" in lines
    assert {"  a (done)", "  b (work-review)", "  ghost (unknown)"} <= set(lines)
    assert any(line.startswith("dependency_status: waiting on b") for line in lines), lines


# ---- question list on a terminal --------------------------------------------------------------

def question_rows() -> Table:
    tasks = FakeTasks()
    add(tasks, "t1", "question", blocked_cause="question",
        questions=add_questions((), "work", [("Which database should the cache use, given the "
                                              "constraints listed in the spec chapter?", "")], CLOCK))
    return ListQuestions(tasks).run()


def test_question_list_keeps_its_columns_and_cuts_the_question_on_a_narrow_terminal(
        capsys: pytest.CaptureFixture[str]) -> None:
    res = question_rows()
    assert res.rows[0] == QUESTION_HEADER
    print_table(res.rows, 60, flex=res.flex)
    out = capsys.readouterr().out.splitlines()
    assert all(len(line) <= 60 for line in out)
    assert out[1].startswith("t1    t1/q1  work   ") and out[1].endswith("...")


def test_question_list_shows_the_whole_question_on_a_wide_terminal(
        capsys: pytest.CaptureFixture[str]) -> None:
    res = question_rows()
    print_table(res.rows, 300, flex=res.flex)
    assert capsys.readouterr().out.splitlines()[1].endswith("listed in the spec chapter?")
