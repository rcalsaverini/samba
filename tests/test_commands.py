"""Black-box tests for `plan accept|reject` and `work reject` (spec: cli). Must not import samba."""

from __future__ import annotations

import fcntl
import re
import sys
import time
from pathlib import Path

import pytest
from conftest import Sandbox, stop, wait_for

PLAN_RUN = {"plan": "the plan"}


def review_task(sb: Sandbox, task_id: str, state: str, **side: object) -> Path:
    path = sb.add_task(task_id, state=state)
    sb.write_sidecar(task_id, {"state": state, **side})
    return path


def feedback_section(sb: Sandbox, task_id: str) -> str:
    text = sb.task_text(task_id)
    assert "## Feedback" in text, text
    return text.split("## Feedback", 1)[1].split("\n## ", 1)[0]


def fake_editor(tmp_path: Path, text: str, code: int = 0) -> str:
    script = tmp_path / "editor.py"
    script.write_text("import sys\n"
                      f"open(sys.argv[1], 'w').write({text!r})\n"
                      f"sys.exit({code})\n")
    return f"{sys.executable} {script}"


# ---- success paths --------------------------------------------------------------------------


def test_plan_accept(sb: Sandbox) -> None:
    review_task(sb, "t1", "plan-review", session_id="s", plan_session_id="p")
    res = sb.run("plan", "accept", "t1")
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == str(sb.tasks_dir / "work-todo" / "t1.md")
    assert sb.state_of("t1") == "work-todo"
    side = sb.sidecar("t1")
    assert side["plan_approved"] is True and side["session_id"] is None
    assert side["plan_session_id"] == "p" and side["state"] == "work-todo"
    log = sb.log_section("t1")
    assert "plan.accept: plan-review -> work-todo" in log
    assert "observed" not in log


def test_plan_reject_with_feedback(sb: Sandbox) -> None:
    review_task(sb, "t1", "plan-review")
    res = sb.run("plan", "reject", "t1", "--feedback", "Use SQLite instead.")
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == str(sb.tasks_dir / "plan-todo" / "t1.md")
    assert sb.state_of("t1") == "plan-todo"
    assert sb.sidecar("t1")["state"] == "plan-todo"
    fb = feedback_section(sb, "t1")
    assert "### Round 1" in fb and "Use SQLite instead." in fb
    log = sb.log_section("t1")
    assert "plan.reject: plan-review -> plan-todo: feedback round 1" in log
    assert sb.task_text("t1").index("## Feedback") < sb.task_text("t1").index("## Log")


def test_work_reject_keeps_session(sb: Sandbox) -> None:
    review_task(sb, "t1", "work-review", session_id="s1")
    res = sb.run("work", "reject", "t1", "--feedback", "Add tests.")
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == str(sb.tasks_dir / "work-todo" / "t1.md")
    assert sb.state_of("t1") == "work-todo"
    assert sb.sidecar("t1")["session_id"] == "s1"
    assert "work.reject: work-review -> work-todo: feedback round 1" in sb.log_section("t1")
    assert "Add tests." in feedback_section(sb, "t1")


def test_work_reject_fresh_clears_session(sb: Sandbox) -> None:
    review_task(sb, "t1", "work-review", session_id="s1", plan_session_id="p")
    res = sb.run("work", "reject", "t1", "--fresh", "--feedback", "Redo it.")
    assert res.returncode == 0, res.stderr
    assert sb.state_of("t1") == "work-todo"
    side = sb.sidecar("t1")
    assert side["session_id"] is None and side["plan_session_id"] == "p"
    assert "work.reject_fresh: work-review -> work-todo" in sb.log_section("t1")


# ---- feedback rounds ------------------------------------------------------------------------


def test_repeated_rejects_append_rounds(sb: Sandbox) -> None:
    review_task(sb, "t1", "work-review")
    assert sb.run("work", "reject", "t1", "--feedback", "first").returncode == 0
    sb.move("t1", "work-todo", "work-review")  # back to review; no orchestrator is watching
    sb.write_sidecar("t1", {"state": "work-review"})
    assert sb.run("work", "reject", "t1", "--feedback", "second\n\n## Heading\nmore").returncode == 0
    fb = feedback_section(sb, "t1")
    assert fb.index("### Round 1") < fb.index("first") < fb.index("### Round 2")
    assert fb.index("### Round 2") < fb.index("second")
    assert "\n## Heading" not in fb and "### Heading" in fb
    assert fb.count("### Round") == 2
    assert "feedback round 2" in sb.log_section("t1")


