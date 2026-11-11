"""In-process tests of `AcceptWork` and `CreateTask` over fakes (domain and app only)."""

from __future__ import annotations

import pytest
from samba.app.accept_work import Accepted, AcceptWork, DryRun
from samba.app.create_task import Created, CreateTask
from samba.app.machine import Machine
from samba.app.results import Refused
from samba.domain.task_id import TaskId
from samba.ports import MergeResult

from fake_journal import FakeJournal
from fake_merger import FakeMerger
from fake_tasks import FakeTasks
from fake_terminal import FakeLock, FakeTerminal
from test_app_use_cases import make, messages
from test_scenarios import FakeClock


# --- AcceptWork -------------------------------------------------------------------------------

def accept_uc(tasks: FakeTasks, merger: FakeMerger, terminal: FakeTerminal | None = None,
              lock: FakeLock | None = None, command: str | None = "make check") -> AcceptWork:
    return AcceptWork(tasks, Machine(tasks, FakeClock(), FakeJournal()), terminal or FakeTerminal(),
                      lock or FakeLock(), merger, "main", command)


def test_dry_run_prints_the_plan_and_changes_nothing() -> None:
    tasks, tid = make("work-review")
    merger = FakeMerger(commits=1)
    res = accept_uc(tasks, merger).run(tid, dry_run=True)
    assert res == DryRun((
        "Merge samba/t1 into main (1 commit), then validate with `make check`",
        "branch: samba/t1\nbase: main\ncommits: 1", "merge: yes (--no-ff)",
        "validate: make check", "final state: done"))
    assert merger.calls == [] and tasks.records[tid].status == "work-review"
    skipped = accept_uc(tasks, merger).run(tid, dry_run=True, no_merge=True)
    assert isinstance(skipped, DryRun)
    assert skipped.lines[0] == "Mark t1 done without merging (--no-merge)"
    assert skipped.lines[2:4] == ("merge: no", "validate: skipped")


def test_accept_merges_validates_and_fires() -> None:
    tasks, tid = make("work-review")
    merger = FakeMerger()
    res = accept_uc(tasks, merger).run(tid, yes=True)
    assert res == Accepted("fake://t1")
    assert merger.calls == [("t1", "samba/t1", "Merge samba/t1: T", True)]
    rec = tasks.records[tid]
    assert rec.status == "done" and any("merged abc1234, validated" in ln for ln in rec.log)


def test_accept_without_a_validate_command_says_so() -> None:
    tasks, tid = make("work-review")
    merger = FakeMerger(MergeResult("merged", "abc1234"))
    res = accept_uc(tasks, merger, command=None).run(tid, yes=True)
    assert isinstance(res, Accepted)
    assert res.notes == ("samba: no validate.command; merged without validation",)
    assert merger.calls[0][3] is False


def test_accept_no_merge_and_already_merged() -> None:
    tasks, tid = make("work-review")
    merger = FakeMerger()
    assert isinstance(accept_uc(tasks, merger).run(tid, yes=True, no_merge=True), Accepted)
    assert merger.calls == [] and merger.preflights == 0
    assert any("no merge" in ln for ln in tasks.records[tid].log)
    tasks, tid = make("work-review")
    res = accept_uc(tasks, FakeMerger(MergeResult("already"))).run(tid, yes=True)
    assert isinstance(res, Accepted)
    assert res.notes == ("samba: samba/t1 is already merged into main; nothing to merge",)
    assert any("already merged" in ln for ln in tasks.records[tid].log)


def test_accept_refusals_before_any_change() -> None:
    tasks, tid = make("work-todo")
    res = accept_uc(tasks, FakeMerger()).run(tid, yes=True)
    assert isinstance(res, Refused) and "work.accept not allowed" in messages(res)
    tasks, tid = make("work-review")
    pre = accept_uc(tasks, FakeMerger(problem="the main checkout has uncommitted changes")
                    ).run(tid, yes=True)
    assert isinstance(pre, Refused) and pre.kind == "refused"
    assert messages(pre) == "samba: the main checkout has uncommitted changes; nothing changed"
    gone = accept_uc(tasks, FakeMerger()).run(TaskId("nope"), yes=True)
    assert isinstance(gone, Refused) and messages(gone) == "samba: task 'nope' has no file"
    busy = accept_uc(tasks, FakeMerger(), lock=FakeLock(held=False)).run(tid, yes=True)
    assert isinstance(busy, Refused) and "holds .samba/lock" in messages(busy)
    no_tty = accept_uc(tasks, FakeMerger(), FakeTerminal(interactive=False)).run(tid)
    assert isinstance(no_tty, Refused) and no_tty.kind == "usage"
    declined = accept_uc(tasks, FakeMerger(), FakeTerminal(lines=["n"])).run(tid)
    assert isinstance(declined, Refused) and declined.kind == "refused"
    assert tasks.records[tid].status == "work-review"


