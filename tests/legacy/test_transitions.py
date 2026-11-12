"""Black-box tests for the transition table (spec: states). Must not import the samba package.

The table is read from `samba dev transitions`. Every row has a scenario below, and a coverage test
fails when a row is added without one.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from legacy_support import Sandbox, stop, wait_for

STATES_DOC = Path(__file__).parent.parent.parent / "docs" / "spec" / "states.md"
BLOCKER = ["no-such-task"]  # an unknown dependency keeps a todo task where it is

# Live-orchestrator tests poll conditions with a generous deadline (polling returns as soon as the
# condition holds, so this costs nothing). The fake agent hangs far longer than the deadline, and the
# stall/turn timeouts are raised above it, so a slow machine never lets a timeout fire first.
GENEROUS_S = 90
HANG_S = 600
LONG_AGENT = {"turn_timeout_s": 900, "stall_timeout_s": 900}


def table(sb: Sandbox) -> dict[tuple[str, str, str, str], dict[str, str]]:
    """`samba dev transitions` parsed into {(src, event, guard, dst): row}."""
    res = sb.run("dev", "transitions")
    assert res.returncode == 0, res.stderr
    rows: dict[tuple[str, str, str, str], dict[str, str]] = {}
    for line in res.stdout.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [c.strip().replace("`", "") for c in line.strip().strip("|").split("|")]
        event, src, dst, who, guard, effects = cells
        rows[(src, event, guard, dst)] = {"who": who, "effects": effects}
    return rows


def safe_text(sb: Sandbox, task_id: str) -> str:
    try:
        return sb.task_text(task_id)
    except (AssertionError, FileNotFoundError):
        return ""


# ---- scenarios: Samba rows ---------------------------------------------------------------

Scenario = Callable[[Sandbox], None]


def plain_run(task_state: str, **side: object) -> Scenario:
    def go(sb: Sandbox) -> None:
        sb.add_task("t1", state=task_state)
        if side:
            sb.write_sidecar("t1", dict(side))
        sb.run_idle()
    return go


def with_workflow(run: Scenario, **overrides: Any) -> Scenario:
    def go(sb: Sandbox) -> None:
        sb.write_workflow(**overrides)
        run(sb)
    return go


def steps_then(run: Scenario, *steps: dict[str, Any]) -> Scenario:
    def go(sb: Sandbox) -> None:
        sb.steps("t1", *steps)
        run(sb)
    return go


def retry_scenario(folder: str) -> Scenario:
    def go(sb: Sandbox) -> None:
        sb.write_workflow(retry_base_s=60, max_retry_backoff_s=60)
        sb.add_task("t1", state=folder)
        sb.steps("t1", {"is_error": True})
        proc = sb.popen("run", "--exit-when-idle")
        try:
            wait_for(lambda: "retry_" in safe_text(sb, "t1") and sb.state_of("t1") == folder,
                     timeout=GENEROUS_S)
        finally:
            stop(proc)
        assert sb.sidecar("t1")["attempts"] == 1
        assert sb.sidecar("t1")["last_outcome"] == "retrying"
        assert sb.sidecar("t1")["not_before"]
    return go


def dependency_scenario(folder: str, cycle: bool) -> Scenario:
    def go(sb: Sandbox) -> None:
        if cycle:
            sb.add_task("t1", state=folder, depends_on=["t1"])
        else:
            sb.add_task("gone", state="discarded")
            sb.add_task("t1", state=folder, depends_on=["gone"])
        sb.run_idle()
        cause = "dependency_cycle" if cycle else "dependency_discarded"
        assert sb.sidecar("t1")["blocked_cause"] == cause
    return go


def check_sidecar(run: Scenario, **expected: object) -> Scenario:
    def go(sb: Sandbox) -> None:
        run(sb)
        side = sb.sidecar("t1")
        for k, v in expected.items():
            assert side[k] == v, (k, side)
    return go


FAIL_ONCE = {"is_error": True}
CAP = {"max_cost_usd_per_task": 0.15}
GIVE_UP = {"max_attempts": 1, "reflect_on_give_up": False}

SAMBA_ROWS: dict[tuple[str, str, str], Scenario] = {
    ("plan-todo", "dispatch_plan", "deps_met"):
        check_sidecar(plain_run("plan-todo"), last_stage="plan"),
    ("work-todo", "dispatch_work", "deps_met"):
        check_sidecar(plain_run("work-todo"), last_stage="work"),
    ("work-todo", "route_to_plan", "plan_required,deps_met"):
        with_workflow(plain_run("work-todo"), planning={"require_plan": True}),
    ("plan-running", "planned", ""):
        check_sidecar(plain_run("plan-todo"), last_outcome="planned", attempts=0),
    ("plan-running", "plan_blocked", ""):
        check_sidecar(steps_then(plain_run("plan-todo"), {"outcome": "blocked", "plan": "p"}),
                      blocked_cause="question"),
    ("work-running", "done", ""):
        check_sidecar(plain_run("work-todo"), last_outcome="done", attempts=0),
    ("work-running", "work_blocked", ""):
        check_sidecar(steps_then(plain_run("work-todo"), {"outcome": "blocked"}),
                      blocked_cause="question"),
    ("plan-running", "budget", ""):
        check_sidecar(with_workflow(steps_then(plain_run("plan-todo"), {"cost": 0.2}), **CAP),
                      blocked_cause="budget"),
    ("work-running", "budget", ""):
        check_sidecar(with_workflow(steps_then(plain_run("work-todo"),
                                               {"outcome": "continue", "cost": 0.2}), **CAP),
                      blocked_cause="budget"),
    ("plan-running", "give_up", ""):
        check_sidecar(with_workflow(steps_then(plain_run("plan-todo"), FAIL_ONCE), **GIVE_UP),
                      blocked_cause="gave_up", attempts=1, last_outcome="failed"),
    ("work-running", "give_up", ""):
        check_sidecar(with_workflow(steps_then(plain_run("work-todo"), FAIL_ONCE), **GIVE_UP),
                      blocked_cause="gave_up", attempts=1, last_outcome="failed"),
    ("plan-running", "retry_plan", ""): retry_scenario("plan-todo"),
    ("work-running", "retry_work", ""): retry_scenario("work-todo"),
    ("plan-running", "recover", ""): plain_run("plan-running", last_stage="plan"),
    ("work-running", "recover", ""): plain_run("work-running", last_stage="work"),
    ("plan-todo", "dependency_discarded", ""): dependency_scenario("plan-todo", cycle=False),
    ("work-todo", "dependency_discarded", ""): dependency_scenario("work-todo", cycle=False),
    ("plan-todo", "dependency_cycle", ""): dependency_scenario("plan-todo", cycle=True),
    ("work-todo", "dependency_cycle", ""): dependency_scenario("work-todo", cycle=True),
}


@pytest.mark.parametrize("key", list(SAMBA_ROWS), ids=lambda k: f"{k[1]}:{k[0]}")
def test_samba_row(sb: Sandbox, key: tuple[str, str, str]) -> None:
    src, event, _guard = key
    (dst,) = {r[3] for r in table(sb) if r[:3] == key}  # Samba rows have one destination
    SAMBA_ROWS[key](sb)
    assert f"{event}: {src} -> {dst}" in sb.log_section("t1")
    assert f"event=transition task=t1 transition={event} src={src} dst={dst}" in sb.log_text()


# ---- scenarios: human rows (observed hand moves) --------------------------------------------

HumanCase = tuple[dict[str, object], dict[str, object]]  # (sidecar before, sidecar expected after)

# Keys are (src, event, guard, dst): a guard can have two destinations.
HUMAN_ROWS: dict[tuple[str, str, str, str], HumanCase] = {
    ("plan-review", "plan.accept", "", "work-todo"):
        ({"session_id": "s", "plan_session_id": "p"},
         {"plan_approved": True, "session_id": None, "state": "work-todo"}),
    ("plan-review", "plan.reject", "", "plan-todo"): ({}, {"state": "plan-todo"}),
    ("work-review", "work.accept", "", "done"): ({}, {"state": "done"}),
    ("work-review", "work.reject", "", "work-todo"): ({}, {"state": "work-todo"}),
    ("question", "question.answer", "last_stage=plan", "plan-todo"):
        ({"last_stage": "plan", "attempts": 2, "blocked_cause": "question"},
         {"attempts": 0, "blocked_cause": None, "state": "plan-todo"}),
    ("question", "question.answer", "last_stage=work", "work-todo"):
        ({"last_stage": "work", "attempts": 2, "blocked_cause": "question"},
         {"attempts": 0, "blocked_cause": None, "state": "work-todo"}),
    ("stuck", "task.retry", "last_stage=plan", "plan-todo"):
        ({"last_stage": "plan", "attempts": 3, "blocked_cause": "gave_up"},
         {"attempts": 0, "blocked_cause": None, "state": "plan-todo"}),
    ("stuck", "task.retry", "last_stage=work", "work-todo"):
        ({"last_stage": "work", "attempts": 3, "blocked_cause": "budget"},
         {"attempts": 0, "blocked_cause": None, "state": "work-todo"}),
    # No last_stage recorded: the folder the human chose decides the stage.
    **{(src, event, "last_stage=unset", dst):
       ({"attempts": 2, "blocked_cause": "gave_up"},
        {"attempts": 0, "blocked_cause": None, "state": dst, "last_stage": dst[:4]})
       for src, event in (("question", "question.answer"), ("stuck", "task.retry"))
       for dst in ("plan-todo", "work-todo")},
    **{(s, "task.discard", "", "discarded"): ({}, {"state": "discarded"})
       for s in ("plan-todo", "plan-review", "work-todo", "work-review", "question", "stuck")},
}


@pytest.mark.parametrize("key", list(HUMAN_ROWS), ids=lambda k: f"{k[1]}:{k[0]}:{k[2]}:{k[3]}")
def test_human_row_is_observed(sb: Sandbox, key: tuple[str, str, str, str]) -> None:
    src, event, _guard, dst = key
    before, after = HUMAN_ROWS[key]
    assert key in table(sb)
    sb.add_task("t1", state=dst, depends_on=BLOCKER)  # held in place: only the observed effects
    sb.write_sidecar("t1", {"state": src, **before})
    sb.run_idle()
    assert sb.state_of("t1") == dst
    assert f"{event}: {src} -> {dst}: observed hand move" in sb.log_section("t1")
    side = sb.sidecar("t1")
    for k, v in after.items():
        assert side[k] == v, (k, side)


COMMAND_ONLY = {("work-review", "work.reject_fresh", "", "work-todo")}

LIVE_ROWS = [("plan-running", "stuck", "task.stop"), ("work-running", "stuck", "task.stop"),
             ("plan-running", "discarded", "task.discard"),
             ("work-running", "discarded", "task.discard")]


@pytest.mark.parametrize("src,dst,event", LIVE_ROWS, ids=[f"{e}:{s}" for s, _, e in LIVE_ROWS])
def test_human_row_out_of_running_stops_agent(sb: Sandbox, src: str, dst: str,
                                              event: str) -> None:
    stage_todo = src.replace("running", "todo")
    sb.write_workflow(claude=LONG_AGENT)
    sb.add_task("t1", state=stage_todo)
    sb.steps("t1", {"hang": HANG_S})
    proc = sb.popen("run", "--exit-when-idle")
    try:
        wait_for(lambda: (sb.tasks_dir / src / "t1.md").exists() and bool(sb.calls("t1")),
                 timeout=GENEROUS_S)
        sb.move("t1", src, dst)
        # Only stopping the agent can end the run: the hang outlasts every deadline here.
        assert proc.wait(timeout=GENEROUS_S) == 0
    finally:
        stop(proc)
    assert f"{event}: {src} -> {dst}: observed hand move" in sb.log_section("t1")
    if dst == "discarded":
        assert sb.state_of("t1") == "discarded"
        assert not sb.worktree("t1").exists()
    else:  # stopped: it stays in stuck and is not dispatched again
        assert sb.state_of("t1") == "stuck"
        assert len(sb.calls("t1")) == 1


# ---- coverage and drift ----------------------------------------------------------------------


def test_every_row_has_a_test(sb: Sandbox) -> None:
    rows = table(sb)
    covered = set(HUMAN_ROWS) | {(s, e, "", d) for s, d, e in LIVE_ROWS}
    covered |= COMMAND_ONLY  # no hand move selects these rows; tests/test_commands.py covers them
    covered |= {(*k, rows_dst) for k in SAMBA_ROWS
                for rows_dst in {r[3] for r in rows if r[:3] == k}}
    assert set(rows) == covered


def test_spec_table_matches_the_code(sb: Sandbox) -> None:
    text = STATES_DOC.read_text()
    begin, end = "<!-- transitions:begin -->", "<!-- transitions:end -->"
    assert begin in text and end in text
    block = text.split(begin, 1)[1].split(end, 1)[0].strip()

    def norm(s: str) -> list[str]:
        return [re.sub(r"\s+", " ", ln).strip() for ln in s.strip().splitlines()]
    assert norm(block) == norm(sb.run("dev", "transitions").stdout)


def test_actors_and_known_names(sb: Sandbox) -> None:
    rows = table(sb)
    assert {r["who"] for r in rows.values()} == {"samba", "human"}
    assert all(re.fullmatch(r"[a-z_.]+", e) for _, e, _, _ in rows)


# ---- illegal hand moves ---------------------------------------------------------------------

ILLEGAL = [("work-todo", "done"), ("plan-todo", "work-todo"), ("done", "work-todo"),
           ("work-review", "plan-todo"), ("discarded", "work-todo"), ("question", "done"),
           ("plan-review", "done"), ("work-todo", "plan-todo"), ("stuck", "done")]


@pytest.mark.parametrize("src,dst", ILLEGAL)
def test_illegal_hand_move_is_moved_back(sb: Sandbox, src: str, dst: str) -> None:
    sb.add_task("t1", state=dst, depends_on=BLOCKER)
    sb.write_sidecar("t1", {"state": src, "last_stage": "work"})
    sb.run_idle()
    assert sb.state_of("t1") == src
    assert f"illegal move: {src} -> {dst}, moved back to {src}" in sb.log_section("t1")
    assert sb.sidecar("t1")["state"] == src
    assert "event=illegal_move" in sb.log_text()


def test_question_answer_to_the_other_stage_is_illegal(sb: Sandbox) -> None:
    sb.add_task("t1", state="plan-todo", depends_on=BLOCKER)
    sb.write_sidecar("t1", {"state": "question", "last_stage": "work"})
    sb.run_idle()
    assert sb.state_of("t1") == "question"


def test_illegal_move_of_running_task_keeps_agent_and_defers_log(sb: Sandbox) -> None:
    sb.write_workflow(claude=LONG_AGENT)
    sb.add_task("t1")
    sb.steps("t1", {"hang": HANG_S})
    proc = sb.popen("run", "--exit-when-idle")
    running = sb.tasks_dir / "work-running" / "t1.md"
    try:
        wait_for(lambda: running.exists() and bool(sb.calls("t1")), timeout=GENEROUS_S)
        sb.move("t1", "work-running", "work-review")
        wait_for(lambda: "event=illegal_move" in sb.log_text(), timeout=GENEROUS_S)
        wait_for(running.exists, timeout=GENEROUS_S)
        assert proc.poll() is None
        assert len(sb.calls("t1")) == 1
        assert "illegal move" not in running.read_text()  # not written while the agent runs
    finally:
        stop(proc)
    assert sb.state_of("t1") == "work-todo"
    assert "illegal move: work-running -> work-review, moved back" in sb.log_section("t1")


def test_first_sight_records_the_folder_and_fires_nothing(sb: Sandbox) -> None:
    sb.add_task("t1", state="work-review")
    sb.write_sidecar("t1", {"attempts": 1})  # an old sidecar without `state`
    sb.run_idle()
    assert sb.state_of("t1") == "work-review"
    assert sb.sidecar("t1")["state"] == "work-review"
    assert "## Log" not in sb.task_text("t1")


def test_samba_own_moves_are_not_seen_as_hand_moves(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "blocked"})
    sb.run_idle()
    assert "illegal move" not in sb.task_text("t1")
    assert "observed hand move" not in sb.task_text("t1")
    assert sb.sidecar("t1")["state"] == "question"


def test_rejected_plan_is_not_approved_by_inference(sb: Sandbox) -> None:
    """After a rejection a hand move plan-todo -> work-todo has no row: it is moved back."""
    sb.add_task("t1", state="plan-todo")
    sb.steps("t1", {"plan": "p1"}, {"plan": "p2"})
    sb.run_idle()
    sb.move("t1", "plan-review", "plan-todo")
    sb.run_idle()  # observed plan.reject, replanned
    assert sb.state_of("t1") == "plan-review"
    assert sb.sidecar("t1")["plan_approved"] is False
    sb.write_workflow(planning={"require_plan": True})
    sb.move("t1", "plan-review", "plan-todo")  # observed plan.reject, replanned again
    sb.run_idle()
    assert len(sb.calls("t1")) == 3
    assert sb.state_of("t1") == "plan-review"
    assert sb.sidecar("t1")["plan_approved"] is False