def test_feedback_after_existing_prose_in_section(sb: Sandbox) -> None:
    sb.add_task("t1", state="plan-review",
                body="Goal.\n\n## Feedback\nHuman prose here.\n\n## Plan\nsteps\n\n## Log\n- x")
    sb.write_sidecar("t1", {"state": "plan-review"})
    assert sb.run("plan", "reject", "t1", "--feedback", "new").returncode == 0
    text = sb.task_text("t1")
    assert "Human prose here." in text
    assert re.search(r"Human prose here\.\n\n### Round 1\n\nnew\n\n## Plan\nsteps", text), text


def test_feedback_section_created_before_log(sb: Sandbox) -> None:
    sb.add_task("t1", state="plan-review", body="Goal.\n\n## Log\n- x")
    sb.write_sidecar("t1", {"state": "plan-review"})
    assert sb.run("plan", "reject", "t1", "--feedback", "new").returncode == 0
    text = sb.task_text("t1")
    assert text.index("## Feedback") < text.index("## Log")
    assert text.count("## Feedback") == 1 and "### Round 1" in text


def test_reject_without_feedback_warns(sb: Sandbox) -> None:
    review_task(sb, "t1", "plan-review")
    res = sb.run("plan", "reject", "t1")
    assert res.returncode == 0
    assert "warning: rejecting without feedback" in res.stderr
    assert sb.state_of("t1") == "plan-todo"
    assert "### Round" not in sb.task_text("t1")
    assert "plan.reject: plan-review -> plan-todo" in sb.log_section("t1")


def test_edit_uses_editor(sb: Sandbox, tmp_path: Path) -> None:
    review_task(sb, "t1", "work-review")
    res = sb.run("work", "reject", "t1", "--edit", EDITOR=fake_editor(tmp_path, "From editor.\n"))
    assert res.returncode == 0, res.stderr
    assert "### Round 1" in feedback_section(sb, "t1")
    assert "From editor." in feedback_section(sb, "t1")


def test_failing_editor_changes_nothing(sb: Sandbox, tmp_path: Path) -> None:
    review_task(sb, "t1", "plan-review")
    before = sb.task_text("t1")
    res = sb.run("plan", "reject", "t1", "--edit", EDITOR=fake_editor(tmp_path, "x", code=1))
    assert res.returncode == 1
    assert sb.state_of("t1") == "plan-review" and sb.task_text("t1") == before


def test_feedback_and_edit_together_is_a_usage_error(sb: Sandbox) -> None:
    review_task(sb, "t1", "plan-review")
    res = sb.run("plan", "reject", "t1", "--feedback", "a", "--edit")
    assert res.returncode == 2
    assert sb.state_of("t1") == "plan-review"


# ---- wrong state ----------------------------------------------------------------------------

WRONG = [
    (["plan", "accept"], "plan-running", "plan.accept"),
    (["plan", "reject", "--feedback", "x"], "work-todo", "plan.reject"),
    (["plan", "accept"], "done", "plan.accept"),
    (["work", "reject", "--feedback", "x"], "plan-review", "work.reject"),
    (["work", "reject", "--fresh"], "work-running", "work.reject"),
    (["work", "reject"], "done", "work.reject"),
]


@pytest.mark.parametrize("cmd,state,event", WRONG, ids=[f"{' '.join(c[:2])}:{s}" for c, s, _ in WRONG])
def test_wrong_state_is_refused(sb: Sandbox, cmd: list[str], state: str, event: str) -> None:
    review_task(sb, "t1", state)
    before_text, before_side = sb.task_text("t1"), sb.sidecar("t1")
    res = sb.run(*cmd[:2], "t1", *cmd[2:])
    assert res.returncode == 1, res.stderr
    assert res.stdout == ""
    assert f"t1 is in {state}; {event} not allowed. Legal events:" in res.stderr
    assert sb.state_of("t1") == state
    assert sb.task_text("t1") == before_text and sb.sidecar("t1") == before_side


def test_wrong_state_lists_legal_events(sb: Sandbox) -> None:
    review_task(sb, "t1", "work-review")
    res = sb.run("plan", "accept", "t1")
    assert res.returncode == 1
    legal = res.stderr.split("Legal events:", 1)[1]
    assert "work.accept" in legal and "work.reject" in legal and "plan.accept" not in legal
    review_task(sb, "t2", "plan-running")
    assert "Legal events: task.stop" in sb.run("plan", "accept", "t2").stderr
    review_task(sb, "t3", "done")
    assert "Legal events: none" in sb.run("plan", "accept", "t3").stderr


# ---- id resolver ----------------------------------------------------------------------------


