#!/usr/bin/env python3
"""Fake `claude` CLI for black-box tests.

Behavior is driven by a JSON plan file named in the env var FAKE_CLAUDE_PLAN:

    {"<task-id>": [step, step, ...], ...}

The task id is the basename of the working directory (the worktree). Each invocation consumes the
next step for that task (a default "done" step once the list is exhausted). Every invocation's argv
is appended to <plan dir>/<task-id>.calls.jsonl.

Step fields (all optional):
    outcome         "done" | "blocked" | "continue" | null (null = no structured output)
    summary         string
    cost            float, default 0.01
    write           {relative path: content} written in the cwd
    commit          bool, `git add -A && git commit` after writing
    task_log        string appended at the end of the task file
    exit_code       int, default 0
    is_error        bool, result event with is_error true
    no_result       bool, exit without a result event
    hang            float seconds to sleep before the result (stall/timeout tests)
    malformed       bool, emit a non-JSON line first
    denials         list of tool names to report in permission_denials
    missing_session bool, when called with --resume, fail like an unknown session id
    plan            string, put in structured_output.plan (planning runs)
    questions       list of {"text": ..., "context": ...}, put in structured_output.questions
                    (work and planning runs; anything else is emitted as given)
    assumptions     string, put in structured_output.assumptions (planning runs)
    (for planning runs "outcome" is "planned" or "blocked"; the default there is "planned")

`claude auth status` prints {"loggedIn": true} unless FAKE_CLAUDE_LOGGED_OUT is set.

Standard library only, so it can be reused unchanged against a non-Python Samba.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any


def emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def arg_value(argv: list[str], flag: str) -> str | None:
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def main() -> int:
    argv = sys.argv[1:]
    if argv[:2] == ["auth", "status"]:
        print(json.dumps({"loggedIn": not os.environ.get("FAKE_CLAUDE_LOGGED_OUT")}))
        return 0

    plan_path = Path(os.environ["FAKE_CLAUDE_PLAN"])
    plan: dict[str, list[dict[str, Any]]] = json.loads(plan_path.read_text())
    cwd = Path.cwd()
    task_id = cwd.name
    plan_dir = plan_path.parent

    with (plan_dir / f"{task_id}.calls.jsonl").open("a") as f:
        f.write(json.dumps({"argv": argv, "cwd": str(cwd), "pid": os.getpid()}) + "\n")

    counter = plan_dir / f"{task_id}.count"
    n = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(n + 1))
    steps = plan.get(task_id, [])
    step: dict[str, Any] = steps[n] if n < len(steps) else {}  # default outcome: done/planned

    resume = arg_value(argv, "--resume")
    session_id = resume or arg_value(argv, "--session-id") or str(uuid.uuid4())

    if resume and step.get("missing_session"):
        emit({"type": "result", "subtype": "error_during_execution", "is_error": True,
              "result": None, "session_id": str(uuid.uuid4()), "total_cost_usd": 0,
              "usage": {"input_tokens": 0, "output_tokens": 0}, "num_turns": 0,
              "permission_denials": []})
        sys.stderr.write(f"No conversation found with session ID: {resume}\n")
        return 1

    emit({"type": "system", "subtype": "hook_started"})
    emit({"type": "system", "subtype": "init", "session_id": session_id, "cwd": str(cwd),
          "permissionMode": arg_value(argv, "--permission-mode") or "default",
          "skills": ["fake-skill"], "plugins": [], "mcp_servers": [], "tools": ["Bash", "Edit"]})
    if step.get("malformed"):
        sys.stdout.write("this is not json\n")
        sys.stdout.flush()

    writes: dict[str, str] = step.get("write") or {}
    for rel, content in writes.items():
        p = cwd / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    if step.get("commit"):
        subprocess.run(["git", "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-c", "user.email=fake@x", "-c", "user.name=fake", "commit", "-qm",
                        f"fake commit {n + 1}"], check=True, capture_output=True)
    if step.get("task_log"):
        add_dir = arg_value(argv, "--add-dir")
        if add_dir:
            found = sorted(Path(add_dir).glob(f"*-running/{task_id}.md"))
            tf = found[0] if found else Path(add_dir) / "work-running" / f"{task_id}.md"
            if tf.exists():
                with tf.open("a") as f:
                    f.write(step["task_log"] + "\n")

    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": "working"}]}})

    if step.get("hang"):
        time.sleep(float(step["hang"]))

    if step.get("no_result"):
        return int(step.get("exit_code", 1))

    planning = "planned" in (arg_value(argv, "--json-schema") or "")
    outcome = step.get("outcome", "planned" if planning else "done")
    structured: dict[str, Any] | None = None
    if outcome is not None:
        structured = {"outcome": outcome, "summary": step.get("summary", f"step {n + 1}")}
        if planning:
            structured["plan"] = step.get("plan", f"plan {n + 1}")
            if "assumptions" in step:
                structured["assumptions"] = step["assumptions"]
        if "questions" in step:
            structured["questions"] = step["questions"]
    is_error = bool(step.get("is_error", False))
    emit({"type": "result", "subtype": "success", "is_error": is_error,
          "result": json.dumps(structured) if structured else "no structured output",
          "structured_output": structured, "session_id": session_id,
          "total_cost_usd": float(step.get("cost", 0.01)),
          "usage": {"input_tokens": 100, "output_tokens": 50}, "num_turns": 1,
          "terminal_reason": "completed",
          "permission_denials": [{"tool_name": t, "tool_use_id": "x", "tool_input": {}}
                                 for t in step.get("denials", [])]})
    return int(step.get("exit_code", 1 if is_error else 0))


if __name__ == "__main__":
    sys.exit(main())
