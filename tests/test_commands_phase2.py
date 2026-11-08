"""Black-box tests for `question answer`, `task retry|stop|discard` (SPEC §11).

Must not import samba.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import Sandbox, stop, samba_cmd, wait_for


def seed(sb: Sandbox, task_id: str, state: str, **side: object) -> Path:
    path = sb.add_task(task_id, state=state)
    if state == "question" and "questions" not in side:
        side["questions"] = [question("q1")]
    sb.write_sidecar(task_id, {"state": state, **side})
    return path


def question(qid: str, status: str = "open", rnd: int = 1) -> dict[str, object]:
    return {"id": qid, "round": rnd, "stage": "work", "status": status, "text": f"text {qid}",
            "context": "why", "asked_at": "2026-11-07T10:00:00-03:00", "answer": None,
            "answered_at": None}


def fake_editor(tmp_path: Path, text: str) -> str:
    script = tmp_path / "editor.py"
    script.write_text(f"import sys\nopen(sys.argv[1], 'w').write({text!r})\n")
    return f"{sys.executable} {script}"


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def snapshot(sb: Sandbox, task_id: str) -> tuple[str | None, str, str]:
    state = sb.state_of(task_id)
    side = sb.repo / ".samba" / "state" / f"{task_id}.json"
    return state, sb.task_text(task_id), side.read_text() if side.exists() else ""


# ---- question answer ------------------------------------------------------------------------


@pytest.mark.parametrize("stage,dst", [("plan", "plan-todo"), ("work", "work-todo"),
                                       (None, "plan-todo")])
def test_question_answer(sb: Sandbox, stage: str | None, dst: str) -> None:
    seed(sb, "t1", "question", last_stage=stage, blocked_cause="question", attempts=2)
    res = sb.run("question", "answer", "t1", "Use SQLite.")
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == str(sb.tasks_dir / dst / "t1.md")
    assert sb.state_of("t1") == dst
    side = sb.sidecar("t1")
    assert side["state"] == dst and side["attempts"] == 0 and side["blocked_cause"] is None
    text = sb.task_text("t1")
    assert "## Feedback" not in text
    assert "Answer: Use SQLite." in text
    log = sb.log_section("t1")
    assert "question.answer: t1/q1 answered" in log
    assert f"question.answer: question -> {dst}" in log


def test_question_answer_heading_in_answer_is_demoted(sb: Sandbox) -> None:
    seed(sb, "t1", "question", last_stage="work")
    assert sb.run("question", "answer", "t1", "# Big heading\nsecond").returncode == 0
    assert "\n# Big heading" not in sb.task_text("t1")


def test_question_answer_edit(sb: Sandbox, tmp_path: Path) -> None:
    seed(sb, "t1", "question", last_stage="work")
    res = sb.run("question", "answer", "t1", "--edit", EDITOR=fake_editor(tmp_path, "From editor.\n"))
    assert res.returncode == 0, res.stderr
    assert sb.sidecar("t1")["questions"][0]["answer"] == "From editor."
    assert sb.state_of("t1") == "work-todo"


def test_question_answer_edit_quotes_question_and_strips_comments(sb: Sandbox,
                                                                  tmp_path: Path) -> None:
    seed(sb, "t1", "question", last_stage="work")
    script = tmp_path / "ed.py"
    script.write_text("import sys\np = sys.argv[1]\nt = open(p).read()\n"
                      "assert '# q1: text q1' in t and '# Context: why' in t, t\n"
                      "open(p, 'w').write(t + 'My answer\\n')\n")
    res = sb.run("question", "answer", "t1", "--edit", EDITOR=f"{sys.executable} {script}")
    assert res.returncode == 0, res.stderr
    assert sb.sidecar("t1")["questions"][0]["answer"] == "My answer"


@pytest.mark.parametrize("args", [[], ["--edit", "text"], [""], ["   "]],
                         ids=["none", "both", "empty", "blank"])
def test_question_answer_usage_errors(sb: Sandbox, args: list[str]) -> None:
    seed(sb, "t1", "question", last_stage="work")
    before = snapshot(sb, "t1")
    res = sb.run("question", "answer", "t1", *args)
    assert res.returncode == 2, res.stderr
    assert snapshot(sb, "t1") == before


# ---- task retry -----------------------------------------------------------------------------


@pytest.mark.parametrize("stage,dst", [("plan", "plan-todo"), ("work", "work-todo")])
def test_retry(sb: Sandbox, stage: str, dst: str) -> None:
    seed(sb, "t1", "stuck", last_stage=stage, blocked_cause="gave_up", attempts=3)
    res = sb.run("task", "retry", "t1")
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == str(sb.tasks_dir / dst / "t1.md")
    assert res.stderr.strip() == ""
    side = sb.sidecar("t1")
    assert side["attempts"] == 0 and side["blocked_cause"] is None and side["state"] == dst
    assert f"task.retry: stuck -> {dst}" in sb.log_section("t1")


@pytest.mark.parametrize("cause,word", [("budget", "WORKFLOW.md"),
                                        ("dependency_discarded", "depends_on"),
                                        ("dependency_cycle", "depends_on")])
def test_retry_hints(sb: Sandbox, cause: str, word: str) -> None:
    seed(sb, "t1", "stuck", last_stage="work", blocked_cause=cause)
    workflow = (sb.repo / "WORKFLOW.md").read_bytes()
    res = sb.run("task", "retry", "t1")
    assert res.returncode == 0, res.stderr
    assert "hint:" in res.stderr and word in res.stderr
    assert res.stdout.strip() == str(sb.tasks_dir / "work-todo" / "t1.md")
    assert (sb.repo / "WORKFLOW.md").read_bytes() == workflow
    assert sb.state_of("t1") == "work-todo"


# ---- task stop ------------------------------------------------------------------------------


@pytest.mark.parametrize("stage", ["work", "plan"])
def test_stop_live_agent(sb: Sandbox, stage: str) -> None:
    running = f"{stage}-running"
    sb.add_task("t1", state=f"{stage}-todo")
    sb.steps("t1", {"hang": 30}, {"hang": 30})  # the second is used after `task retry`
    proc = sb.popen("run")
    try:
        wait_for(lambda: sb.pids("t1") != [] and sb.state_of("t1") == running)
        pid = sb.pids("t1")[0]
        res = sb.run("task", "stop", "t1")
        assert res.returncode == 0, res.stderr
        assert res.stdout.strip() == str(sb.tasks_dir / "stuck" / "t1.md")
        wait_for(lambda: not alive(pid))
        time.sleep(2.5)  # several poll intervals: it must not be dispatched again
        assert len(sb.pids("t1")) == 1 and sb.state_of("t1") == "stuck"
        side = sb.sidecar("t1")  # the cancelled worker did not write a stale sidecar
        assert side["state"] == "stuck" and side["attempts"] == 0, side
        assert side["blocked_cause"] == "stopped" and side["last_stage"] == stage, side
        res = sb.run("task", "retry", "t1")
        assert res.returncode == 0, res.stderr
        assert res.stderr.strip() == ""
        wait_for(lambda: len(sb.pids("t1")) == 2)  # dispatched again
        assert sb.state_of("t1") == running
    finally:
        stop(proc)
    log = sb.log_section("t1")
    assert log.count(f"task.stop: {running} -> stuck") == 1, log
    assert "observed hand move" not in log and "illegal move" not in log, log


@pytest.mark.parametrize("stage,after", [("work", "work-review"), ("plan", "plan-review")])
def test_stop_without_orchestrator(sb: Sandbox, stage: str, after: str) -> None:
    seed(sb, "t1", f"{stage}-running", last_stage=stage, attempts=1)
    res = sb.run("task", "stop", "t1")
    assert res.returncode == 0, res.stderr
    assert sb.state_of("t1") == "stuck"
    side = sb.sidecar("t1")
    assert side["state"] == "stuck" and side["blocked_cause"] == "stopped"
    assert side["last_stage"] == stage
    sb.run_idle()
    assert sb.state_of("t1") == "stuck" and sb.calls("t1") == []
    assert sb.run("task", "retry", "t1").returncode == 0
    assert sb.state_of("t1") == f"{stage}-todo"
    sb.run_idle()
    assert sb.state_of("t1") == after
    assert "observed" not in sb.log_section("t1")


def test_retry_stopped_has_no_hint(sb: Sandbox) -> None:
    seed(sb, "t1", "stuck", last_stage="work", blocked_cause="stopped")
    res = sb.run("task", "retry", "t1")
    assert res.returncode == 0 and res.stderr.strip() == ""
    assert sb.sidecar("t1")["blocked_cause"] is None
    assert sb.state_of("t1") == "work-todo"


# ---- task discard ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", ["work-review", "stuck", "plan-review", "work-todo"])
def test_discard_yes(sb: Sandbox, state: str) -> None:
    seed(sb, "t1", state)
    res = sb.run("task", "discard", "t1", "--yes")
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == str(sb.tasks_dir / "discarded" / "t1.md")
    assert f"task.discard: {state} -> discarded" in sb.log_section("t1")
    assert sb.sidecar("t1")["state"] == "discarded"


def test_discard_without_tty_needs_yes(sb: Sandbox) -> None:
    seed(sb, "t1", "work-review")
    before = snapshot(sb, "t1")
    res = sb.run("task", "discard", "t1")
    assert res.returncode == 2 and "--yes" in res.stderr
    assert snapshot(sb, "t1") == before


def test_discard_tty_prompt(sb: Sandbox) -> None:
    pty = pytest.importorskip("pty")
    seed(sb, "t1", "work-review")
    for answer, discarded in ((b"n\n", False), (b"\n", False), (b"y\n", True)):
        master, slave = pty.openpty()
        proc = subprocess.Popen([*samba_cmd(), "task", "discard", "t1", "--repo", str(sb.repo)],
                                cwd=sb.repo, env=sb.env(), stdin=slave, stdout=slave,
                                stderr=subprocess.PIPE)
        os.close(slave)
        out = ""
        while "[y/N]" not in out:  # wait for the prompt, then answer
            chunk = os.read(master, 4096).decode()
            assert chunk, "no prompt"
            out += chunk
        os.write(master, answer)
        proc.wait(timeout=60)
        os.close(master)
        assert (proc.returncode == 0) == discarded, proc.stderr.read() if proc.stderr else ""
        assert (sb.state_of("t1") == "discarded") == discarded
        if not discarded:
            assert proc.returncode == 1


def test_discard_prompt_names_resolved_id(sb: Sandbox) -> None:
    pty = pytest.importorskip("pty")
    seed(sb, "task-one", "work-review")
    master, slave = pty.openpty()
    proc = subprocess.Popen([*samba_cmd(), "task", "discard", "task-o", "--repo", str(sb.repo)],
                            cwd=sb.repo, env=sb.env(), stdin=slave, stdout=slave,
                            stderr=subprocess.PIPE)
    os.close(slave)
    out = ""
    while "[y/N]" not in out:
        chunk = os.read(master, 4096).decode()
        assert chunk, "no prompt"
        out += chunk
    os.write(master, b"n\n")
    proc.wait(timeout=60)
    os.close(master)
    assert "Discard task task-one?" in out, out


def test_discard_running_kills_agent_and_keeps_branch(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.steps("t1", {"hang": 30})
    proc = sb.popen("run")
    try:
        wait_for(lambda: sb.pids("t1") != [] and sb.state_of("t1") == "work-running")
        pid = sb.pids("t1")[0]
        res = sb.run("task", "discard", "t1", "--yes")
        assert res.returncode == 0, res.stderr
        wait_for(lambda: not alive(pid))
        wait_for(lambda: not sb.worktree("t1").exists())
    finally:
        stop(proc)
    assert sb.state_of("t1") == "discarded"
    assert sb.branch_exists("samba/t1")


# ---- shared: wrong state --------------------------------------------------------------------

WRONG = [
    (["question", "answer", "t1", "text"], "work-todo", "question.answer"),
    (["task", "retry", "t1"], "work-review", "task.retry"),
    (["task", "stop", "t1"], "work-todo", "task.stop"),
    (["task", "stop", "t1"], "stuck", "task.stop"),
    (["task", "discard", "t1", "--yes"], "done", "task.discard"),
    (["task", "discard", "t1", "--yes"], "discarded", "task.discard"),
]


@pytest.mark.parametrize("cmd,state,event", WRONG, ids=[f"{w[2]}-{w[1]}" for w in WRONG])
def test_wrong_state(sb: Sandbox, cmd: list[str], state: str, event: str) -> None:
    seed(sb, "t1", state)
    before = snapshot(sb, "t1")
    res = sb.run(*cmd[:2], *cmd[2:])
    assert res.returncode == 1 and res.stdout == ""
    assert f"t1 is in {state}; {event} not allowed. Legal events:" in res.stderr
    assert snapshot(sb, "t1") == before


def test_discard_wrong_state_lists_none(sb: Sandbox) -> None:
    seed(sb, "t1", "done")
    res = sb.run("task", "discard", "t1")  # no --yes: refused before any prompt
    assert res.returncode == 1 and "Legal events: none" in res.stderr


# ---- concurrency ----------------------------------------------------------------------------


@pytest.mark.parametrize("cmd,state,event", [
    (["question", "answer", "t1", "go"], "question", "question.answer"),
    (["task", "retry", "t1"], "stuck", "task.retry"),
], ids=["answer", "retry"])
def test_command_while_orchestrator_runs(sb: Sandbox, cmd: list[str], state: str,
                                         event: str) -> None:
    seed(sb, "other", "work-todo")
    sb.steps("other", {"hang": 30})
    seed(sb, "t1", state, last_stage="work", blocked_cause="gave_up", attempts=2)
    proc = sb.popen("run")
    try:
        wait_for(lambda: sb.pids("other") != [])
        res = sb.run(*cmd, SAMBA_DEBUG_FIRE_DELAY="1.0")
        assert res.returncode == 0, res.stderr
        wait_for(lambda: "done: work-running -> work-review" in sb.log_section("t1"), 30)
    finally:
        stop(proc)
    log = sb.log_section("t1")
    assert log.count(f"{event}: {state} ->") == 1, log
    assert "observed hand move" not in log and "illegal move" not in log, log
