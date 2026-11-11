"""`find_task`: id and prefix resolution as a result, shared by every use case that takes an id."""

from __future__ import annotations

from samba.app.resolve import find_task
from samba.app.results import Refused
from samba.domain.task import Task
from samba.domain.task_id import TaskId

from fake_tasks import FakeTasks
from test_scenarios import FakeClock


def store(*ids: str) -> FakeTasks:
    tasks = FakeTasks()
    for tid in ids:
        tasks.create(Task.new(TaskId(tid), "T", "", 3, (), "work-todo", FakeClock()))
    return tasks


def test_exact_id_and_unique_prefix() -> None:
    tasks = store("alpha-1", "beta")
    assert find_task(tasks, "beta") == "beta"
    assert find_task(tasks, "alp") == "alpha-1"


def test_exact_id_wins_over_a_longer_id_it_prefixes() -> None:
    assert find_task(store("a1", "a1-b"), "a1") == "a1"


def test_ambiguous_prefix_is_a_usage_refusal_with_candidates() -> None:
    assert find_task(store("a1", "a2"), "a") == Refused(
        "usage", ("samba: ambiguous task id 'a'; candidates:\n  a1\n  a2",))


def test_unknown_id_is_a_usage_refusal() -> None:
    assert find_task(store("a1"), "zz") == Refused("usage", ("samba: unknown task 'zz'",))
