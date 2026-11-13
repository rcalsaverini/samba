"""The end-to-end sandbox: a temporary git repository driven only through the `samba` command.

It never imports `samba`. `SAMBA_CMD` (a shell-style string) replaces the command under test, so the
same suite runs against a rewrite (ADR 0009 mechanics, kept by ADR 0016). The agent is the scripted
`tests/fakes/fake_claude.py`, configured per task through a plan file.
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

FAKE_CLAUDE = Path(__file__).resolve().parents[1] / "fakes" / "fake_claude.py"
STATES = ("plan-todo", "plan-running", "plan-review", "work-todo", "work-running", "work-review",
          "question", "stuck", "done", "discarded")


def samba_cmd() -> list[str]:
    env = os.environ.get("SAMBA_CMD")
    return shlex.split(env) if env else [sys.executable, "-m", "samba"]


def git(cwd: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return out.stdout.strip()


def wait_for(cond: Callable[[], bool], timeout: float = 20) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


class Box:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo = root / "repo"
        self.plan_dir = root / "plan"
        self.repo.mkdir()
        self.plan_dir.mkdir()
        self.plan: dict[str, list[dict[str, Any]]] = {}
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "README.md").write_text("# test repo\n")
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
        self.workflow()

    # ---- setup --------------------------------------------------------------------------

    def workflow(self, **overrides: Any) -> None:
        config: dict[str, Any] = {
            "workspaces_root": str(self.root / "ws"),
            "poll_interval_s": 0.05, "retry_base_s": 0.05, "max_retry_backoff_s": 0.1,
            "claude": {"command": f"{shlex.quote(sys.executable)} {shlex.quote(str(FAKE_CLAUDE))}",
                       "turn_timeout_s": 30, "stall_timeout_s": 10},
        }
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key].update(value)
            else:
                config[key] = value
        text = "---\n" + yaml.safe_dump(config, sort_keys=False) + "---\nWork on {{ task.title }}.\n"
        (self.repo / "WORKFLOW.md").write_text(text)

    def steps(self, task_id: str, *steps: dict[str, Any]) -> None:
        self.plan[task_id] = list(steps)

    # ---- running ------------------------------------------------------------------------

    def env(self, **extra: str) -> dict[str, str]:
        (self.plan_dir / "plan.json").write_text(json.dumps(self.plan))
        env = dict(os.environ)
        env["FAKE_CLAUDE_PLAN"] = str(self.plan_dir / "plan.json")
        env.update(extra)
        return env

    def run(self, *args: str, cwd: Path | None = None, repo: bool = True, timeout: float = 60,
            stdin: str | None = None, **env: str) -> subprocess.CompletedProcess[str]:
        cmd = [*samba_cmd(), *args, *(["--repo", str(self.repo)] if repo else [])]
        return subprocess.run(cmd, cwd=cwd or self.repo, env=self.env(**env), capture_output=True,
                              text=True, timeout=timeout, input=stdin)

    def run_idle(self) -> subprocess.CompletedProcess[str]:
        res = self.run("run", "--exit-when-idle")
        assert res.returncode == 0, f"samba run failed:\n{res.stdout}\n{res.stderr}"
        return res

    def popen_run(self) -> subprocess.Popen[str]:
        cmd = [*samba_cmd(), "run", "--repo", str(self.repo)]
        return subprocess.Popen(cmd, cwd=self.repo, env=self.env(), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)

    def new_task(self, title: str, *flags: str) -> str:
        res = self.run("task", "new", title, "--body", "Do it.", *flags)
        assert res.returncode == 0, res.stderr
        return Path(res.stdout.strip()).stem

    # ---- looking --------------------------------------------------------------------------

    def state_of(self, task_id: str) -> str | None:
        found = [s for s in STATES if (self.repo / ".samba" / "tasks" / s / f"{task_id}.md").exists()]
        assert len(found) <= 1, found
        return found[0] if found else None

    def task_text(self, task_id: str) -> str:
        state = self.state_of(task_id)
        assert state is not None
        return (self.repo / ".samba" / "tasks" / state / f"{task_id}.md").read_text()

    def calls(self, task_id: str) -> list[dict[str, Any]]:
        path = self.plan_dir / f"{task_id}.calls.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def stop(self, proc: subprocess.Popen[str], sig: int = signal.SIGINT) -> tuple[str, str]:
        proc.send_signal(sig)
        return proc.communicate(timeout=30)


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
