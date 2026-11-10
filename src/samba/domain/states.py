"""Task states and block causes (spec: states)."""

from __future__ import annotations

from typing import Literal

State = Literal["plan-todo", "plan-running", "plan-review", "work-todo", "work-running",
                "work-review", "question", "stuck", "done", "discarded"]
STATES: tuple[State, ...] = ("plan-todo", "plan-running", "plan-review", "work-todo",
                             "work-running", "work-review", "question", "stuck", "done",
                             "discarded")
Stage = Literal["plan", "work"]

# Values of Sidecar.blocked_cause. Plain strings, not a closed type: more are added later.
CAUSE_QUESTION = "question"
CAUSE_BUDGET = "budget"
CAUSE_GAVE_UP = "gave_up"
CAUSE_STOPPED = "stopped"
CAUSE_DEPENDENCY_DISCARDED = "dependency_discarded"
CAUSE_DEPENDENCY_CYCLE = "dependency_cycle"


def todo_of(stage: Stage) -> State:
    return "plan-todo" if stage == "plan" else "work-todo"


def running_of(stage: Stage) -> State:
    return "plan-running" if stage == "plan" else "work-running"
