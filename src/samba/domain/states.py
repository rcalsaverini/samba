"""Task states and block causes (spec: states)."""

from __future__ import annotations

from typing import Literal

State = Literal["plan-todo", "plan-running", "plan-review", "work-todo", "work-running",
                "work-review", "question", "stuck", "done", "discarded"]
STATES: tuple[State, ...] = ("plan-todo", "plan-running", "plan-review", "work-todo",
                             "work-running", "work-review", "question", "stuck", "done",
                             "discarded")
Stage = Literal["plan", "work"]

# Closed sets (a spec decision of the Task aggregate: an unknown stored value reads as None).
BlockedCause = Literal["question", "budget", "gave_up", "stopped", "dependency_discarded",
                       "dependency_cycle"]
BLOCKED_CAUSES: tuple[BlockedCause, ...] = ("question", "budget", "gave_up", "stopped",
                                            "dependency_discarded", "dependency_cycle")
LastOutcome = Literal["done", "blocked", "failed", "retrying", "planned"]
LAST_OUTCOMES: tuple[LastOutcome, ...] = ("done", "blocked", "failed", "retrying", "planned")

CAUSE_QUESTION: BlockedCause = "question"
CAUSE_BUDGET: BlockedCause = "budget"
CAUSE_GAVE_UP: BlockedCause = "gave_up"
CAUSE_STOPPED: BlockedCause = "stopped"
CAUSE_DEPENDENCY_DISCARDED: BlockedCause = "dependency_discarded"
CAUSE_DEPENDENCY_CYCLE: BlockedCause = "dependency_cycle"


def todo_of(stage: Stage) -> State:
    return "plan-todo" if stage == "plan" else "work-todo"


def running_of(stage: Stage) -> State:
    return "plan-running" if stage == "plan" else "work-running"