@pytest.mark.parametrize("result,message,log", [
    (MergeResult("conflict", "a.py, b.py"),
     "samba: merge conflict in: a.py, b.py; merge aborted, task stays in work-review",
     "work.accept: merge failed (conflicts: a.py, b.py)"),
    (MergeResult("error", "boom"),
     "samba: merge failed: boom; merge aborted, task stays in work-review",
     "work.accept: merge failed (boom)"),
    (MergeResult("validation_failed", "2 failed", log_path="/x/v.log"),
     "samba: validation failed after merge; merge aborted, task stays in work-review: 2 failed"
     "\nsamba: full output: /x/v.log",
     "work.accept: validation failed after merge: 2 failed"),
])
def test_merge_failures_log_and_stay_in_work_review(result: MergeResult, message: str,
                                                    log: str) -> None:
    tasks, tid = make("work-review")
    res = accept_uc(tasks, FakeMerger(result)).run(tid, yes=True)
    assert isinstance(res, Refused) and res.kind == "refused"
    assert messages(res) == message
    rec = tasks.records[tid]
    assert rec.status == "work-review" and log in rec.log


def test_fire_failure_after_the_merge() -> None:
    tasks, tid = make("work-review")

    class Racing(FakeMerger):
        def merge(self, task_id: str, branch: str, message: str, validate: bool) -> MergeResult:
            tasks.records[tid].status = "stuck"  # a hand move after the checks
            return super().merge(task_id, branch, message, validate)

    res = accept_uc(tasks, Racing()).run(tid, yes=True)
    assert isinstance(res, Refused)
    assert messages(res) == ("samba: work.accept did not apply to t1 after the merge (merged "
                             "abc1234, validated); the merge is in main")


# --- CreateTask -------------------------------------------------------------------------------

def create_uc(tasks: FakeTasks, terminal: FakeTerminal | None = None) -> CreateTask:
    return CreateTask(tasks, terminal or FakeTerminal(interactive=False), FakeClock())


def test_slug_collisions_get_numeric_suffixes() -> None:
    tasks = FakeTasks()
    uc = create_uc(tasks)
    ids: list[TaskId] = []
    for _ in range(3):
        res = uc.run("Fix the thing", None, None, 3, False)
        assert isinstance(res, Created)
        ids.append(res.task_id)
    assert ids == ["fix-the-thing", "fix-the-thing-2", "fix-the-thing-3"]
    assert tasks.records[ids[0]].status == "plan-todo"
    skip = uc.run("Other", "body", None, 1, True)
    assert isinstance(skip, Created)
    rec = tasks.records[skip.task_id]
    assert rec.status == "work-todo" and rec.priority == 1 and rec.body == "body"


def test_dependencies_by_flag_resolve_prefixes_or_fail() -> None:
    tasks, _ = make("work-todo", "alpha-one")
    uc = create_uc(tasks)
    res = uc.run("T2", None, "alpha, alpha-one", 3, False)
    assert isinstance(res, Created) and tasks.records[res.task_id].depends_on == ("alpha-one",)
    bad = uc.run("T3", None, "zzz", 3, False)
    assert isinstance(bad, Refused) and bad.kind == "usage"
    assert messages(bad) == "samba: unknown task 'zzz'"


def test_no_title_without_a_terminal_is_a_usage_error() -> None:
    res = create_uc(FakeTasks()).run(None, None, None, 3, False)
    assert isinstance(res, Refused) and res.kind == "usage"
    assert messages(res).startswith("samba: task new needs a TITLE")


def test_missing_fields_are_asked_on_a_terminal() -> None:
    tasks, _ = make("work-todo", "alpha")
    term = FakeTerminal(lines=["", "  Asked title ", "line one", "line two", "", "nope", "alpha",
                               "n"])
    res = create_uc(tasks, term).run(None, None, None, 3, False)
    assert isinstance(res, Created) and res.task_id == "asked-title"
    rec = tasks.records[res.task_id]
    assert rec.body == "line one\nline two" and rec.depends_on == ("alpha",)
    assert rec.status == "work-todo"  # "n" to "Plan first?"
    assert term.warnings == ["samba: unknown task 'nope'"]
    assert term.prompts[0] == "Title: " and term.prompts[-1] == "Plan first? [Y/n] "


def test_input_ending_creates_nothing() -> None:
    tasks = FakeTasks()
    res = create_uc(tasks, FakeTerminal(lines=["Title"])).run(None, None, None, 3, False)
    assert isinstance(res, Refused) and res.kind == "refused"
    assert messages(res) == "samba: input ended; nothing created"
    assert tasks.records == {}
