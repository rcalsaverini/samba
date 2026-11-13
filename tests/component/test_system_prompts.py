"""What the system prompt of a run tells the agent, as `PromptBuilder` renders it (spec: prompts)."""

from __future__ import annotations

from dataclasses import replace

from fake_tasks import FakeTasks
from fake_vcs import FakeVcs
from test_app_run_task import Clock, make_config

from samba.app.prompt_builder import PromptBuilder
from samba.domain.settings import DEFAULT_ALLOW, DEFAULT_PLANNING_ALLOW, Config
from samba.domain.states import State
from samba.domain.task import Task
from samba.domain.task_id import TaskId

ADR_WRITES = ("adr accept", "adr reject", "adr supersede")


def default_config() -> Config:
    config = make_config()
    agent = replace(config.agent, allow=list(DEFAULT_ALLOW),
                    planning_allow=list(DEFAULT_PLANNING_ALLOW))
    return replace(config, agent=agent)


def system_prompt(status: State, config: Config | None = None) -> str:
    tasks = FakeTasks()
    task = Task.new(TaskId("t1"), "feature", "", None, (), status, Clock())
    tasks.create(task)
    builder = PromptBuilder(config or default_config(), tasks, FakeVcs())
    stage = "plan" if status.startswith("plan") else "work"
    return builder.setup(task, "/ws/t1", stage).system_prompt


def test_the_default_allow_lists_grant_only_the_read_adr_commands() -> None:
    for allow in (DEFAULT_ALLOW, DEFAULT_PLANNING_ALLOW):
        assert "Bash(samba adr list:*)" in allow and "Bash(samba adr show:*)" in allow
        assert not any(w in a for a in allow for w in ADR_WRITES)
        assert "Bash(samba adr:*)" not in allow


def test_both_system_prompts_name_the_read_adr_commands() -> None:
    for status in ("work-running", "plan-running"):
        text = system_prompt(status)
        assert "samba adr list" in text and "samba adr show" in text, status


def test_the_work_protocol_requires_the_spec_step_and_proposed_adrs() -> None:
    text = system_prompt("work-running")
    assert "project's spec" in text
    assert "before reporting `done`" in text
    assert "docs/adr/" in text and "status `proposed`" in text
    assert "docs/spec" not in text  # the spec location is the project's, not hard-coded


def test_the_plan_protocol_asks_for_a_spec_changes_section() -> None:
    text = system_prompt("plan-running")
    assert "Spec changes" in text and "none, because" in text
    assert "docs/spec" not in text
