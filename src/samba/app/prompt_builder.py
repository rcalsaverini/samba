"""`PromptBuilder`: the prompt variables and the turn setup of a run (spec: prompts, Which prompt is sent)."""

from __future__ import annotations

import re

from samba.app.turn import TurnSetup
from samba.domain.ports import Tasks, Vcs
from samba.domain.prompts import (
    APPROVED_PLAN_RULE,
    DEFAULT_PROMPTS,
    PLAN_PROTOCOL,
    PROTOCOL,
    allowed_tools_note,
    validate_note,
)
from samba.domain.questions import open_questions, round_pairs
from samba.domain.settings import Config
from samba.domain.states import Stage
from samba.domain.task import Task
from samba.domain.template import render

_VARIABLE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}")


class PromptBuilder:
    def __init__(self, config: Config, tasks: Tasks, vcs: Vcs) -> None:
        self.config = config
        self.tasks = tasks
        self.vcs = vcs

    def variables(self, task: Task, ws: str) -> dict[str, str]:
        return {
            "task.id": task.id,
            "task.title": task.title,
            "task.body": task.body,
            "task.path": self.tasks.location(task.id),
            "workspace": ws,
            "branch": self.vcs.branch_name(task.id),
            "base_branch": self.config.repository.base_branch,
            "attempt": str(task.attempts),
            "validate_command": self.config.validation.command or "",
            # The answered round, for the first run after a question (spec: prompts, Which prompt is sent).
            "questions": (round_pairs(task.questions)
                          if task.last_outcome == "blocked" and not open_questions(task.questions)
                          else ""),
        }

    def system_prompt(self, variables: dict[str, str], task: Task) -> str:
        agent = self.config.agent
        text = render(PROTOCOL, {
            **variables,
            "validate_note": validate_note(self.config.validation.command),
            "allowed_tools": allowed_tools_note(agent.allow, agent.permission_mode),
        })
        if task.plan_approved:
            text = text.rstrip("\n") + "\n" + APPROVED_PLAN_RULE
        return text

    def prompt(self, key: str, variables: dict[str, str]) -> str:
        template = self.config.prompts.overrides.get(key) or DEFAULT_PROMPTS[key]
        text = render(template, variables).rstrip()
        questions = variables.get("questions", "")
        # A custom prompt without {{ questions }} must not lose the answers.
        if key in ("resume", "plan_revise") and questions and "questions" not in _VARIABLE.findall(
                template):
            text += "\n\n" + questions
        return text

    def first_plan_prompt(self, variables: dict[str, str]) -> str:
        prompts = self.config.prompts
        override = prompts.overrides.get("plan")
        if override:
            return render(override, variables)
        return render(prompts.template, variables) + "\n\n" + DEFAULT_PROMPTS["plan"]

    def setup(self, task: Task, ws: str, stage: Stage) -> TurnSetup:
        """The prompts and limits of a run."""
        config = self.config
        variables = self.variables(task, ws)
        cap = config.policy.max_cost_usd_per_task
        if stage == "plan":
            system_prompt = render(PLAN_PROTOCOL, {
                **variables,
                "allowed_tools": allowed_tools_note(config.agent.planning_allow, "dontAsk"),
            })
            first = self.first_plan_prompt(variables)
            resume = bool(task.plan_session_id)
            return TurnSetup(
                stage="plan", system_prompt=system_prompt, location=ws,
                prompt=self.prompt("plan_revise", variables) if resume else first,
                resume=resume, first_prompt=first, continue_prompt="",
                validate_failed=lambda tail: "", max_turns=1, validate_enabled=False,
                max_cost_usd=cap)
        first = render(config.prompts.template, variables)
        resume = bool(task.session_id)
        failed = self.prompt("validate_failed", variables)
        return TurnSetup(
            stage="work", system_prompt=self.system_prompt(variables, task), location=ws,
            prompt=self.prompt("resume", variables) if resume else first, resume=resume,
            first_prompt=first, continue_prompt=self.prompt("continue", variables),
            validate_failed=lambda tail: failed + "\n\n```\n" + tail + "\n```",
            max_turns=config.policy.max_turns, validate_enabled=bool(config.validation.command),
            max_cost_usd=cap)
