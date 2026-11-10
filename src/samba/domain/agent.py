"""What the core asks of an agent and what it gets back (spec: running-claude, Adapter boundary).

Pure data, no provider types: the adapter maps its own output into `AgentReport`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Outcome = Literal["done", "blocked", "continue", "planned", "missing"]
FailureKind = Literal["stalled", "timeout", "error"]
RequestKind = Literal["plan", "work"]


@dataclass(frozen=True)
class QuestionDraft:
    text: str
    context: str


@dataclass(frozen=True)
class Failure:
    kind: FailureKind
    detail: str  # the text that lands in `## Log` and `last_error`


@dataclass(frozen=True)
class AgentReport:
    outcome: Outcome = "missing"
    summary: str = ""
    plan: str = ""
    assumptions: str = ""
    questions: tuple[QuestionDraft, ...] = ()
    denials: tuple[str, ...] = ()
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    failure: Failure | None = None
    session_missing: bool = False

    @property
    def ok(self) -> bool:
        return self.failure is None


@dataclass(frozen=True)
class AgentRequest:
    prompt: str
    session_id: str
    resume: bool
    system_prompt: str
    max_budget_usd: float | None
    kind: RequestKind
    location: str  # opaque to the core: where the agent works (the adapter reads it as a path)
    log_name: str  # opaque key for the adapter's own run log, `<task id>/<turn number>`


@dataclass(frozen=True)
class Readiness:
    ok: bool
    detail: str = ""
