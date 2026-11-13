"""What the markdown task store writes and reads on disk (spec: task-files, layout).

Real `MarkdownTasks` on a temporary directory, driven through the use cases where the text comes
from a person (feedback, answers, a new task). The behaviors here are the file layout itself, which
no fake can show; the store's contract against the fake is in `test_tasks_port.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fake_clock import FakeClock
from fake_journal import FakeJournal
from fake_terminal import FakeLock, FakeTerminal

from samba.adapters.markdown_tasks import MarkdownTasks
from samba.app.answer_question import AnswerQuestion
from samba.app.change_state import ChangeState
from samba.app.create_task import CreateTask
from samba.app.machine import Machine
from samba.app.results import Done
from samba.domain.questions import add_questions
from samba.domain.states import State
from samba.domain.task import Task
from samba.domain.task_id import TaskId

CLOCK = FakeClock(100.0)
T1 = TaskId("t1")


class Store:
    def __init__(self, tmp: Path) -> None:
        self.root = tmp / "tasks"
        self.state = tmp / "state"
        self.tasks = MarkdownTasks(self.root, self.state, CLOCK)
        self.machine = Machine(self.tasks, CLOCK, FakeJournal())

    def add(self, status: State = "plan-review", **fields: object) -> Task:
        task = Task.new(T1, "Feature", "Do the thing.", 3, (), status, CLOCK)
        for key, value in fields.items():
            setattr(task, key, value)
        self.tasks.create(task)
        return task

    def text(self) -> str:
        [path] = list(self.root.glob("*/t1.md"))
        return path.read_text()

    def sidecar(self) -> dict[str, object]:
        return json.loads((self.state / "t1.json").read_text())

    def reject(self, feedback: str) -> None:
        change = ChangeState(self.tasks, self.machine, FakeTerminal(interactive=False), FakeLock())
        res = change.run("t1", "plan.reject", "plan.reject", feedback=feedback,
                         feedback_mode="optional")
        assert isinstance(res, Done), res
        task = self.tasks.get(T1)
        assert task is not None
        if task.status != "plan-review":  # back to review for the next round
            task.status = "plan-review"
            assert self.tasks.save(task)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path)


# ---- feedback rounds --------------------------------------------------------------------------

def test_the_first_feedback_creates_the_section_once_before_the_log(store: Store) -> None:
    store.add()
    store.reject("Split it in two.")
    text = store.text()
    assert text.count("## Feedback") == 1
    assert text.index("## Feedback") < text.index("## Log")
    assert "### Round 1\n\nSplit it in two." in text


def test_repeated_rejects_append_rounds_in_order_and_demote_headings(store: Store) -> None:
    store.add()
    store.reject("First.")
    store.reject("## Not a section\nSecond.")
    text = store.text()
    assert text.index("### Round 1") < text.index("### Round 2")
    assert "### Not a section" in text and "\n## Not a section" not in text
    assert any("round 2" in line for line in text.splitlines() if line.startswith("- "))


def test_feedback_goes_after_human_prose_already_in_the_section(store: Store) -> None:
    store.add()
    [path] = list(store.root.glob("*/t1.md"))
    path.write_text(path.read_text() + "\n## Feedback\n\nA note the human wrote.\n\n## Log\n")
    store.reject("Now the real feedback.")
    text = store.text()
    prose, round1, log = (text.index("A note the human wrote."), text.index("### Round 1"),
                          text.index("## Log"))
    assert prose < round1 < log
    assert text.count("## Feedback") == 1


# ---- answers ----------------------------------------------------------------------------------

def test_a_heading_inside_an_answer_is_demoted_in_the_task_file(store: Store) -> None:
    store.add("question", blocked_cause="question", last_stage="work",
              questions=add_questions((), "work", [("Which db?", "")], CLOCK))
    answer = AnswerQuestion(store.tasks, store.machine, FakeTerminal(), FakeLock(), CLOCK)
    assert isinstance(answer.run("t1", "postgres\n## Why\nit is there", False), Done)
    text = store.text()
    assert "### Why" in text and "\n## Why" not in text
    assert text.count("## Questions") == 1


# ---- plan and assumptions ---------------------------------------------------------------------

def test_a_plan_with_headings_stays_one_section_and_is_replaced_whole_on_revision(
        store: Store) -> None:
    task = store.add("plan-running")
    task.plan = "Steps\n## Detail\nfirst version"
    assert store.tasks.save(task)
    first = store.text()
    assert first.count("## Plan") == 1 and "### Detail" in first
    task = store.tasks.get(T1)
    assert task is not None and "first version" in task.plan
    task.plan = "Second version only"
    assert store.tasks.save(task)
    text = store.text()
    assert text.count("## Plan") == 1
    assert "first version" not in text and "Second version only" in text


def test_assumptions_are_their_own_section_and_record_no_question(store: Store) -> None:
    task = store.add("plan-running")
    task.plan = "Do it."
    task.assumptions = "The cache is local."
    assert store.tasks.save(task)
    text = store.text()
    assert "## Assumptions\nThe cache is local." in text
    assert "## Questions" not in text
    assert store.sidecar()["questions"] == []


# ---- reading files a person wrote -------------------------------------------------------------

def test_a_depends_on_that_is_not_a_list_is_ignored(store: Store) -> None:
    (store.root / "work-todo").mkdir(parents=True)
    (store.root / "work-todo" / "t1.md").write_text('---\ndepends_on: "dep-a"\n---\n# T\n')
    task = store.tasks.get(T1)
    assert task is not None and task.depends_on == ()


def test_an_old_sidecar_still_loads_and_its_old_key_is_dropped_on_save(store: Store) -> None:
    store.add("work-todo")
    store.state.mkdir(parents=True, exist_ok=True)
    (store.state / "t1.json").write_text(json.dumps({"state": "work-todo", "phase": "work",
                                                     "attempts": 2}))
    task = store.tasks.get(T1)
    assert task is not None and task.attempts == 2
    task.last_error = "touched"
    assert store.tasks.save(task)
    side = store.sidecar()
    assert "phase" not in side and side["attempts"] == 2


def test_empty_old_layout_folders_do_not_block_startup(store: Store) -> None:
    for old in ("todo", "running", "review"):
        (store.root / old).mkdir(parents=True)
    store.tasks.prepare()  # raises only when an old folder still holds a task


# ---- a new task -------------------------------------------------------------------------------

def test_a_new_task_without_a_terminal_is_front_matter_and_the_title_only(store: Store) -> None:
    res = CreateTask(store.tasks, FakeTerminal(interactive=False), CLOCK).run(
        "My title", None, None, 3, False)
    assert isinstance(res, Done)
    [path] = list(store.root.glob("*/my-title.md"))
    assert path.parent.name == "plan-todo"
    assert path.read_text() == "---\npriority: 3\n---\n# My title\n\n"


def test_a_new_round_goes_before_the_next_section_without_piling_up_blank_lines(
        store: Store) -> None:
    store.add()
    [path] = list(store.root.glob("*/t1.md"))
    path.write_text(path.read_text() + "\n## Feedback\n\n### Round 1\n\nold\n\n\n\n## Notes\nkeep\n")
    task = store.tasks.get(T1)
    assert task is not None
    task.add_feedback("new")
    assert store.tasks.save(task)
    assert "old\n\n### Round 2\n\nnew\n\n## Notes\nkeep" in store.text()


def test_a_log_line_goes_at_the_end_of_the_log_when_another_section_follows(
        store: Store) -> None:
    store.add()
    [path] = list(store.root.glob("*/t1.md"))
    path.write_text(path.read_text() + "\n## Log\n- first\n\n\n## Notes\nkeep\n")
    task = store.tasks.get(T1)
    assert task is not None
    task.add_log("- second")
    assert store.tasks.save(task)
    # right after the last entry; the blank lines a person left before the next section stay
    assert "## Log\n- first\n- second\n\n\n## Notes\nkeep" in store.text()
