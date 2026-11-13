"""Signals to the running program and prompts on a real terminal (spec: orchestrator, cli)."""

from __future__ import annotations

import os
import pty
import select
import signal
import subprocess

import pytest
from e2e_box import Box, alive, samba_cmd, wait_for


def test_sigint_stops_samba_run_and_returns_the_running_task_to_its_todo(box: Box) -> None:
    """Signal handling belongs to the process: Ctrl-C ends the loop cleanly."""
    tid = box.new_task("Long", "--skip-plan")
    box.steps(tid, {"hang": 30})
    proc = box.popen_run()
    assert wait_for(lambda: bool(box.calls(tid)) and box.state_of(tid) == "work-running")
    _, err = box.stop(proc, signal.SIGINT)
    assert proc.returncode == 0 and "samba: stopped" in err
    assert box.state_of(tid) == "work-todo"
    assert not alive(int(box.calls(tid)[-1]["pid"]))


def test_task_stop_kills_the_live_agent_and_leaves_the_task_stuck(box: Box) -> None:
    """A command in one process stops an agent run by another."""
    tid = box.new_task("Long", "--skip-plan")
    box.steps(tid, {"hang": 30})
    proc = box.popen_run()
    try:
        assert wait_for(lambda: bool(box.calls(tid)) and box.state_of(tid) == "work-running")
        res = box.run("task", "stop", tid)
        assert res.returncode == 0, res.stderr
        pid = int(box.calls(tid)[-1]["pid"])
        assert wait_for(lambda: not alive(pid))
        assert box.state_of(tid) == "stuck"
        assert len(box.calls(tid)) == 1  # not dispatched again
    finally:
        box.stop(proc, signal.SIGINT)
    assert box.state_of(tid) == "stuck"


def discard_on_a_pty(box: Box, tid: str, typed: bytes) -> tuple[int, str]:
    master, slave = pty.openpty()
    proc = subprocess.Popen([*samba_cmd(), "task", "discard", tid, "--repo", str(box.repo)],
                            cwd=box.repo, env=box.env(), stdin=slave, stdout=slave, stderr=slave,
                            close_fds=True)
    os.close(slave)
    out, sent = b"", False
    try:
        while True:
            ready, _, _ = select.select([master], [], [], 20)
            if not ready:
                break
            try:
                chunk = os.read(master, 1024)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
            if not sent and b"[y/N]" in out:
                os.write(master, typed)
                sent = True
    finally:
        os.close(master)
        proc.wait(20)
    return proc.returncode, out.decode(errors="replace")


@pytest.mark.parametrize("typed, discarded", [(b"n\n", False), (b"\n", False), (b"y\n", True)])
def test_on_a_terminal_discard_asks_and_only_yes_discards(box: Box, typed: bytes,
                                                         discarded: bool) -> None:
    """Only a real terminal makes the program ask."""
    tid = box.new_task("Maybe", "--skip-plan")
    code, screen = discard_on_a_pty(box, tid, typed)
    assert f"Discard task {tid}" in screen and "[y/N]" in screen
    assert (code == 0) is discarded
    assert box.state_of(tid) == ("discarded" if discarded else "work-todo")


def test_without_a_terminal_discard_needs_yes(box: Box) -> None:
    """With no terminal the program cannot ask, so it refuses as a usage error."""
    tid = box.new_task("Maybe", "--skip-plan")
    res = box.run("task", "discard", tid, stdin="y\n")
    assert res.returncode == 2 and "--yes" in res.stderr
    assert box.state_of(tid) == "work-todo"
    assert box.run("task", "discard", tid, "--yes").returncode == 0
    assert box.state_of(tid) == "discarded"
