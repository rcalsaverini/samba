"""The transition table and the single `fire` path (SPEC §4.1).

The table is plain data so a rewrite in another language can reuse it. Rows only change Symphony's
own state: the folder, the sidecar and the task's `## Log`. Effects outside Symphony (a git merge,
appending an answer) belong to the commands that fire an event, never to a row.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from symphony.tasks import (
    CAUSE_BUDGET,
    CAUSE_DEPENDENCY_CYCLE,
    CAUSE_DEPENDENCY_DISCARDED,
    CAUSE_GAVE_UP,
    CAUSE_QUESTION,
    Sidecar,
    SidecarStore,
    State,
    TaskStore,
)

log = logging.getLogger("symphony")

Actor = Literal["symphony", "human"]


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


S: Actor = "symphony"
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
    _t("question", "question.answer", H, "plan-todo", "last_stage=plan", "attempts=0",
       "blocked_cause=None"),
    _t("question", "question.answer", H, "work-todo", "last_stage=work", "attempts=0",
       "blocked_cause=None"),
    _t("stuck", "task.retry", H, "plan-todo", "last_stage=plan", "attempts=0",
       "blocked_cause=None"),
    _t("stuck", "task.retry", H, "work-todo", "last_stage=work", "attempts=0",
       "blocked_cause=None"),
    _t("plan-running", "task.stop", H, "plan-todo"),
    _t("work-running", "task.stop", H, "work-todo"),
    *(_t(s, "task.discard", H, "discarded") for s in DISCARDABLE),
)


# ---- effects --------------------------------------------------------------------------------

Ctx = dict[str, object]
Effect = Callable[[Sidecar, Ctx], None]


def _set(**kw: object) -> Effect:
    def apply(side: Sidecar, _ctx: Ctx) -> None:
        for k, v in kw.items():
            setattr(side, k, v)
    return apply


def _attempts_inc(side: Sidecar, _ctx: Ctx) -> None:
    side.attempts += 1


def _error_from_ctx(side: Sidecar, ctx: Ctx) -> None:
    side.last_error = str(ctx.get("error", ""))


def _retry_delay(side: Sidecar, ctx: Ctx) -> None:
    side.not_before = time.time() + float(str(ctx.get("delay", 0)))


def _first_dispatch(side: Sidecar, _ctx: Ctx) -> None:
    if side.first_dispatched_at is None:
        side.first_dispatched_at = time.time()


EFFECTS: dict[str, Effect] = {
    "attempts=0": _set(attempts=0),
    "attempts+=1": _attempts_inc,
    "not_before=None": _set(not_before=None),
    "not_before=retry": _retry_delay,
    "blocked_cause=None": _set(blocked_cause=None),
    f"blocked_cause={CAUSE_QUESTION}": _set(blocked_cause=CAUSE_QUESTION),
    f"blocked_cause={CAUSE_BUDGET}": _set(blocked_cause=CAUSE_BUDGET),
    f"blocked_cause={CAUSE_GAVE_UP}": _set(blocked_cause=CAUSE_GAVE_UP),
    f"blocked_cause={CAUSE_DEPENDENCY_DISCARDED}": _set(blocked_cause=CAUSE_DEPENDENCY_DISCARDED),
    f"blocked_cause={CAUSE_DEPENDENCY_CYCLE}": _set(blocked_cause=CAUSE_DEPENDENCY_CYCLE),
    "last_error=None": _set(last_error=None),
    "last_error=ctx": _error_from_ctx,
    "last_outcome=done": _set(last_outcome="done"),
    "last_outcome=blocked": _set(last_outcome="blocked"),
    "last_outcome=planned": _set(last_outcome="planned"),
    "last_outcome=retrying": _set(last_outcome="retrying"),
    "last_outcome=failed": _set(last_outcome="failed"),
    "plan_approved=True": _set(plan_approved=True),
    "session_id=None": _set(session_id=None),
    "last_stage=plan": _set(last_stage="plan"),
    "last_stage=work": _set(last_stage="work"),
    "first_dispatched_at=now": _first_dispatch,
}

KNOWN_GUARDS = ("deps_met", "plan_required", "last_stage=plan", "last_stage=work")

for _row in TRANSITIONS:
    for _e in _row.effects:
        assert _e in EFFECTS, f"unknown effect {_e!r} in {_row}"
    for _g in filter(None, _row.guard.split(",")):
        assert _g in KNOWN_GUARDS, f"unknown guard {_g!r} in {_row}"

EVENTS: frozenset[str] = frozenset(r.event for r in TRANSITIONS)

GuardFn = Callable[[str, str, Sidecar], bool]  # (guard name, task id, sidecar) -> holds?


def kv(event: str, **fields: object) -> str:
    parts = [f"event={event}"]
    for k, v in fields.items():
        if v is None:
            continue
        s = str(v)
        if any(c.isspace() for c in s) or "=" in s or '"' in s:
            s = '"' + s.replace('"', "'") + '"'
        parts.append(f"{k}={s}")
    return " ".join(parts)


def log_line(message: str) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"- {stamp} symphony: {message}"


def human_row(src: State, dst: State, side: Sidecar) -> Transition | None:
    """The human row for a hand move `src -> dst`, if the table has one (guards on the sidecar)."""
    for r in TRANSITIONS:
        if r.actor == "human" and r.src == src and r.dst == dst and _own_guards_ok(r, side):
            return r
    return None


def _own_guards_ok(row: Transition, side: Sidecar) -> bool:
    for g in filter(None, row.guard.split(",")):
        if g.startswith("last_stage=") and g != f"last_stage={side.last_stage or 'work'}":
            return False
    return True


def _apply(row: Transition, side: Sidecar, ctx: Ctx) -> None:
    for name in row.effects:
        EFFECTS[name](side, ctx)
    side.state = row.dst


def entry_line(row: Transition, message: str = "") -> str:
    text = f"{row.event}: {row.src} -> {row.dst}"
    return log_line(f"{text}: {message}" if message else text)


class Machine:
    """Applies table rows. `fire` is the only way Symphony moves a task."""

    def __init__(self, tasks: TaskStore, sidecars: SidecarStore,
                 guard: GuardFn | None = None) -> None:
        self.tasks = tasks
        self.sidecars = sidecars
        self.guard = guard

    def _guards_ok(self, row: Transition, task_id: str, side: Sidecar) -> bool:
        for g in filter(None, row.guard.split(",")):
            if g.startswith("last_stage="):
                if g != f"last_stage={side.last_stage or 'work'}":
                    return False
            elif self.guard is None or not self.guard(g, task_id, side):
                return False
        return True

    def fire(self, task_id: str, event: str, *, side: Sidecar | None = None, message: str = "",
             **ctx: object) -> bool:
        """Fire `event` for a task: rename, sidecar effects, `## Log` line. Synchronous, so no
        other tick step can observe it half done. False if no row applies to the task's current
        folder (for example a human moved the file meanwhile) or a guard fails."""
        if event not in EVENTS:
            raise KeyError(f"unknown event {event!r}")
        folder = self.tasks.state_of(task_id)
        if folder is None:
            return False
        side = side if side is not None else self.sidecars.load(task_id)
        row = next((r for r in TRANSITIONS if r.event == event and r.src == folder
                    and self._guards_ok(r, task_id, side)), None)
        if row is None:
            return False
        if not self.tasks.move(task_id, row.src, row.dst):
            return False
        _apply(row, side, ctx)
        self.sidecars.save(task_id, side)
        self.tasks.append_log(task_id, entry_line(row, message))
        log.info(kv("transition", task=task_id, transition=row.event, src=row.src, dst=row.dst,
                    actor=row.actor))
        return True

    def observe(self, task_id: str, row: Transition, side: Sidecar) -> str:
        """Apply a human row for a move already made by hand. Returns the `## Log` line, which
        the caller writes (or defers while an agent runs, SPEC §3.3)."""
        _apply(row, side, {})
        self.sidecars.save(task_id, side)
        log.info(kv("transition", task=task_id, transition=row.event, src=row.src, dst=row.dst,
                    actor=row.actor, observed=True))
        return entry_line(row, "observed hand move")


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
