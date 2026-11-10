"""The transition table and its pure helpers (spec: states).

The table is plain data so a rewrite in another language can reuse it. Rows only change Samba's
own state: the task's status, its fields and its log. Effects outside Samba (a git merge,
appending an answer) belong to the commands that fire an event, never to a row. The file IO of
firing a row lives in `samba.app.machine.Machine`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from samba.domain.states import (
    CAUSE_BUDGET,
    CAUSE_DEPENDENCY_CYCLE,
    CAUSE_DEPENDENCY_DISCARDED,
    CAUSE_GAVE_UP,
    CAUSE_QUESTION,
    CAUSE_STOPPED,
    BlockedCause,
    LastOutcome,
    Stage,
    State,
)
from samba.domain.task import TODO_STATES, Task
from samba.ports import Clock

Actor = Literal["samba", "human"]


@dataclass(frozen=True)
class Transition:
    src: State
    event: str
    actor: Actor
    dst: State
    guard: str = ""  # comma-separated guard names, all must hold; "" = always
    effects: tuple[str, ...] = ()  # names in EFFECTS, applied in order


def _t(src: State, event: str, actor: Actor, dst: State, guard: str = "",
       *effects: str) -> Transition:
    return Transition(src, event, actor, dst, guard, effects)


S: Actor = "samba"
H: Actor = "human"
RUNNING: tuple[State, ...] = ("plan-running", "work-running")
TODO: tuple[State, ...] = ("plan-todo", "work-todo")
DISCARDABLE: tuple[State, ...] = ("plan-todo", "plan-running", "plan-review", "work-todo",
                                  "work-running", "work-review", "question", "stuck")

TRANSITIONS: tuple[Transition, ...] = (
    _t("plan-todo", "dispatch_plan", S, "plan-running", "deps_met", "not_before=None",
       "blocked_cause=None", "last_stage=plan", "first_dispatched_at=now"),
    _t("work-todo", "dispatch_work", S, "work-running", "deps_met", "not_before=None",
       "blocked_cause=None", "last_stage=work", "first_dispatched_at=now"),
    _t("work-todo", "route_to_plan", S, "plan-todo", "plan_required,deps_met"),
    _t("plan-running", "planned", S, "plan-review", "", "last_outcome=planned", "attempts=0",
       "last_error=None", "blocked_cause=None"),
    _t("plan-running", "plan_blocked", S, "question", "", "last_outcome=blocked",
       "blocked_cause=question"),
    _t("work-running", "done", S, "work-review", "", "last_outcome=done", "attempts=0",
       "last_error=None", "blocked_cause=None"),
    _t("work-running", "work_blocked", S, "question", "", "last_outcome=blocked",
       "blocked_cause=question"),
    _t("plan-running", "budget", S, "stuck", "", "last_outcome=blocked", "blocked_cause=budget"),
    _t("work-running", "budget", S, "stuck", "", "last_outcome=blocked", "blocked_cause=budget"),
    _t("plan-running", "give_up", S, "stuck", "", "attempts+=1", "last_outcome=failed",
       "last_error=ctx", "blocked_cause=gave_up"),
    _t("work-running", "give_up", S, "stuck", "", "attempts+=1", "last_outcome=failed",
       "last_error=ctx", "blocked_cause=gave_up"),
    _t("plan-running", "retry_plan", S, "plan-todo", "", "attempts+=1", "last_error=ctx",
       "not_before=retry", "last_outcome=retrying"),
    _t("work-running", "retry_work", S, "work-todo", "", "attempts+=1", "last_error=ctx",
       "not_before=retry", "last_outcome=retrying"),
    _t("plan-running", "recover", S, "plan-todo"),
    _t("work-running", "recover", S, "work-todo"),
    _t("plan-todo", "dependency_discarded", S, "stuck", "", "last_stage=plan",
       "blocked_cause=dependency_discarded"),
    _t("work-todo", "dependency_discarded", S, "stuck", "", "last_stage=work",
       "blocked_cause=dependency_discarded"),
    _t("plan-todo", "dependency_cycle", S, "stuck", "", "last_stage=plan",
       "blocked_cause=dependency_cycle"),
    _t("work-todo", "dependency_cycle", S, "stuck", "", "last_stage=work",
       "blocked_cause=dependency_cycle"),
    _t("plan-review", "plan.accept", H, "work-todo", "", "plan_approved=True", "session_id=None"),
    _t("plan-review", "plan.reject", H, "plan-todo"),
    _t("work-review", "work.accept", H, "done"),
    _t("work-review", "work.reject", H, "work-todo"),
    # Command-only: `work reject --fresh`. Keep it after work.reject, which `human_row` must pick
    # for an observed hand move (a hand move never resets the session).
    _t("work-review", "work.reject_fresh", H, "work-todo", "", "session_id=None"),
    _t("question", "question.answer", H, "plan-todo", "last_stage=plan", "attempts=0",
       "blocked_cause=None", "questions=dismiss_open"),
    _t("question", "question.answer", H, "work-todo", "last_stage=work", "attempts=0",
       "blocked_cause=None", "questions=dismiss_open"),
    _t("question", "question.answer", H, "plan-todo", "last_stage=unset", "attempts=0",
       "blocked_cause=None", "last_stage=plan", "questions=dismiss_open"),
    _t("question", "question.answer", H, "work-todo", "last_stage=unset", "attempts=0",
       "blocked_cause=None", "last_stage=work", "questions=dismiss_open"),
    _t("stuck", "task.retry", H, "plan-todo", "last_stage=plan", "attempts=0",
       "blocked_cause=None"),
    _t("stuck", "task.retry", H, "work-todo", "last_stage=work", "attempts=0",
       "blocked_cause=None"),
    _t("stuck", "task.retry", H, "plan-todo", "last_stage=unset", "attempts=0",
       "blocked_cause=None", "last_stage=plan"),
    _t("stuck", "task.retry", H, "work-todo", "last_stage=unset", "attempts=0",
       "blocked_cause=None", "last_stage=work"),
    _t("plan-running", "task.stop", H, "stuck", "", "last_stage=plan", "blocked_cause=stopped"),
    _t("work-running", "task.stop", H, "stuck", "", "last_stage=work", "blocked_cause=stopped"),
    *(_t(s, "task.discard", H, "discarded") for s in DISCARDABLE),
)


# ---- effects --------------------------------------------------------------------------------

Ctx = dict[str, object]
Effect = Callable[[Task, Ctx, Clock], None]


def _cause(value: BlockedCause | None) -> Effect:
    def apply(task: Task, _ctx: Ctx, _clock: Clock) -> None:
        task.blocked_cause = value
    return apply


def _outcome(value: LastOutcome) -> Effect:
    def apply(task: Task, _ctx: Ctx, _clock: Clock) -> None:
        task.last_outcome = value
    return apply


def _stage(value: Stage) -> Effect:
    def apply(task: Task, _ctx: Ctx, _clock: Clock) -> None:
        task.last_stage = value
    return apply


def _attempts_zero(task: Task, _ctx: Ctx, _clock: Clock) -> None:
    task.attempts = 0


def _attempts_inc(task: Task, _ctx: Ctx, _clock: Clock) -> None:
    task.attempts += 1


def _not_before_none(task: Task, _ctx: Ctx, _clock: Clock) -> None:
    task.not_before = None


def _last_error_none(task: Task, _ctx: Ctx, _clock: Clock) -> None:
    task.last_error = None


def _plan_approved(task: Task, _ctx: Ctx, _clock: Clock) -> None:
    task.plan_approved = True


def _session_none(task: Task, _ctx: Ctx, _clock: Clock) -> None:
    task.session_id = None


def _error_from_ctx(task: Task, ctx: Ctx, _clock: Clock) -> None:
    task.last_error = str(ctx.get("error", ""))


def _retry_delay(task: Task, ctx: Ctx, clock: Clock) -> None:
    task.not_before = clock.time() + float(str(ctx.get("delay", 0)))


def _first_dispatch(task: Task, _ctx: Ctx, clock: Clock) -> None:
    if task.first_dispatched_at is None:
        task.first_dispatched_at = clock.time()


def _dismiss_open(task: Task, _ctx: Ctx, clock: Clock) -> None:
    task.dismiss_open(clock)


EFFECTS: dict[str, Effect] = {
    "questions=dismiss_open": _dismiss_open,
    "attempts=0": _attempts_zero,
    "attempts+=1": _attempts_inc,
    "not_before=None": _not_before_none,
    "not_before=retry": _retry_delay,
    "blocked_cause=None": _cause(None),
    f"blocked_cause={CAUSE_QUESTION}": _cause(CAUSE_QUESTION),
    f"blocked_cause={CAUSE_BUDGET}": _cause(CAUSE_BUDGET),
    f"blocked_cause={CAUSE_GAVE_UP}": _cause(CAUSE_GAVE_UP),
    f"blocked_cause={CAUSE_STOPPED}": _cause(CAUSE_STOPPED),
    f"blocked_cause={CAUSE_DEPENDENCY_DISCARDED}": _cause(CAUSE_DEPENDENCY_DISCARDED),
    f"blocked_cause={CAUSE_DEPENDENCY_CYCLE}": _cause(CAUSE_DEPENDENCY_CYCLE),
    "last_error=None": _last_error_none,
    "last_error=ctx": _error_from_ctx,
    "last_outcome=done": _outcome("done"),
    "last_outcome=blocked": _outcome("blocked"),
    "last_outcome=planned": _outcome("planned"),
    "last_outcome=retrying": _outcome("retrying"),
    "last_outcome=failed": _outcome("failed"),
    "plan_approved=True": _plan_approved,
    "session_id=None": _session_none,
    "last_stage=plan": _stage("plan"),
    "last_stage=work": _stage("work"),
    "first_dispatched_at=now": _first_dispatch,
}

KNOWN_GUARDS = ("deps_met", "plan_required", "last_stage=plan", "last_stage=work",
                "last_stage=unset")

for _row in TRANSITIONS:
    for _e in _row.effects:
        assert _e in EFFECTS, f"unknown effect {_e!r} in {_row}"
    for _g in filter(None, _row.guard.split(",")):
        assert _g in KNOWN_GUARDS, f"unknown guard {_g!r} in {_row}"

EVENTS: frozenset[str] = frozenset(r.event for r in TRANSITIONS)


# ---- log lines ------------------------------------------------------------------------------

def log_line(message: str, clock: Clock) -> str:
    return f"- {clock.log_stamp()} samba: {message}"


def entry_line(row: Transition, message: str, clock: Clock) -> str:
    text = f"{row.event}: {row.src} -> {row.dst}"
    return log_line(f"{text}: {message}" if message else text, clock)


# ---- guards and row selection ---------------------------------------------------------------

def guard_names(row: Transition) -> list[str]:
    return list(filter(None, row.guard.split(",")))


def stage_guard_ok(guard: str, task: Task) -> bool:
    """`last_stage=plan|work|unset` against the task (unset: no stage recorded)."""
    return guard == f"last_stage={task.last_stage or 'unset'}"


def _own_guards_ok(row: Transition, task: Task) -> bool:
    return all(stage_guard_ok(g, task) for g in guard_names(row) if g.startswith("last_stage="))


def find_row(event: str, src: State, guard_holds: Callable[[str], bool]) -> Transition | None:
    """The first row for `event` in `src` whose guards all hold (`guard_holds` is asked for each
    guard name). The one place that picks a row, shared by `Machine.fire` and the scenarios."""
    return next((r for r in TRANSITIONS if r.event == event and r.src == src
                 and all(guard_holds(g) for g in guard_names(r))), None)


def human_row(src: State, dst: State, task: Task) -> Transition | None:
    """The human row for a hand move `src -> dst`, if the table has one (guards on the task)."""
    for r in TRANSITIONS:
        if r.actor == "human" and r.src == src and r.dst == dst and _own_guards_ok(r, task):
            return r
    return None


def human_events(src: State, task: Task) -> list[Transition]:
    """The human events legal in `src`, one row per event name, in table order. Only the
    `last_stage=*` guards are checked: human rows have no other guards."""
    rows: list[Transition] = []
    for r in TRANSITIONS:
        if (r.actor == "human" and r.src == src and _own_guards_ok(r, task)
                and all(r.event != x.event for x in rows)):
            rows.append(r)
    return rows


def apply_row(row: Transition, task: Task, ctx: Ctx, clock: Clock) -> bool:
    """Apply the row's effects and the destination status. True if the question records changed.
    A todo destination stamps `queued_at`, the dispatch order key."""
    before = task.questions
    for name in row.effects:
        EFFECTS[name](task, ctx, clock)
    task.status = row.dst
    if row.dst in TODO_STATES:
        task.queued_at = clock.time()
    return task.questions is not before


# ---- rendering ------------------------------------------------------------------------------

TABLE_BEGIN = "<!-- transitions:begin -->"
TABLE_END = "<!-- transitions:end -->"


def render_markdown_table() -> str:
    def cell(items: str) -> str:
        return f"`{items}`" if items else ""
    lines = ["| Event | From | To | Who | Guard | Effects |", "|---|---|---|---|---|---|"]
    for r in TRANSITIONS:
        lines.append(f"| `{r.event}` | `{r.src}` | `{r.dst}` | {r.actor} | {cell(r.guard)} | "
                     f"{', '.join(f'`{e}`' for e in r.effects)} |")
    return "\n".join(lines)
