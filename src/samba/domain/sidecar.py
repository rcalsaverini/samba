"""The sidecar record: orchestrator state kept next to a task (spec: states, Sidecar state).

Interim home: a later task of the refactor replaces it with the `Task` aggregate.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Sidecar:
    state: str | None = None  # last known folder, for observed hand moves (spec: states)
    session_id: str | None = None
    last_stage: str | None = None  # "plan" | "work", set at dispatch (spec: states, Sidecar state)
    blocked_cause: str | None = None  # why the task is in question/stuck (CAUSE_*)
    plan_session_id: str | None = None
    plan_approved: bool = False
    attempts: int = 0
    not_before: float | None = None  # unix timestamp
    last_error: str | None = None
    last_outcome: str | None = None
    turns_total: int = 0
    cost_usd_total: float = 0.0
    input_tokens_total: int = 0
    output_tokens_total: int = 0
    branch: str | None = None
    workspace: str | None = None
    first_dispatched_at: float | None = None
    updated_at: float | None = None
    questions: list[dict[str, object]] = field(default_factory=lambda: [])  # spec: states, Sidecar state
