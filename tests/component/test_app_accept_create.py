"""In-process tests of `AcceptWork` and `CreateTask` over fakes (domain and app only)."""

from __future__ import annotations

import asyncio

import pytest
from samba.app.accept_work import AcceptWork
from samba.app.create_task import CreateTask
from samba.app.machine import Machine
from samba.app.results import Done, Refused, Text
from samba.domain.task import Task
from samba.domain.task_id import TaskId
from samba.domain.ports import CommitResult, MergeAttempt

from fake_journal import FakeJournal
from fake_tasks import FakeTasks
from fake_terminal import FakeLock, FakeTerminal
from fake_validator import FakeValidator, failing, passing
from fake_vcs import FakeVcs
from test_app_use_cases import make, messages
from fake_clock import FakeClock


# --- AcceptWork -------------------------------------------------------------------------------

def accept_uc(tasks: FakeTasks, vcs: FakeVcs, terminal: FakeTerminal | None = None,
              lock: FakeLock | None = None, command: str | None = "make check",
              validator: FakeValidator | None = None) -> AcceptWork:
    return AcceptWork(tasks, Machine(tasks, FakeClock(), FakeJournal()), terminal or FakeTerminal(),
                      lock or FakeLock(), vcs, validator or FakeValidator(), "main", command)


def accept(uc: AcceptWork, tid: str, **flags: bool) -> Done | Text | Refused:
    return asyncio.run(uc.run(tid, **flags))


def names(vcs: FakeVcs) -> list[str]:
    return [c[0] for c in vcs.calls]


def test_dry_run_prints_the_plan_and_changes_nothing() -> None:
    tasks, tid = make("work-review")
    vcs = FakeVcs(commits=1)
    res = accept(accept_uc(tasks, vcs), tid, dry_run=True)
    assert res == Text(
        "Merge samba/t1 into main (1 commit), then validate with `make check`\n"
        "branch: samba/t1\nbase: main\ncommits: 1\nmerge: yes (--no-ff)\n"
        "validate: make check\nfinal state: done\n")
    assert "begin_merge" not in names(vcs) and tasks.records[tid].status == "work-review"
    skipped = accept(accept_uc(tasks, vcs), tid, dry_run=True, no_merge=True)
    assert isinstance(skipped, Text)
    lines = skipped.text.splitlines()
    assert lines[0] == "Mark t1 done without merging (--no-merge)"
    assert lines[4:6] == ["merge: no", "validate: skipped"]


def test_accept_merges_validates_and_fires() -> None:
    tasks, tid = make("work-review")
    vcs, validator = FakeVcs(), FakeValidator()
    res = accept(accept_uc(tasks, vcs, validator=validator), tid, yes=True)
    assert res == Done("fake://t1")
    assert vcs.calls[-2:] == [("begin_merge", "samba/t1", "Merge samba/t1: T"),
                              ("commit_merge", "pre0001")]
    assert validator.calls == [("/repo", "t1/accept-validate.log")]
    rec = tasks.records[tid]
    assert rec.status == "done" and any("merged abc1234, validated" in ln for ln in rec.log)


def test_accept_without_a_validate_command_says_so() -> None:
    tasks, tid = make("work-review")
    validator = FakeValidator()
    res = accept(accept_uc(tasks, FakeVcs(), command=None, validator=validator), tid, yes=True)
    assert isinstance(res, Done)
    assert res.notes == ("samba: no validate.command; merged without validation",)
    assert validator.calls == []


def test_accept_no_validate_skips_the_validator() -> None:
    tasks, tid = make("work-review")
    validator = FakeValidator()
    res = accept(accept_uc(tasks, FakeVcs(), validator=validator), tid, yes=True, no_validate=True)
    assert isinstance(res, Done) and validator.calls == []
    assert any("merged abc1234, validation skipped" in ln for ln in tasks.records[tid].log)


def test_accept_no_merge_and_already_merged() -> None:
    tasks, tid = make("work-review")
    vcs = FakeVcs()
    assert isinstance(accept(accept_uc(tasks, vcs), tid, yes=True, no_merge=True), Done)
    assert names(vcs) == []
    assert any("no merge" in ln for ln in tasks.records[tid].log)
    tasks, tid = make("work-review")
    vcs = FakeVcs(merge=MergeAttempt("already", "", "pre0001"))
    res = accept(accept_uc(tasks, vcs), tid, yes=True)
    assert isinstance(res, Done)
    assert res.notes == ("samba: samba/t1 is already merged into main; nothing to merge",)
    assert any("already merged" in ln for ln in tasks.records[tid].log)
    assert "commit_merge" not in names(vcs)


def test_accept_refusals_before_any_change() -> None:
    tasks, tid = make("work-todo")
    res = accept(accept_uc(tasks, FakeVcs()), tid, yes=True)
    assert isinstance(res, Refused) and "work.accept not allowed" in messages(res)
    tasks, tid = make("work-review")
    pre = accept(accept_uc(tasks, FakeVcs(problem="the main checkout has uncommitted changes")),
                 tid, yes=True)
    assert isinstance(pre, Refused) and pre.kind == "refused"
    assert messages(pre) == "samba: the main checkout has uncommitted changes; nothing changed"
    gone = accept(accept_uc(tasks, FakeVcs()), "nope", yes=True)
    assert gone == Refused("usage", ("samba: unknown task 'nope'",))
    busy = accept(accept_uc(tasks, FakeVcs(), lock=FakeLock(held=False)), tid, yes=True)
    assert isinstance(busy, Refused) and "holds .samba/lock" in messages(busy)
    no_tty = accept(accept_uc(tasks, FakeVcs(), FakeTerminal(interactive=False)), tid)
    assert isinstance(no_tty, Refused) and no_tty.kind == "usage"
    declined = accept(accept_uc(tasks, FakeVcs(), FakeTerminal(lines=["n"])), tid)
    assert isinstance(declined, Refused) and declined.kind == "refused"
    assert tasks.records[tid].status == "work-review"


