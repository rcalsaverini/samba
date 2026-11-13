"""The `Lock` port: the contract run against `FakeLock` and `FileLock`, then what only a real flock
shows (contention between holders), and commands applied under the real lock and store
(spec: task-files, Write discipline)."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fake_clock import FakeClock
from fake_journal import FakeJournal
from fake_terminal import FakeLock, FakeTerminal

from samba.adapters.file_lock import FileLock
from samba.adapters.markdown_tasks import MarkdownTasks
from samba.app.answer_question import AnswerQuestion
from samba.app.change_state import ChangeState
from samba.app.machine import Machine
from samba.app.results import Done
from samba.domain.ports import Lock
from samba.domain.questions import add_questions
from samba.domain.states import State
from samba.domain.task import Task
from samba.domain.task_id import TaskId

CLOCK = FakeClock(100.0)


@pytest.fixture(params=["fake", "file"])
def lock(request: pytest.FixtureRequest, tmp_path: Path) -> Lock:
    return FakeLock() if request.param == "fake" else FileLock(tmp_path / ".samba")


# ---- the contract ------------------------------------------------------------------------------

def test_a_free_lock_is_held_inside_the_block(lock: Lock) -> None:
    with lock.acquire() as held:
        assert held is True


def test_a_released_lock_can_be_taken_again_even_after_an_error(lock: Lock) -> None:
    with pytest.raises(RuntimeError):
        with lock.acquire():
            raise RuntimeError("boom")
    with lock.acquire(blocking=False) as held:
        assert held is True


# ---- only a real flock -------------------------------------------------------------------------

@pytest.fixture
def held_elsewhere(tmp_path: Path) -> Iterator[threading.Event]:
    """Another holder keeps the lock until the returned event is set."""
    release, taken = threading.Event(), threading.Event()

    def hold() -> None:
        with FileLock(tmp_path / ".samba").acquire() as ok:
            assert ok
            taken.set()
            release.wait(5)

    t = threading.Thread(target=hold)
    t.start()
    assert taken.wait(5)
    yield release
    release.set()
    t.join(5)


def test_a_held_lock_refuses_a_non_blocking_taker(tmp_path: Path,
                                                   held_elsewhere: threading.Event) -> None:
    with FileLock(tmp_path / ".samba").acquire(blocking=False) as held:
        assert held is False


def test_a_blocking_taker_gives_up_after_its_timeout(tmp_path: Path,
                                                     held_elsewhere: threading.Event) -> None:
    start = time.monotonic()
    with FileLock(tmp_path / ".samba", timeout=0.2).acquire() as held:
        assert held is False
    assert time.monotonic() - start >= 0.2


def test_a_blocking_taker_waits_for_the_release(tmp_path: Path,
                                                held_elsewhere: threading.Event) -> None:
    threading.Timer(0.3, held_elsewhere.set).start()
    start = time.monotonic()
    with FileLock(tmp_path / ".samba").acquire() as held:
        assert held is True
    assert time.monotonic() - start >= 0.25


# ---- commands under the real lock and store ----------------------------------------------------

class Repo:
    def __init__(self, tmp: Path) -> None:
        self.tasks = MarkdownTasks(tmp / "tasks", tmp / "state", CLOCK)
        self.tasks.prepare()
        self.lock = FileLock(tmp / ".samba")
        self.machine = Machine(self.tasks, CLOCK, FakeJournal())
        self.change = ChangeState(self.tasks, self.machine, FakeTerminal(interactive=False),
                                  self.lock)

    def add(self, tid: str, status: State, **fields: object) -> None:
        task = Task.new(TaskId(tid), tid, "", 3, (), status, CLOCK)
        for key, value in fields.items():
            setattr(task, key, value)
        self.tasks.create(task)

    def status(self, tid: str) -> State:
        task = self.tasks.get(TaskId(tid))
        assert task is not None
        return task.status


def test_a_command_waits_for_the_lock_then_applies(tmp_path: Path) -> None:
    repo = Repo(tmp_path)
    repo.add("t1", "plan-review")
    release, taken = threading.Event(), threading.Event()

    def orchestrator_tick() -> None:
        with FileLock(tmp_path / ".samba").acquire():
            taken.set()
            release.wait(5)

    t = threading.Thread(target=orchestrator_tick)
    t.start()
    assert taken.wait(5)
    threading.Timer(0.3, release.set).start()
    start = time.monotonic()
    assert isinstance(repo.change.run("t1", "plan.accept", "plan.accept"), Done)
    t.join(5)
    assert time.monotonic() - start >= 0.25
    assert repo.status("t1") == "work-todo"


@pytest.mark.parametrize("status, event, dst", [
    ("plan-review", "plan.accept", "work-todo"),
    ("plan-review", "plan.reject", "plan-todo"),
    ("work-review", "work.reject", "work-todo"),
    ("stuck", "task.retry", "work-todo"),
])
def test_a_command_is_samba_own_move_and_never_a_hand_move(tmp_path: Path, status: State,
                                                          event: str, dst: State) -> None:
    repo = Repo(tmp_path)
    repo.add("t1", status, last_stage="work", blocked_cause="stopped" if status == "stuck" else None)
    assert repo.tasks.observe_moves() == []  # first sight records the folder
    assert isinstance(repo.change.run("t1", event, event), Done)
    assert repo.status("t1") == dst
    assert repo.tasks.observe_moves() == []
    task = repo.tasks.get(TaskId("t1"))
    assert task is not None and task.attempts == 0


def test_an_answer_is_samba_own_move_too(tmp_path: Path) -> None:
    repo = Repo(tmp_path)
    repo.add("t1", "question", last_stage="work", blocked_cause="question",
             questions=add_questions((), "work", [("Which db?", "")], CLOCK))
    assert repo.tasks.observe_moves() == []
    answer = AnswerQuestion(repo.tasks, repo.machine, FakeTerminal(), repo.lock, CLOCK)
    assert isinstance(answer.run("t1", "postgres", False), Done)
    assert repo.status("t1") == "work-todo"
    assert repo.tasks.observe_moves() == []
