"""Retry, budget and turn decision policy (spec: orchestrator, Retries and budget; running-claude).

Pure rules, no I/O: the use case in `samba.app.turn` and the orchestrator execute what these return.
"""

from __future__ import annotations

from dataclasses import dataclass

from samba.domain.agent import AgentReport
from samba.domain.states import Stage


@dataclass(frozen=True)
class Budget:
    """The per-task cost cap against what is spent so far."""

    cap: float | None
    spent: float

    @property
    def left(self) -> float | None:
        return None if self.cap is None else self.cap - self.spent

    @property
    def exceeded(self) -> bool:
        left = self.left
        return left is not None and left <= 0


# ---- retries ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class Retry:
    attempts: int  # the failed attempts, this one included
    delay: float  # seconds before the next attempt


@dataclass(frozen=True)
class GiveUp:
    attempts: int


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    base_s: float
    max_backoff_s: float

    def delay_for(self, attempt: int) -> float:
        """Backoff after the `attempt`-th failed attempt (1-based): doubles, capped."""
        return min(self.base_s * 2 ** (attempt - 1), self.max_backoff_s)

    def decide(self, failed_before: int) -> Retry | GiveUp:
        attempts = failed_before + 1
        if attempts < self.max_attempts:
            return Retry(attempts, self.delay_for(attempts))
        return GiveUp(attempts)


def should_reflect(reflect_on_give_up: bool, session_id: str | None, stage: Stage,
                   in_running_folder: bool) -> bool:
    """Whether one last give-up turn runs before the task goes to `stuck` (work stage only)."""
    return reflect_on_give_up and bool(session_id) and stage == "work" and in_running_folder


# ---- after a turn ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Fail:
    error: str


@dataclass(frozen=True)
class Finish:
    event: str  # budget, done, planned, work_blocked, plan_blocked
    what: str
    summary: str = ""


@dataclass(frozen=True)
class RunValidation:
    summary: str


@dataclass(frozen=True)
class RecordQuestions:
    then: Finish


@dataclass(frozen=True)
class Continue:
    pass


Action = Fail | Finish | RunValidation | RecordQuestions | Continue


def budget_finish(budget: Budget, summary: str = "") -> Finish:
    return Finish("budget", f"budget exceeded (${budget.spent:.2f})", summary)


def budget_gate(budget: Budget) -> Finish | None:
    """Checked before each invoke: no turn starts on an exhausted budget."""
    return budget_finish(budget) if budget.exceeded else None


def session_reset_needed(report: AgentReport) -> bool:
    """The resumed session is gone: drop it and send the first prompt once."""
    return report.session_missing


def after_last_turn(max_turns: int) -> Fail:
    return Fail(f"max_turns ({max_turns}) exhausted")


def decide_after_turn(report: AgentReport, stage: Stage, budget: Budget,
                      validate_enabled: bool) -> Action:
    """The one action after a turn. A failure wins over the budget, the budget over the outcome."""
    if report.failure is not None:
        return Fail(report.failure.detail)
    if budget.exceeded:
        return budget_finish(budget, report.summary)
    outcome = report.outcome
    if stage == "work":
        if outcome == "done":
            if validate_enabled:
                return RunValidation(report.summary)
            return Finish("done", "done", report.summary)
        if outcome == "blocked":
            return RecordQuestions(Finish("work_blocked", "blocked", report.summary))
        return Continue()  # continue, or a missing outcome
    if outcome not in ("planned", "blocked") or not report.plan:
        return Fail("planning run returned no valid outcome and plan")
    if outcome == "planned":
        return Finish("planned", "planned", report.summary)
    return RecordQuestions(Finish("plan_blocked", "blocked", report.summary))
