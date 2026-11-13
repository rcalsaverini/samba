"""In-process tests of the completion queries over fakes (no adapter)."""

from __future__ import annotations

from samba.app.completion import CompleteAdrs, CompleteQuestions, CompleteTaskIds, source_states
from samba.domain.questions import Question
from samba.domain.states import STATES, State
from samba.domain.task import Task
from samba.domain.task_id import TaskId
from samba.domain.transitions import human_events

from fake_tasks import FakeTasks
from test_app_queries import FakeAdrs, adr
from fake_clock import FakeClock


def store(*specs: tuple[str, State]) -> FakeTasks:
    tasks = FakeTasks()
    for tid, status in specs:
        tasks.create(Task.new(TaskId(tid), f"Title {tid}", "", 3, (), status, FakeClock()))
    return tasks


ALL: tuple[tuple[str, State], ...] = tuple((f"t-{s}", s) for s in STATES)


def ids(found: list[tuple[str, str]]) -> list[str]:
    return [v for v, _ in found]


def test_each_command_offers_the_states_its_table_rows_start_from() -> None:
    tasks = store(*ALL)
    q = CompleteTaskIds(tasks)
    assert ids(q.run("plan accept", "")) == ["t-plan-review"]
    assert ids(q.run("plan reject", "")) == ["t-plan-review"]
    assert ids(q.run("work accept", "")) == ["t-work-review"]
    assert ids(q.run("work reject", "")) == ["t-work-review"]
    assert ids(q.run("task retry", "")) == ["t-stuck"]
    assert ids(q.run("task stop", "")) == ["t-plan-running", "t-work-running"]
    assert len(q.run("task show", "")) == len(STATES)
    discard = ids(q.run("task discard", ""))
    assert discard and "t-done" not in discard and "t-discarded" not in discard


def test_source_states_come_from_the_transition_table() -> None:
    assert source_states("plan.accept") == ("plan-review",)
    assert source_states("nope") == ()
    for state in STATES:
        events = {r.event for r in human_events(state, Task.new(
            TaskId("x"), "X", "", 3, (), state, FakeClock()))}
        assert ("task.discard" in events) == (state in source_states("task.discard"))


def test_prefix_filter_and_help_text() -> None:
    tasks = store(("ab-1", "plan-review"), ("cd-2", "plan-review"))
    found = CompleteTaskIds(tasks).run("plan accept", "ab")
    assert found == [("ab-1", "plan-review Title ab-1")]
    assert CompleteTaskIds(tasks).run("plan accept", "zz") == []
    assert CompleteTaskIds(store()).run("plan accept", "") == []


def test_questions_offer_only_open_ones_as_task_slash_qid() -> None:
    tasks = FakeTasks()
    task = Task.new(TaskId("qa"), "QA", "", 3, (), "question", FakeClock())
    task.questions = (
        Question("q1", 1, "work", "open", "Which\ndatabase?"),
        Question("q2", 1, "work", "answered", "Old?", answer="yes"),
        Question("q3", 1, "work", "open", "x" * 100))
    tasks.create(task)
    tasks.create(Task.new(TaskId("zz"), "ZZ", "", 3, (), "work-todo", FakeClock()))
    found = CompleteQuestions(tasks).run("")
    assert [v for v, _ in found] == ["qa/q1", "qa/q3"]
    assert found[0][1] == "Which database?"
    assert len(found[1][1]) == 60 and found[1][1].endswith("...")
    assert CompleteQuestions(tasks).run("qa/q3") == [found[1]]
    assert CompleteQuestions(tasks).run("zz") == []


def test_adr_numbers_by_status() -> None:
    store_ = FakeAdrs(adr(1, "accepted"), adr(2, "proposed"), adr(3, "rejected"),
                      adr(12, "proposed"))
    q = CompleteAdrs(store_)
    assert ids(q.run("accept", "")) == ["0002", "0012"]
    assert ids(q.run("reject", "")) == ["0002", "0012"]
    assert ids(q.run("supersede", "")) == ["0001"]
    assert ids(q.run("show", "")) == ["0001", "0002", "0003", "0012"]
    assert q.run("accept", "001") == [("0012", "Title 12")]
    assert CompleteAdrs(FakeAdrs()).run("show", "") == []
