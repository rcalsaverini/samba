"""Scenario runner (ADR 0012, docs/spec/architecture.md, Scenarios).

Loads `tests/scenarios/*.json` and runs each scenario in-process against the domain. It imports the
domain and use cases only: never an adapter (`FakeTasks` stands in for the store). The fake clock lives
here for that reason.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
from pathlib import Path
from typing import Any, cast

import pytest
from fake_agent import FakeAgentRunner
from fake_journal import FakeJournal
from fake_tasks import FakeTasks

from samba.app.turn import TurnFlow, TurnSetup
from samba.domain.agent import AgentReport, Failure, QuestionDraft
from samba.domain.deps import TaskRef, evaluate
from samba.domain.policy import (
    Action,
    Budget,
    Continue,
    Fail,
    Finish,
    GiveUp,
    RecordQuestions,
    Retry,
    RetryPolicy,
    RunValidation,
    after_last_turn,
    budget_gate,
    decide_after_turn,
    session_reset_needed,
    should_reflect,
)
from samba.domain.questions import Question
from samba.domain.states import State
from samba.domain.task import Task
from samba.domain.task_id import TaskId
from samba.domain.transitions import (
    TRANSITIONS,
    Transition,
    apply_row,
    find_row,
    guard_names,
    human_events,
    human_row,
    stage_guard_ok,
)

SCENARIO_DIR = Path(__file__).resolve().parent / "scenarios"
FAKE_ISO = "2026-01-01T00:00:00+00:00"

Scenario = dict[str, Any]


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def time(self) -> float:
        return self.now

    def monotonic(self) -> float:
        return self.now

    def iso_seconds(self) -> str:
        return FAKE_ISO

    def log_stamp(self) -> str:
        return "2026-01-01 00:00"


def load(kind: str) -> list[Scenario]:
    scenarios: list[Scenario] = []
    for path in sorted(SCENARIO_DIR.glob("*.json")):
        doc = cast(dict[str, Any], json.loads(path.read_text()))
        if doc["kind"] == kind:
            scenarios.extend({**sc, "_file": path.name} for sc in doc["scenarios"])
    return scenarios


def ids(scenarios: list[Scenario]) -> list[str]:
    return [f"{sc['_file']}::{sc['name']}" for sc in scenarios]


def question_of(fields: dict[str, Any]) -> Question:
    """A question from the fields a scenario names; the rest take neutral defaults."""
    return Question(**cast(dict[str, Any], {"stage": "plan", "text": "", **fields}))


def task_of(status: State, fields: dict[str, Any] | None) -> Task:
    """A task in `status` with the fields a scenario names set on it."""
    task = Task(id=TaskId("t1"), title="t", body="", priority=None, depends_on=(), status=status)
    for key, value in copy.deepcopy(fields or {}).items():
        if key == "questions":
            value = tuple(question_of(q) for q in value)
        setattr(task, key, value)
    return task


# ---- transition ------------------------------------------------------------------------------

def pick_row(sc: Scenario) -> Transition | None:
    """The row the scenario's event selects, the way `Machine.fire` selects it (`find_row`), or
    the row a hand move to `hand_move_to` observes (`human_row`)."""
    given = cast(dict[str, Any], sc["given"])
    state = cast(State, given["state"])
    side = task_of(state, given.get("task"))
    external = {"deps_met": given.get("deps_met", True),
                "plan_required": given.get("plan_required", False)}

    def holds(name: str) -> bool:
        return stage_guard_ok(name, side) if name.startswith("last_stage=") else external[name]

    if "hand_move_to" in sc:
        row = human_row(state, cast(State, sc["hand_move_to"]), side)
        row = row if row is not None and row.event == sc["event"] else None
    else:
        row = find_row(sc["event"], state, holds)
    return row if row is not None and row.actor == sc["actor"] else None


def changed_fields(before: Task, after: Task) -> dict[str, Any]:
    """The fields a row changed, except the status and the dispatch order stamp (checked apart)."""
    names = [f.name for f in dataclasses.fields(Task) if f.name not in ("status", "queued_at")]
    return {n: getattr(after, n) for n in names if getattr(after, n) != getattr(before, n)}


def expected_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return {k: tuple(question_of(q) for q in v) if k == "questions" else v
            for k, v in fields.items()}


TRANSITION = load("transition")


@pytest.mark.parametrize("sc", TRANSITION, ids=ids(TRANSITION))
def test_transition(sc: Scenario) -> None:
    given = cast(dict[str, Any], sc["given"])
    expect = cast(dict[str, Any], sc["expect"])
    row = pick_row(sc)
    if not expect["fires"]:
        assert row is None
        return
    assert row is not None, "no row selected"
    assert row.dst == expect["state"]
    assert guard_names(row) == expect["guards"]
    assert list(row.effects) == expect["effects"]
    before = task_of(given["state"], given.get("task"))
    after = task_of(given["state"], given.get("task"))
    apply_row(row, after, cast(dict[str, object], sc.get("ctx", {})),
              FakeClock(sc.get("clock_time", 0.0)))
    assert after.status == row.dst
    assert changed_fields(before, after) == expected_fields(expect["task"])


def test_every_table_row_is_covered() -> None:
    hit = {(r.src, r.event, r.guard, r.dst) for sc in TRANSITION
           if sc["expect"]["fires"] and (r := pick_row(sc)) is not None}
    missing = [r for r in TRANSITIONS if (r.src, r.event, r.guard, r.dst) not in hit]
    assert not missing, "rows without a scenario: " + ", ".join(
        f"{r.src} {r.event} [{r.guard}] -> {r.dst}" for r in missing)


# ---- hand moves and legal events -------------------------------------------------------------

HUMAN_ROW = load("human_row")


@pytest.mark.parametrize("sc", HUMAN_ROW, ids=ids(HUMAN_ROW))
def test_human_row(sc: Scenario) -> None:
    row = human_row(sc["src"], sc["dst"], task_of(sc["src"], sc.get("task")))
    assert (row.event if row else None) == sc["expect"]


HUMAN_EVENTS = load("human_events")


@pytest.mark.parametrize("sc", HUMAN_EVENTS, ids=ids(HUMAN_EVENTS))
def test_human_events(sc: Scenario) -> None:
    rows = human_events(sc["state"], task_of(sc["state"], sc.get("task")))
    assert [r.event for r in rows] == sc["expect"]


# ---- dependencies ----------------------------------------------------------------------------

DEPS = load("deps")


@pytest.mark.parametrize("sc", DEPS, ids=ids(DEPS))
def test_deps(sc: Scenario) -> None:
    snapshot = {t["id"]: TaskRef(t["id"], t["status"], tuple(t.get("depends_on", [])))
                for t in cast(list[dict[str, Any]], sc["tasks"])}
    status = evaluate(snapshot, sc["task"])
    expect = cast(dict[str, Any], sc["expect"])
    assert status.kind == expect["kind"]
    assert list(status.waiting) == expect["waiting"]
    assert list(status.unknown) == expect["unknown"]


# ---- retry, budget, turn decisions -----------------------------------------------------------

RETRY = load("retry_policy")


@pytest.mark.parametrize("sc", RETRY, ids=ids(RETRY))
def test_retry_policy(sc: Scenario) -> None:
    decision = RetryPolicy(**sc["settings"]).decide(sc["failed_before"])
    expect = cast(dict[str, Any], sc["expect"])
    if expect["action"] == "retry":
        assert decision == Retry(expect["attempts"], expect["delay"])
    else:
        assert decision == GiveUp(expect["attempts"])


BUDGET = load("budget")


@pytest.mark.parametrize("sc", BUDGET, ids=ids(BUDGET))
def test_budget(sc: Scenario) -> None:
    budget = Budget(sc["cap"], sc["spent"])
    assert budget.left == sc["expect"]["left"]
    assert budget.exceeded is sc["expect"]["exceeded"]


def report_of(fields: dict[str, Any]) -> AgentReport:
    data = dict(fields)
    if "failure" in data:
        data["failure"] = Failure(**data["failure"])
    data["questions"] = tuple(QuestionDraft(**q) for q in data.get("questions", []))
    data["denials"] = tuple(data.get("denials", []))
    return AgentReport(**data)


def budget_of(fields: dict[str, Any] | None) -> Budget:
    return Budget(**fields) if fields else Budget(None, 0.0)


def action_dict(action: Action) -> dict[str, Any]:
    match action:
        case Fail():
            return {"action": "fail", "error": action.error}
        case Finish():
            return {"action": "finish", **dataclasses.asdict(action)}
        case RunValidation():
            return {"action": "run_validation", "summary": action.summary}
        case RecordQuestions():
            return {"action": "record_questions", **dataclasses.asdict(action.then)}
        case Continue():
            return {"action": "continue"}


TURN_DECISION = load("turn_decision")


@pytest.mark.parametrize("sc", TURN_DECISION, ids=ids(TURN_DECISION))
def test_turn_decision(sc: Scenario) -> None:
    action = decide_after_turn(report_of(sc["report"]), sc["stage"], budget_of(sc.get("budget")),
                               sc["validate"])
    assert action_dict(action) == sc["expect"]


TURN_RULE = load("turn_rule")


@pytest.mark.parametrize("sc", TURN_RULE, ids=ids(TURN_RULE))
def test_turn_rule(sc: Scenario) -> None:
    rule = sc["rule"]
    if rule == "session_reset":
        got: object = session_reset_needed(report_of(sc["report"]))
    elif rule == "budget_gate":
        gate = budget_gate(budget_of(sc["budget"]))
        got = None if gate is None else dataclasses.asdict(gate)
    elif rule == "exhausted":
        got = after_last_turn(sc["max_turns"]).error
    else:
        a = sc["args"]
        got = should_reflect(a["flag"], a["session"], a["stage"], a["in_running"])
    assert got == sc["expect"]


# ---- the turn flow with the fake runner ------------------------------------------------------

class SeqIds:
    def __init__(self) -> None:
        self.n = 0

    def new_session_id(self) -> str:
        self.n += 1
        return f"s{self.n}"


TURN_FLOW = load("turn_flow")


@pytest.mark.parametrize("sc", TURN_FLOW, ids=ids(TURN_FLOW))
def test_turn_flow(sc: Scenario) -> None:
    s = cast(dict[str, Any], sc["setup"])
    expect = cast(dict[str, Any], sc["expect"])
    setup = TurnSetup(
        stage=s["stage"], system_prompt="SYS", location="/ws", prompt=s["prompt"],
        resume=s["resume"], first_prompt="FIRST", continue_prompt="CONT",
        validate_failed=lambda tail: f"VF:{tail}", max_turns=s["max_turns"],
        validate_enabled=s.get("validate_enabled", False), max_cost_usd=s.get("max_cost_usd"))
    store = FakeTasks()
    store.create(task_of("plan-running" if setup.stage == "plan" else "work-running",
                         sc.get("task")))
    side = store.get(TaskId("t1"))
    assert side is not None
    agent = FakeAgentRunner([report_of(r) for r in sc["reports"]])
    flow = TurnFlow(agent, SeqIds(), store, FakeClock(), FakeJournal())
    validations = iter(sc.get("validate", []))
    calls: list[int] = []

    async def validate() -> tuple[bool, str]:
        calls.append(1)
        ok, tail = next(validations)
        return ok, tail

    turns: list[int] = []
    result = asyncio.run(flow.run(side, setup, validate, turns.append))
    if expect["result"]["kind"] == "fail":
        assert result == Fail(expect["result"]["error"])
    else:
        r = expect["result"]
        assert result == Finish(r["event"], r["what"], r["summary"])
    assert [{"prompt": q.prompt, "resume": q.resume, "kind": q.kind, "session_id": q.session_id,
             "max_budget_usd": q.max_budget_usd} for q in agent.requests] == expect["requests"]
    sections = {name: text for name, text in (("Plan", side.plan), ("Assumptions", side.assumptions))
                if text}
    assert sections == expect["sections"]
    assert len(side.questions) == expect["questions"]
    assert len(calls) == expect["validate_calls"]
    assert turns == list(range(1, len(turns) + 1))
    for key, value in expect["task"].items():
        assert getattr(side, key) == value, key
    wanted = expect.get("log", [])
    assert len(side.log) == len(wanted)
    for want, got in zip(wanted, side.log):
        assert want in got


def test_every_scenario_file_has_a_known_kind() -> None:
    known = {"transition", "human_row", "human_events", "deps", "retry_policy", "budget",
             "turn_decision", "turn_rule", "turn_flow"}
    for path in SCENARIO_DIR.glob("*.json"):
        assert json.loads(path.read_text())["kind"] in known, path.name