def test_accept_resolves_a_unique_prefix_and_refuses_ambiguous_or_unknown() -> None:
    tasks, _ = make("work-review", "alpha-1")
    for other in ("alpha-2", "beta"):
        tasks.create(Task.new(TaskId(other), "T", "", 3, (), "work-review", FakeClock()))
    vcs = FakeVcs()
    amb = accept(accept_uc(tasks, vcs), "alpha", yes=True)
    assert amb == Refused("usage", (
        "samba: ambiguous task id 'alpha'; candidates:\n  alpha-1\n  alpha-2",))
    unk = accept(accept_uc(tasks, vcs), "zz", yes=True)
    assert unk == Refused("usage", ("samba: unknown task 'zz'",))
    assert names(vcs) == [] and {t.status for t in tasks.records.values()} == {"work-review"}
    assert accept(accept_uc(tasks, vcs), "bet", yes=True) == Done("fake://beta")
    assert tasks.records[TaskId("beta")].status == "done"


@pytest.mark.parametrize("vcs,message,log", [
    (FakeVcs(merge=MergeAttempt("conflict", "a.py, b.py", "pre0001")),
     "samba: merge conflict in: a.py, b.py; merge aborted, task stays in work-review",
     "work.accept: merge failed (conflicts: a.py, b.py)"),
    (FakeVcs(merge=MergeAttempt("error", "boom", "pre0001")),
     "samba: merge failed: boom; merge aborted, task stays in work-review",
     "work.accept: merge failed (boom)"),
    (FakeVcs(commit=CommitResult(False, "hook said no")),
     "samba: merge failed: hook said no; merge aborted, task stays in work-review",
     "work.accept: merge failed (hook said no)"),
])
def test_merge_failures_log_and_stay_in_work_review(vcs: FakeVcs, message: str,
                                                    log: str) -> None:
    tasks, tid = make("work-review")
    res = accept(accept_uc(tasks, vcs), tid, yes=True)
    assert isinstance(res, Refused) and res.kind == "refused"
    assert messages(res) == message
    rec = tasks.records[tid]
    assert rec.status == "work-review" and log in rec.log


def test_validation_failure_aborts_the_merge_and_shows_the_tail() -> None:
    tasks, tid = make("work-review")
    vcs = FakeVcs()
    validator = FakeValidator(failing("noise\n\n  2 failed  \n"))
    res = accept(accept_uc(tasks, vcs, validator=validator), tid, yes=True)
    assert isinstance(res, Refused) and res.kind == "refused"
    assert messages(res) == (
        "samba: validation failed after merge; merge aborted, task stays in work-review: "
        "noise | 2 failed\nsamba: full output: runs/t1/accept-validate.log")
    assert vcs.calls[-1] == ("abort_merge", "pre0001") and "commit_merge" not in names(vcs)
    rec = tasks.records[tid]
    assert rec.status == "work-review"
    assert "work.accept: validation failed after merge: noise | 2 failed" in rec.log


def test_a_timed_out_validation_says_so() -> None:
    tasks, tid = make("work-review")
    validator = FakeValidator(failing("", code=None, timed_out=True))
    res = accept(accept_uc(tasks, FakeVcs(), validator=validator), tid, yes=True)
    assert isinstance(res, Refused)
    assert "work-review: (timed out after 60s)\n" in messages(res)


def test_fire_failure_after_the_merge() -> None:
    tasks, tid = make("work-review")

    class Racing(FakeVcs):
        async def begin_merge(self, branch: str, message: str) -> MergeAttempt:
            tasks.records[tid].status = "stuck"  # a hand move after the checks
            return await super().begin_merge(branch, message)

    res = accept(accept_uc(tasks, Racing(), validator=FakeValidator(passing())), tid, yes=True)
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
        assert isinstance(res, Done) and res.location is not None
        ids.append(TaskId(res.location.removeprefix("fake://")))
    assert ids == ["fix-the-thing", "fix-the-thing-2", "fix-the-thing-3"]
    assert tasks.records[ids[0]].status == "plan-todo"
    skip = uc.run("Other", "body", None, 1, True)
    assert skip == Done("fake://other")
    rec = tasks.records[TaskId("other")]
    assert rec.status == "work-todo" and rec.priority == 1 and rec.body == "body"


def test_dependencies_by_flag_resolve_prefixes_or_fail() -> None:
    tasks, _ = make("work-todo", "alpha-one")
    uc = create_uc(tasks)
    res = uc.run("T2", None, "alpha, alpha-one", 3, False)
    assert res == Done("fake://t2")
    assert tasks.records[TaskId("t2")].depends_on == ("alpha-one",)
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
    assert res == Done("fake://asked-title")
    rec = tasks.records[TaskId("asked-title")]
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