def test_id_prefix_resolution(sb: Sandbox) -> None:
    review_task(sb, "alpha-one", "plan-review")
    review_task(sb, "alpha-two", "plan-review")
    review_task(sb, "beta", "plan-review")
    review_task(sb, "beta-long", "plan-review")
    amb = sb.run("plan", "accept", "alpha")
    assert amb.returncode == 2 and "alpha-one" in amb.stderr and "alpha-two" in amb.stderr
    assert sb.state_of("alpha-one") == "plan-review"
    assert sb.run("plan", "accept", "nope").returncode == 2
    assert sb.run("plan", "accept", "alpha-t").returncode == 0
    assert sb.state_of("alpha-two") == "work-todo"
    assert sb.run("plan", "accept", "beta").returncode == 0  # exact id beats "beta-long"
    assert sb.state_of("beta") == "work-todo" and sb.state_of("beta-long") == "plan-review"


# ---- hand-move compatibility ----------------------------------------------------------------


def test_hand_move_work_reject_is_still_observed_and_keeps_session(sb: Sandbox) -> None:
    review_task(sb, "t1", "work-review", session_id="s1")
    sb.move("t1", "work-review", "work-todo")
    sb.run_idle()
    assert "work.reject: work-review -> work-todo: observed hand move" in sb.log_section("t1")
    assert "work.reject_fresh" not in sb.log_section("t1")
    assert sb.calls("t1")[0].count("--resume") == 1


# ---- concurrency with a running orchestrator ------------------------------------------------


def started(sb: Sandbox) -> bool:
    return "event=started" in sb.log_text()


def settle(sb: Sandbox, task_id: str, marker: str) -> None:
    wait_for(lambda: sb.state_of(task_id) is not None and marker in sb.task_text(task_id),
             timeout=30)


def assert_clean(sb: Sandbox, event: str) -> None:
    log = sb.log_section("t1")
    assert log.count(f"{event}:") == 1, log
    assert "observed hand move" not in log and "illegal move" not in log, log
    assert "illegal_move" not in sb.log_text()


CONCURRENT = [
    (["plan", "accept"], "plan-review", "plan.accept", "done: work-running -> work-review"),
    (["plan", "reject", "--feedback", "redo"], "plan-review", "plan.reject",
     "planned: plan-running -> plan-review"),
    (["work", "reject", "--feedback", "redo"], "work-review", "work.reject",
     "done: work-running -> work-review"),
    (["work", "reject", "--fresh", "--feedback", "redo"], "work-review", "work.reject_fresh",
     "done: work-running -> work-review"),
]


@pytest.mark.parametrize("cmd,state,event,marker", CONCURRENT, ids=[c[2] for c in CONCURRENT])
def test_command_while_orchestrator_runs(sb: Sandbox, cmd: list[str], state: str, event: str,
                                         marker: str) -> None:
    review_task(sb, "t1", state, session_id="s1")
    if state == "plan-review":
        sb.steps("t1", PLAN_RUN)
    proc = sb.popen("run")
    try:
        wait_for(lambda: started(sb))
        time.sleep(0.3)
        # The delay between rename and sidecar save lasts many ticks (poll interval 0.05 s).
        res = sb.run(*cmd[:2], "t1", *cmd[2:], SAMBA_DEBUG_FIRE_DELAY="1.0")
        assert res.returncode == 0, res.stderr
        settle(sb, "t1", marker)
    finally:
        stop(proc)
    assert_clean(sb, event)
    assert sb.sidecar("t1")["attempts"] == 0


def test_command_waits_for_lock_and_orchestrator_keeps_ticking(sb: Sandbox) -> None:
    review_task(sb, "t1", "plan-review")
    lock_path = sb.repo / ".samba" / "lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        proc = sb.popen("plan", "accept", "t1")
        time.sleep(0.8)
        assert proc.poll() is None  # blocked on the lock
        assert sb.state_of("t1") == "plan-review"
        fcntl.flock(fh, fcntl.LOCK_UN)
    _, err = proc.communicate(timeout=30)
    assert proc.returncode == 0, err
    assert sb.state_of("t1") == "work-todo"
    assert "plan.accept: plan-review -> work-todo" in sb.log_section("t1")


def test_orchestrator_skips_ticks_while_lock_is_held(sb: Sandbox) -> None:
    review_task(sb, "t1", "work-todo")
    lock_path = sb.repo / ".samba" / "lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        proc = sb.popen("run")
        try:
            wait_for(lambda: started(sb))
            time.sleep(0.5)
            assert sb.state_of("t1") == "work-todo"  # no dispatch while the lock is held
            fcntl.flock(fh, fcntl.LOCK_UN)
            settle(sb, "t1", "done: work-running -> work-review")
        finally:
            stop(proc)
