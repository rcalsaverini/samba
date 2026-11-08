"""Black-box test harness.

These tests drive the `symphony` CLI as a subprocess and only inspect files, so they can be reused
against a rewrite in another language: set SYMPHONY_CMD to the new binary (a shell-style string).
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

FAKE_CLAUDE = Path(__file__).parent / "fake_claude.py"
STATES = ("plan-todo", "plan-running", "plan-review", "work-todo", "work-running", "work-review",
          "question", "stuck", "done", "discarded")


def symphony_cmd() -> list[str]:
    env = os.environ.get("SYMPHONY_CMD")
    return shlex.split(env) if env else [sys.executable, "-m", "symphony"]


def git(cwd: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return out.stdout.strip()


@dataclass
class Sandbox:
    root: Path
    repo: Path = field(init=False)
    workspaces_root: Path = field(init=False)
    plan_dir: Path = field(init=False)
    plan: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: {})

    def __post_init__(self) -> None:
        self.repo = self.root / "repo"
        self.workspaces_root = self.root / "ws"
        self.plan_dir = self.root / "plan"
        self.repo.mkdir()
        self.plan_dir.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "README.md").write_text("# test repo\n")
        (self.repo / "CLAUDE.md").write_text("Test repo.\n")
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
        self.write_workflow()

    # ---- setup helpers -------------------------------------------------------------------

    def write_workflow(self, body: str = "Work on {{ task.title }}.\n\n{{ task.body }}",
                       **overrides: Any) -> None:
        config: dict[str, Any] = {
            "workspaces_root": str(self.workspaces_root),
            "poll_interval_s": 0.05,
            "retry_base_s": 0.05,
            "max_retry_backoff_s": 0.2,
            "claude": {
                "command": f"{shlex.quote(sys.executable)} {shlex.quote(str(FAKE_CLAUDE))}",
                "turn_timeout_s": 30,
                "stall_timeout_s": 10,
            },
        }
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key].update(value)
            else:
                config[key] = value
        text = "---\n" + yaml.safe_dump(config, sort_keys=False) + "---\n" + body + "\n"
        (self.repo / "WORKFLOW.md").write_text(text)

    def add_task(self, task_id: str, body: str = "Do the thing.", state: str = "work-todo",
                 priority: int | None = None, title: str | None = None,
                 depends_on: list[str] | None = None) -> Path:
        d = self.tasks_dir / state
        d.mkdir(parents=True, exist_ok=True)
        front: dict[str, Any] = {}
        if priority is not None:
            front["priority"] = priority
        if depends_on is not None:
            front["depends_on"] = depends_on
        fm = f"---\n{yaml.safe_dump(front)}---\n" if front else ""
        p = d / f"{task_id}.md"
        p.write_text(f"{fm}# {title or task_id}\n\n{body}\n")
        return p

    def steps(self, task_id: str, *steps: dict[str, Any]) -> None:
        self.plan[task_id] = list(steps)

    def write_sidecar(self, task_id: str, data: dict[str, Any]) -> None:
        d = self.repo / ".symphony" / "state"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{task_id}.json").write_text(json.dumps(data))

    # ---- running -------------------------------------------------------------------------

    def env(self, **extra: str) -> dict[str, str]:
        (self.plan_dir / "plan.json").write_text(json.dumps(self.plan))
        env = dict(os.environ)
        env["FAKE_CLAUDE_PLAN"] = str(self.plan_dir / "plan.json")
        env.update(extra)
        return env

    def run(self, *args: str, timeout: float = 60, **env: str) -> subprocess.CompletedProcess[str]:
        cmd = [*symphony_cmd(), *args, "--repo", str(self.repo)]
        return subprocess.run(cmd, cwd=self.repo, env=self.env(**env), capture_output=True,
                              text=True, timeout=timeout)

    def run_idle(self, timeout: float = 60, **env: str) -> subprocess.CompletedProcess[str]:
        res = self.run("run", "--exit-when-idle", timeout=timeout, **env)
        assert res.returncode == 0, f"symphony failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
        return res

    def popen(self, *args: str) -> subprocess.Popen[str]:
        cmd = [*symphony_cmd(), *args, "--repo", str(self.repo)]
        return subprocess.Popen(cmd, cwd=self.repo, env=self.env(), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)

    # ---- inspection ----------------------------------------------------------------------

    @property
    def tasks_dir(self) -> Path:
        return self.repo / ".symphony" / "tasks"

    def state_of(self, task_id: str) -> str | None:
        found = [s for s in STATES if (self.tasks_dir / s / f"{task_id}.md").exists()]
        assert len(found) <= 1, f"task {task_id} in several states: {found}"
        return found[0] if found else None

    def task_text(self, task_id: str) -> str:
        state = self.state_of(task_id)
        assert state is not None
        return (self.tasks_dir / state / f"{task_id}.md").read_text()

    def log_section(self, task_id: str) -> str:
        text = self.task_text(task_id)
        assert "## Log" in text, text
        return text.split("## Log", 1)[1]

    def sidecar(self, task_id: str) -> dict[str, Any]:
        return json.loads((self.repo / ".symphony" / "state" / f"{task_id}.json").read_text())

    def move(self, task_id: str, src: str, dst: str) -> None:
        """Move a task file by hand, like dragging it in the file browser."""
        (self.tasks_dir / dst).mkdir(parents=True, exist_ok=True)
        (self.tasks_dir / src / f"{task_id}.md").rename(self.tasks_dir / dst / f"{task_id}.md")

    def log_text(self) -> str:
        p = self.repo / ".symphony" / "symphony.log"
        return p.read_text() if p.exists() else ""

    def calls(self, task_id: str) -> list[list[str]]:
        p = self.plan_dir / f"{task_id}.calls.jsonl"
        if not p.exists():
            return []
        return [json.loads(line)["argv"] for line in p.read_text().splitlines()]

    def pids(self, task_id: str) -> list[int]:
        p = self.plan_dir / f"{task_id}.calls.jsonl"
        if not p.exists():
            return []
        return [json.loads(line)["pid"] for line in p.read_text().splitlines()]

    @property
    def repo_key(self) -> str:
        resolved = self.repo.resolve()
        digest = hashlib.sha256(str(resolved).encode()).hexdigest()[:8]
        return f"{resolved.name}-{digest}"

    def worktree(self, task_id: str) -> Path:
        return self.workspaces_root / self.repo_key / task_id

    def branch_exists(self, name: str) -> bool:
        res = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"],
                             cwd=self.repo, capture_output=True)
        return res.returncode == 0


@pytest.fixture
def sb(tmp_path: Path) -> Iterator[Sandbox]:
    yield Sandbox(tmp_path)


def wait_for(cond: Callable[[], bool], timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while not cond() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert cond()


def stop(proc: subprocess.Popen[str]) -> None:
    proc.send_signal(signal.SIGINT)
    proc.wait(timeout=15)


def flag(argv: list[str], name: str) -> str | None:
    if name in argv:
        i = argv.index(name)
        return argv[i + 1] if i + 1 < len(argv) else ""
    return None


def prompt_of(argv: list[str]) -> str:
    p = flag(argv, "-p")
    assert p is not None, argv
    return p
