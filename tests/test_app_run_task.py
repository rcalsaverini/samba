"""`RunTask`, `Finisher`, `PromptBuilder` and `Guard` over the fakes, no orchestrator and no loop."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import cast

from fake_agent import FakeAgentRunner
from fake_journal import FakeJournal
from fake_tasks import FakeTasks
from fake_validator import FakeValidator, passing
from fake_vcs import FakeVcs

from samba.app.finish import Finisher
from samba.app.guard import Guard
from samba.app.machine import Machine
from samba.app.prompt_builder import PromptBuilder
from samba.app.run_task import RunTask
from samba.app.turn import TurnFlow
from samba.domain.agent import AgentReport
from samba.domain.prompts import APPROVED_PLAN_RULE
from samba.domain.settings import (
    AgentSettings,
    Config,
    Hooks,
    Policy,
    Prompts,
    Repository,
    Validation,
)
from samba.domain.states import State
from samba.domain.task import Task
from samba.domain.task_id import TaskId

TID = TaskId("t1")


class Clock:
    def time(self) -> float:
        return 0.0

    def monotonic(self) -> float:
        return 0.0

    def iso_seconds(self) -> str:
        return "2026-01-01T00:00:00+00:00"

    def log_stamp(self) -> str:
        return "2026-01-01 00:00"


class Ids:
    def new_session_id(self) -> str:
        return "s1"


def make_config(*, max_attempts: int = 1, reflect: bool = False, validate: str | None = None,
                require_plan: bool = False, template: str = "Do {{ task.title }}",
                overrides: dict[str, str] | None = None) -> Config:
    return Config(
        policy=Policy(max_turns=3, max_attempts=max_attempts, retry_base_s=1.0,
                      max_retry_backoff_s=1.0, max_cost_usd_per_task=None,
                      reflect_on_give_up=reflect, require_plan=require_plan, max_concurrent=1,
                      poll_interval_s=1.0),
        agent=AgentSettings(command=["claude"], model=None, permission_mode="dontAsk", allow=[],
                            args=[], isolate_user_config=True, turn_timeout_s=60.0,
                            stall_timeout_s=60.0),
        repository=Repository(base_branch="main"),
        prompts=Prompts(template=template, overrides=overrides or {}),
        validation=Validation(command=validate, timeout_s=60.0, tail_lines=20, shell=["bash", "-c"]),
        hooks=Hooks(after_create=None, timeout_s=60.0))


class Rig:
    def __init__(self, status: State, reports: list[AgentReport], *, config: Config | None = None,
                 vcs: FakeVcs | None = None, **fields: object) -> None:
        self.config = config or make_config()
        self.clock = Clock()
        self.tasks = FakeTasks()
        self.vcs = vcs or FakeVcs()
        self.journal = FakeJournal()
        self.agent = FakeAgentRunner(reports)
        task = Task.new(TID, "feature", "", None, (), status, self.clock)
        task.last_stage = "plan" if status.startswith("plan") else "work"
        for key, value in fields.items():
            setattr(task, key, value)
        self.tasks.create(task)
        machine = Machine(self.tasks, self.clock, self.journal,
                          Guard(self.config.policy.require_plan, self.tasks))
        turns = TurnFlow(self.agent, Ids(), self.tasks, self.clock, FakeValidator(passing("ok")),
                         self.journal)
        self.builder = PromptBuilder(self.config, self.tasks, self.vcs)
        finisher = Finisher(self.config.policy, machine, turns, self.builder, self.tasks, self.vcs,
                            self.journal)
        self.run_task = RunTask(self.tasks, self.vcs, turns, self.builder, finisher, self.journal)
        self.turns: list[int] = []

    def run(self) -> None:
        asyncio.run(self.run_task.run(TID, self.turns.append))

    @property
    def task(self) -> Task:
        return self.tasks.records[TID]

    @property
    def log(self) -> str:
        return "\n".join(self.task.log)


# ---- the run of one task ---------------------------------------------------------------------

def test_a_plan_run_ends_in_plan_review() -> None:
    rig = Rig("plan-running", [AgentReport(outcome="planned", plan="do x", summary="ok", cost_usd=0.1)])
    rig.run()
    assert rig.task.status == "plan-review"
    assert "(turns 1, $0.10)" in rig.log
    assert rig.turns == [1]
    assert "workspace_created" in rig.journal.events("info")
    assert rig.task.workspace == "/ws/t1" and rig.task.branch == "samba/t1"
    assert rig.agent.requests[0].kind == "plan"


def test_a_work_run_ends_in_work_review() -> None:
    rig = Rig("work-running", [AgentReport(outcome="done", summary="built", cost_usd=0.25)])
    rig.run()
    assert rig.task.status == "work-review"
    assert "(turns 1, $0.25)" in rig.log and "built" in rig.log
    assert "finished" in rig.journal.events("info")


def test_a_missing_task_is_ignored() -> None:
    rig = Rig("work-running", [])
    del rig.tasks.records[TID]
    rig.run()
    assert rig.vcs.calls == []


def test_a_workspace_failure_retries_then_gives_up() -> None:
    rig = Rig("work-running", [], config=make_config(max_attempts=2),
              vcs=FakeVcs(ensure_error="no worktree"))
    rig.run()
    assert rig.task.status == "work-todo"
    assert "attempt 1 failed: no worktree" in rig.log
    rig.tasks.records[TID].status = "work-running"
    rig.run()
    assert rig.task.status != "work-running"
    assert "gave up after 2 failed attempts: no worktree" in rig.log
    assert rig.journal.events("warning").count("attempt_failed") == 2


def test_a_template_error_fails_the_attempt() -> None:
    rig = Rig("work-running", [], config=make_config(template="Do {{ nope }}"))
    rig.run()
    assert rig.agent.requests == []
    assert "gave up after 1 failed attempts" in rig.log


def test_a_crash_leads_to_a_failed_attempt() -> None:
    rig = Rig("work-running", [])
    asyncio.run(rig.run_task.crashed("t1", RuntimeError("boom")))
    assert "internal error: boom" in rig.log
    assert "worker_crashed" in rig.journal.events("error")


def test_a_crash_of_a_vanished_task_is_only_journaled() -> None:
    rig = Rig("work-running", [])
    del rig.tasks.records[TID]
    asyncio.run(rig.run_task.crashed("t1", RuntimeError("boom")))
    assert "worker_crashed" in rig.journal.events("error")


# ---- reflection on give up -------------------------------------------------------------------

def test_the_give_up_prompt_is_sent_with_resume_when_reflecting_is_allowed() -> None:
    rig = Rig("work-running", [AgentReport(outcome="done")],
              config=make_config(reflect=True), vcs=FakeVcs(ensure_error="no worktree"),
              session_id="sess")
    rig.run()
    assert len(rig.agent.requests) == 1
    request = rig.agent.requests[0]
    assert request.resume and request.session_id == "sess"
    assert "gave up after 1 failed attempts" in rig.log


def test_nothing_is_sent_without_a_session_or_with_the_flag_off() -> None:
    for reflect, session in ((True, None), (False, "sess")):
        rig = Rig("work-running", [], config=make_config(reflect=reflect),
                  vcs=FakeVcs(ensure_error="x"), session_id=session)
        rig.run()
        assert rig.agent.requests == []


# ---- prompts ---------------------------------------------------------------------------------

def builder(config: Config | None = None) -> tuple[PromptBuilder, Task]:
    tasks = FakeTasks()
    task = Task.new(TID, "feature", "body", None, (), "work-running", Clock())
    tasks.create(task)
    return PromptBuilder(config or make_config(), tasks, FakeVcs()), task


def test_the_variables_name_the_task_and_its_workspace() -> None:
    b, task = builder(make_config(validate="make check"))
    v = b.variables(task, "/ws/t1")
    assert v["task.id"] == "t1" and v["task.title"] == "feature" and v["task.body"] == "body"
    assert v["task.path"] == "fake://t1" and v["workspace"] == "/ws/t1"
    assert v["branch"] == "samba/t1" and v["base_branch"] == "main"
    assert v["validate_command"] == "make check" and v["questions"] == ""


def test_answers_are_appended_to_a_custom_prompt_that_lacks_questions() -> None:
    b, task = builder(make_config(overrides={"resume": "Go on {{ task.title }}",
                                             "plan_revise": "Again {{ questions }}"}))
    v = {**b.variables(task, "/ws"), "questions": "Q1: A1"}
    assert b.prompt("resume", v) == "Go on feature\n\nQ1: A1"
    assert b.prompt("plan_revise", v) == "Again Q1: A1"


def test_the_work_setup_carries_the_prompts_and_limits() -> None:
    b, task = builder(make_config(validate="make check"))
    s = b.setup(task, "/ws/t1", "work")
    assert (s.stage, s.prompt, s.resume, s.max_turns, s.validate_enabled) == (
        "work", "Do feature", False, 3, True)
    assert s.first_prompt == "Do feature" and s.location == "/ws/t1"
    assert s.validate_failed("tail").endswith("\n\n```\ntail\n```")
    resumed = replace(task, session_id="sess")
    assert b.setup(resumed, "/ws/t1", "work").resume


def test_the_plan_setup_has_one_turn_and_no_validation() -> None:
    b, task = builder(make_config(validate="make check"))
    s = b.setup(task, "/ws/t1", "plan")
    assert (s.stage, s.max_turns, s.validate_enabled, s.resume) == ("plan", 1, False, False)
    assert s.prompt.startswith("Do feature\n\n")
    assert s.validate_failed("x") == ""
    revising = b.setup(replace(task, plan_session_id="p1"), "/ws/t1", "plan")
    assert revising.resume and revising.first_prompt == s.first_prompt


def test_a_plan_override_replaces_the_first_plan_prompt() -> None:
    b, task = builder(make_config(overrides={"plan": "Plan {{ task.id }}"}))
    assert b.setup(task, "/ws", "plan").prompt == "Plan t1"


def test_an_approved_plan_adds_its_rule_to_the_system_prompt() -> None:
    b, task = builder()
    plain = b.system_prompt(b.variables(task, "/ws"), task)
    approved = replace(task, plan_approved=True)
    assert APPROVED_PLAN_RULE not in plain
    assert b.system_prompt(b.variables(approved, "/ws"), approved).endswith(APPROVED_PLAN_RULE)


# ---- the guard -------------------------------------------------------------------------------

def test_guard_plan_required_and_deps_met() -> None:
    tasks = FakeTasks()
    task = Task.new(TID, "t", "", None, (), cast(State, "work-todo"), Clock())
    tasks.create(task)
    assert Guard(True, tasks)("plan_required", task)
    assert not Guard(False, tasks)("plan_required", task)
    assert not Guard(True, tasks)("plan_required", replace(task, plan_approved=True))
    assert Guard(False, tasks)("deps_met", task)
    blocked = Task.new(TaskId("t2"), "t", "", None, (TaskId("missing"),), "work-todo", Clock())
    assert not Guard(False, tasks)("deps_met", blocked)
    assert not Guard(True, tasks)("unknown", task)
