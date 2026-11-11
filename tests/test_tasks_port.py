"""Contract tests of the `Tasks` port, run against `FakeTasks` and `MarkdownTasks`.

This file may import adapters (the black-box and scenario runners may not).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fake_tasks import FakeTasks

from samba.adapters.markdown_tasks import MarkdownTasks
from samba.domain.states import STATES, State
from samba.domain.task import ObservedMove, Task
from samba.domain.task_id import TaskId
from samba.domain.ports import StoreError, TaskExists, Tasks


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


class Env:
    """A store plus what the two implementations do differently: a hand move, an agent edit."""

    def __init__(self, tasks: Tasks, move: Callable[[TaskId, State], None],
                 edit_body: Callable[[TaskId, str], None], root: Path | None) -> None:
        self.tasks = tasks
        self.move = move
        self.edit_body = edit_body
        self.root = root


def fake_env(_tmp: Path) -> Env:
    fake = FakeTasks()

    def edit(id: TaskId, text: str) -> None:
        fake.records[id].body += "\n" + text
    return Env(fake, fake.hand_move, edit, None)


def md_env(tmp: Path) -> Env:
    tasks = MarkdownTasks(tmp / "tasks", tmp / "state", CLK)
    tasks.prepare()

    def move(id: TaskId, dst: State) -> None:
        src = next(s for s in STATES if (tmp / "tasks" / s / f"{id}.md").exists())
        (tmp / "tasks" / src / f"{id}.md").rename(tmp / "tasks" / dst / f"{id}.md")

    def edit(id: TaskId, text: str) -> None:
        """The agent appends to its own file."""
        p = next(tmp / "tasks" / s / f"{id}.md" for s in STATES
                 if (tmp / "tasks" / s / f"{id}.md").exists())
        p.write_text(p.read_text().rstrip("\n") + "\n" + text + "\n")
    return Env(tasks, move, edit, tmp)


@pytest.fixture(params=["fake", "markdown"])
def env(request: pytest.FixtureRequest, tmp_path: Path) -> Env:
    return (fake_env if request.param == "fake" else md_env)(tmp_path)


def make(env: Env, name: str = "t", status: State = "work-todo", body: str = "do it") -> Task:
    env.tasks.create(Task.new(TaskId(name), "Title " + name, body, 2, (), status, CLK))
    got = env.tasks.get(TaskId(name))
    assert got is not None
    return got


def fetch(env: Env, name: str = "t") -> Task:
    t = env.tasks.get(TaskId(name))
    assert t is not None
    return t


# ---- basics ---------------------------------------------------------------------------------

def test_create_get_list(env: Env) -> None:
    make(env, "a", "plan-todo")
    make(env, "b", "work-todo")
    a = fetch(env, "a")
    assert (a.title, a.priority, a.status, a.depends_on) == ("Title a", 2, "plan-todo", ())
    assert env.tasks.get(TaskId("nope")) is None
    assert [t.id for t in env.tasks.list("work-todo")] == ["b"]
    assert env.tasks.ids() == ["a", "b"]
    assert env.tasks.ids("plan-todo") == ["a"]
    with pytest.raises(TaskExists):
        env.tasks.create(Task.new(TaskId("a"), "x", "", None, (), "stuck", CLK))


def test_create_keeps_dependencies(env: Env) -> None:
    env.tasks.create(Task.new(TaskId("c"), "C", "", 1, (TaskId("a"), TaskId("b")), "work-todo", CLK))
    assert fetch(env, "c").depends_on == ("a", "b")


def test_location_is_opaque_text(env: Env) -> None:
    make(env)
    assert isinstance(env.tasks.location(TaskId("t")), str)


def test_save_roundtrips_fields(env: Env) -> None:
    t = make(env)
    t.attempts, t.turns_total, t.cost_usd_total = 2, 5, 0.25
    t.blocked_cause, t.last_outcome, t.last_stage = "budget", "blocked", "work"
    t.session_id, t.branch, t.workspace = "s1", "samba/t", "/ws/t"
    t.add_log("a line")
    t.add_feedback("please change")
    t.add_questions("work", [("why?", "because")], CLK)
    assert env.tasks.save(t)
    got = fetch(env)
    assert (got.attempts, got.turns_total, got.cost_usd_total) == (2, 5, 0.25)
    assert (got.blocked_cause, got.last_outcome, got.last_stage) == ("budget", "blocked", "work")
    assert (got.session_id, got.branch, got.workspace) == ("s1", "samba/t", "/ws/t")
    assert got.log == ("a line",)
    assert [(f.number, f.text) for f in got.feedback] == [(1, "please change")]
    assert [(q.id, q.text, q.context) for q in got.questions] == [("q1", "why?", "because")]


def test_plan_and_assumptions_roundtrip(env: Env) -> None:
    t = make(env, status="plan-running")
    t.plan, t.assumptions = "1. do\n2. done", "none"
    assert env.tasks.save(t)
    got = fetch(env)
    assert (got.plan, got.assumptions) == ("1. do\n2. done", "none")


def test_status_change_and_lost_race(env: Env) -> None:
    mine = make(env, status="work-todo")
    other = fetch(env)
    mine.status = "work-running"
    assert env.tasks.save(mine)
    assert [t.id for t in env.tasks.list("work-running")] == ["t"]
    other.status = "stuck"  # loaded when it was work-todo: the move is lost
    other.attempts = 9
    assert env.tasks.save(other) is False
    got = fetch(env)
    assert got.status == "work-running" and got.attempts == 0  # nothing written


def test_lost_race_after_hand_move(env: Env) -> None:
    t = make(env, status="work-running")
    env.move(t.id, "stuck")
    t.status = "work-review"
    assert env.tasks.save(t) is False
    assert fetch(env).status == "stuck"


# ---- merge rules ----------------------------------------------------------------------------

def test_stale_counter_save_keeps_a_humans_blocked_cause(env: Env) -> None:
    worker = make(env, status="work-running")
    human = fetch(env)
    human.status, human.blocked_cause = "stuck", "stopped"
    assert env.tasks.save(human)
    worker.turns_total += 1  # the worker only counted a turn
    worker.cost_usd_total += 0.5
    assert env.tasks.save(worker)
    got = fetch(env)
    assert got.status == "stuck" and got.blocked_cause == "stopped"
    assert got.turns_total == 1 and got.cost_usd_total == 0.5


def test_save_writes_nothing_the_aggregate_did_not_change(env: Env) -> None:
    worker = make(env, status="work-running")
    human = fetch(env)
    human.last_error, human.attempts = "boom", 3
    assert env.tasks.save(human)
    worker.turns_total = 4
    assert env.tasks.save(worker)
    got = fetch(env)
    assert (got.last_error, got.attempts, got.turns_total) == ("boom", 3, 4)


def test_scalar_changed_on_both_sides_aggregate_wins(env: Env) -> None:
    worker = make(env)
    human = fetch(env)
    human.last_error = "human"
    env.tasks.save(human)
    worker.last_error = "worker"
    env.tasks.save(worker)
    assert fetch(env).last_error == "worker"


def test_log_and_feedback_appends_merge(env: Env) -> None:
    worker = make(env, status="work-running")
    human = fetch(env)
    human.add_log("human line")
    assert human.add_feedback("human feedback") == 1
    env.tasks.save(human)
    worker.add_log("worker line")
    worker.add_feedback("worker feedback")
    env.tasks.save(worker)
    got = fetch(env)
    assert got.log == ("human line", "worker line")
    assert [f.text for f in got.feedback] == ["human feedback", "worker feedback"]
    assert [f.number for f in got.feedback] == [1, 2]


def test_save_refreshes_the_aggregate_from_the_merge(env: Env) -> None:
    worker = make(env, status="work-running")
    human = fetch(env)
    human.add_log("human line")
    human.blocked_cause = "stopped"
    env.tasks.save(human)
    worker.turns_total = 2
    env.tasks.save(worker)
    assert worker.log == ("human line",) and worker.blocked_cause == "stopped"
    assert worker.turns_total == 2
    worker.add_log("again")  # the snapshot was renewed: only the new line is appended
    env.tasks.save(worker)
    assert fetch(env).log == ("human line", "again")


def test_concurrent_question_answers_merge(env: Env) -> None:
    t = make(env, status="question")
    t.add_questions("plan", [("a?", ""), ("b?", "")], CLK)
    env.tasks.save(t)
    worker, human = fetch(env), fetch(env)
    human.answer_question("q2", "human answer", CLK)
    env.tasks.save(human)
    worker.answer_question("q1", "worker answer", CLK)
    env.tasks.save(worker)
    got = {q.id: (q.status, q.answer) for q in fetch(env).questions}
    assert got == {"q1": ("answered", "worker answer"), "q2": ("answered", "human answer")}
    assert [q.answer for q in worker.questions] == ["worker answer", "human answer"]


def test_question_answered_on_both_sides_keeps_the_stored_answer(env: Env) -> None:
    t = make(env, status="question")
    t.add_questions("plan", [("a?", "")], CLK)
    env.tasks.save(t)
    worker, human = fetch(env), fetch(env)
    human.answer_question("q1", "human", CLK)
    env.tasks.save(human)
    worker.dismiss_open(CLK)
    env.tasks.save(worker)
    assert [(q.status, q.answer) for q in fetch(env).questions] == [("answered", "human")]


def test_agents_body_edit_survives_a_worker_save(env: Env) -> None:
    worker = make(env, status="work-running", body="original")
    env.edit_body(worker.id, "agent note")
    worker.turns_total = 1
    worker.add_log("worker line")
    assert env.tasks.save(worker)
    got = fetch(env)
    assert "agent note" in got.body and "original" in got.body
    assert got.log[-1] == "worker line"


def test_state_is_not_reset_by_a_stale_save(env: Env) -> None:
    """A stale save must not hide a hand move from `observe_moves`."""
    worker = make(env, status="work-running")
    assert env.tasks.observe_moves() == []  # first sight records work-running
    env.move(worker.id, "stuck")
    worker.turns_total = 1
    assert env.tasks.save(worker)  # stale: the file was moved by hand
    assert env.tasks.observe_moves() == [ObservedMove(TaskId("t"), "work-running", "stuck")]


# ---- hand moves -----------------------------------------------------------------------------

def test_observe_accept_and_revert(env: Env) -> None:
    make(env, "a", "plan-review")
    make(env, "b", "work-todo")
    assert env.tasks.observe_moves() == []  # first sight
    env.move(TaskId("a"), "work-todo")
    env.move(TaskId("b"), "stuck")
    moves = env.tasks.observe_moves()
    assert moves == [ObservedMove(TaskId("a"), "plan-review", "work-todo"),
                     ObservedMove(TaskId("b"), "work-todo", "stuck")]
    env.tasks.accept_move(moves[0])
    assert env.tasks.revert_move(moves[1])
    assert fetch(env, "b").status == "work-todo"
    assert env.tasks.observe_moves() == []  # b is back where it was recorded, a was accepted


def test_save_after_status_change_records_the_new_status(env: Env) -> None:
    t = make(env, status="work-todo")
    env.tasks.observe_moves()
    t.status = "work-running"
    env.tasks.save(t)
    assert env.tasks.observe_moves() == []


# ---- markdown specifics ---------------------------------------------------------------------

def test_markdown_counter_save_does_not_touch_the_task_file(tmp_path: Path) -> None:
    e = md_env(tmp_path)
    t = make(e, status="work-running")
    p = tmp_path / "tasks" / "work-running" / "t.md"
    before = p.read_text()
    p.write_text(before + "\nhand edit\n")  # an agent edit the aggregate does not know about
    t.turns_total = 3
    assert e.tasks.save(t)
    assert p.read_text() == before + "\nhand edit\n"
    assert '"turns_total": 3' in (tmp_path / "state" / "t.json").read_text()


def test_markdown_file_layout_matches_the_old_writers(tmp_path: Path) -> None:
    e = md_env(tmp_path)
    e.tasks.create(Task.new(TaskId("x"), "My title", "Some body", 5, (TaskId("y"),), "plan-todo", CLK))
    assert (tmp_path / "tasks" / "plan-todo" / "x.md").read_text() == (
        '---\npriority: 5\ndepends_on: ["y"]\n---\n# My title\n\nSome body\n')
    t = fetch(e, "x")
    t.status = "plan-running"
    t.add_log("2026-01-01 00:00 samba: dispatch_plan: plan-todo -> plan-running")
    t.add_questions("plan", [("Which?", "ctx")], CLK)
    e.tasks.save(t)
    assert (tmp_path / "tasks" / "plan-running" / "x.md").read_text() == (
        '---\npriority: 5\ndepends_on: ["y"]\n---\n# My title\n\nSome body\n\n'
        "## Questions\n### q1 (round 1, open)\n\nWhich?\n\nContext: ctx\n\n"
        "## Log\n2026-01-01 00:00 samba: dispatch_plan: plan-todo -> plan-running\n")


def test_markdown_unknown_sidecar_values_read_as_none(tmp_path: Path) -> None:
    e = md_env(tmp_path)
    make(e)
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "state" / "t.json").write_text(
        '{"blocked_cause": "approved", "last_outcome": "weird", "last_stage": "x", '
        '"attempts": "many", "questions": [{"id": "q1", "status": "??"}, 7]}')
    got = fetch(e)
    assert (got.blocked_cause, got.last_outcome, got.last_stage, got.attempts) == (None, None, None, 0)
    assert [(q.id, q.status) for q in got.questions] == [("q1", "dismissed")]


def test_markdown_rejects_invalid_names_and_legacy_folders(tmp_path: Path) -> None:
    e = md_env(tmp_path)
    (tmp_path / "tasks" / "work-todo" / "bad name.md").write_text("x")
    assert e.tasks.rejected_names("work-todo") == ["bad name.md"]
    assert e.tasks.ids() == []
    (tmp_path / "tasks" / "todo").mkdir()
    (tmp_path / "tasks" / "todo" / "old.md").write_text("x")
    with pytest.raises(StoreError, match="old task folders"):
        e.tasks.prepare()


def test_markdown_hand_created_file_is_read(tmp_path: Path) -> None:
    e = md_env(tmp_path)
    (tmp_path / "tasks" / "plan-todo" / "hand.md").write_text("# Hand made\n\nbody\n")
    t = fetch(e, "hand")
    assert (t.title, t.priority, t.status) == ("Hand made", None, "plan-todo")
    assert t.queued_at is not None
