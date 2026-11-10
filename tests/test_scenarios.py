"""Scenario runner (ADR 0012, docs/spec/architecture.md, Scenarios).

Loads `tests/scenarios/*.json` and runs each scenario in-process against the domain. It imports the
domain (and, later, use cases) only: never an adapter, never `samba.tasks`. The fake clock lives
here for that reason.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path
from typing import Any, cast

import pytest

from samba.domain.deps import TaskRef, evaluate
from samba.domain.sidecar import Sidecar
from samba.domain.states import State
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


def sidecar_of(fields: dict[str, Any] | None) -> Sidecar:
    return Sidecar(**copy.deepcopy(fields or {}))  # a copy: effects edit the question records


# ---- transition ------------------------------------------------------------------------------

def pick_row(sc: Scenario) -> Transition | None:
    """The row the scenario's event selects, the way `Machine.fire` selects it (`find_row`), or
    the row a hand move to `hand_move_to` observes (`human_row`)."""
    given = cast(dict[str, Any], sc["given"])
    side = sidecar_of(given.get("sidecar"))
    external = {"deps_met": given.get("deps_met", True),
                "plan_required": given.get("plan_required", False)}

    def holds(name: str) -> bool:
        return stage_guard_ok(name, side) if name.startswith("last_stage=") else external[name]

    state = cast(State, given["state"])
    if "hand_move_to" in sc:
        row = human_row(state, cast(State, sc["hand_move_to"]), side)
        row = row if row is not None and row.event == sc["event"] else None
    else:
        row = find_row(sc["event"], state, holds)
    return row if row is not None and row.actor == sc["actor"] else None


def changed_fields(before: Sidecar, after: Sidecar) -> dict[str, Any]:
    b, a = dataclasses.asdict(before), dataclasses.asdict(after)
    return {k: a[k] for k in a if k != "state" and a[k] != b[k]}


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
    before = sidecar_of(given.get("sidecar"))
    after = sidecar_of(given.get("sidecar"))
    apply_row(row, after, cast(dict[str, object], sc.get("ctx", {})),
              FakeClock(sc.get("clock_time", 0.0)))
    assert after.state == row.dst
    assert changed_fields(before, after) == expect["sidecar"]


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
    row = human_row(sc["src"], sc["dst"], sidecar_of(sc.get("sidecar")))
    assert (row.event if row else None) == sc["expect"]


HUMAN_EVENTS = load("human_events")


@pytest.mark.parametrize("sc", HUMAN_EVENTS, ids=ids(HUMAN_EVENTS))
def test_human_events(sc: Scenario) -> None:
    rows = human_events(sc["state"], sidecar_of(sc.get("sidecar")))
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


def test_every_scenario_file_has_a_known_kind() -> None:
    known = {"transition", "human_row", "human_events", "deps"}
    for path in SCENARIO_DIR.glob("*.json"):
        assert json.loads(path.read_text())["kind"] in known, path.name
