"""`ClaudeCliRunner`, the `AgentRunner` port over a real `claude` process (spec: running-claude).

The process is `tests/fakes/fake_claude.py`, scripted per task by a plan file. These tests show what
only a real process does: the argv it gets, the stream it prints, kills on stall, timeout and
cancel. What the core does with a report is component-tested over the fake runner.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fake_journal import FakeJournal

from samba.adapters.claude_cli import ClaudeCliRunner
from samba.domain.agent import AgentReport, AgentRequest, RequestKind
from samba.domain.prompts import OUTCOME_SCHEMA_JSON, PLAN_OUTCOME_SCHEMA_JSON
from samba.domain.settings import DEFAULT_PLANNING_ALLOW, AgentSettings

FAKE_CLAUDE = Path(__file__).resolve().parents[1] / "fakes" / "fake_claude.py"


class Rig:
    def __init__(self, tmp: Path, monkeypatch: pytest.MonkeyPatch, **settings: object) -> None:
        self.tmp = tmp
        self.ws = tmp / "home" / "work" / "t1"  # the task id is the worktree's basename
        self.ws.mkdir(parents=True)
        self.tasks_dir = tmp / "tasks"
        self.plan = tmp / "plan" / "plan.json"
        self.plan.parent.mkdir()
        self.plan.write_text("{}")
        monkeypatch.setenv("FAKE_CLAUDE_PLAN", str(self.plan))
        monkeypatch.delenv("FAKE_CLAUDE_LOGGED_OUT", raising=False)
        base = AgentSettings(command=[sys.executable, str(FAKE_CLAUDE)], model="sonnet",
                             permission_mode="acceptEdits", allow=["Edit", "Bash(git add:*)"],
                             args=["--extra-flag"], isolate_user_config=True, turn_timeout_s=60,
                             stall_timeout_s=60, planning_model="opus")
        self.cfg = replace(base, **settings)  # type: ignore[arg-type]
        self.journal = FakeJournal()
        self.runner = ClaudeCliRunner(self.cfg, self.tasks_dir, tmp / "runs", tmp, self.journal)

    def steps(self, *steps: dict[str, object]) -> None:
        self.plan.write_text(json.dumps({"t1": list(steps)}))

    def request(self, kind: RequestKind = "work", resume: bool = False) -> AgentRequest:
        return AgentRequest(prompt="Do the thing", session_id="s-1", resume=resume,
                            system_prompt="SYSTEM", max_budget_usd=1.5, kind=kind,
                            location=str(self.ws), log_name="t1/1")

    def run(self, kind: RequestKind = "work", resume: bool = False) -> AgentReport:
        return asyncio.run(self.runner.run(self.request(kind, resume)))

    def calls(self) -> list[dict[str, object]]:
        path = self.plan.parent / "t1.calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def argv(self) -> list[str]:
        return [str(a) for a in self.calls()[-1]["argv"]]  # type: ignore[union-attr]


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    return Rig(tmp_path, monkeypatch)


def values(argv: list[str], flag: str) -> list[str]:
    """The values after a variadic flag, up to the next flag."""
    out: list[str] = []
    for item in argv[argv.index(flag) + 1:]:
        if item.startswith("--"):
            break
        out.append(item)
    return out


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


# ---- the argv contract ------------------------------------------------------------------------

def test_a_work_turn_gets_the_full_argv_and_runs_in_its_worktree(rig: Rig) -> None:
    report = rig.run()
    assert report.ok and report.outcome == "done"
    argv = rig.argv()
    assert argv[:2] == ["-p", "Do the thing"]  # the prompt first: later flags are variadic
    for flag, value in (("--output-format", "stream-json"), ("--session-id", "s-1"),
                        ("--add-dir", str(rig.tasks_dir)), ("--append-system-prompt", "SYSTEM"),
                        ("--json-schema", OUTCOME_SCHEMA_JSON), ("--permission-mode", "acceptEdits"),
                        ("--model", "sonnet"), ("--max-budget-usd", "1.5000")):
        assert argv[argv.index(flag) + 1] == value, flag
    assert "--verbose" in argv and "--resume" not in argv
    assert values(argv, "--allowedTools") == ["Edit", "Bash(git add:*)"]
    assert argv[-1] == "--extra-flag"  # claude.args last
    assert rig.calls()[-1]["cwd"] == str(rig.ws.resolve())


def test_a_resumed_turn_names_the_session_with_resume(rig: Rig) -> None:
    rig.run(resume=True)
    argv = rig.argv()
    assert argv[argv.index("--resume") + 1] == "s-1" and "--session-id" not in argv


def test_a_planning_turn_is_read_only_with_the_planning_allow_list_and_model(rig: Rig) -> None:
    rig.run(kind="plan")
    argv = rig.argv()
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"  # whatever claude.permission_mode
    assert values(argv, "--allowedTools") == DEFAULT_PLANNING_ALLOW  # never claude.allow
    assert argv[argv.index("--json-schema") + 1] == PLAN_OUTCOME_SCHEMA_JSON
    assert argv[argv.index("--model") + 1] == "opus"


def test_without_a_planning_model_planning_uses_the_claude_model(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = Rig(tmp_path, monkeypatch, planning_model=None)
    rig.run(kind="plan")
    argv = rig.argv()
    assert argv[argv.index("--model") + 1] == "sonnet"


def test_isolation_passes_the_settings_flags_and_excludes_ancestor_memory_files(rig: Rig) -> None:
    rig.run()
    argv = rig.argv()
    assert argv[argv.index("--setting-sources") + 1] == "project,local"
    assert "--strict-mcp-config" in argv
    excludes = json.loads(argv[argv.index("--settings") + 1])["claudeMdExcludes"]
    ws = rig.ws.resolve()
    assert str(ws.parent / "CLAUDE.md") in excludes and "/CLAUDE.md" in excludes
    assert str(ws.parent / ".claude" / "CLAUDE.local.md") in excludes
    assert not any(e.startswith(str(ws) + "/") for e in excludes)  # the worktree's own loads


def test_isolation_can_be_turned_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = Rig(tmp_path, monkeypatch, isolate_user_config=False)
    rig.run()
    argv = rig.argv()
    for flag in ("--setting-sources", "--strict-mcp-config", "--settings"):
        assert flag not in argv


# ---- reading the stream -----------------------------------------------------------------------

def test_an_error_result_is_a_failure_even_with_exit_zero(rig: Rig) -> None:
    rig.steps({"is_error": True, "exit_code": 0})
    report = rig.run()
    assert report.failure is not None and report.failure.kind == "error"
    assert "claude reported an error" in report.failure.detail


def test_malformed_lines_are_skipped_and_the_turn_completes(rig: Rig) -> None:
    rig.steps({"malformed": True, "summary": "fine"})
    report = rig.run()
    assert report.ok and report.outcome == "done" and report.summary == "fine"
    assert ("warning", "malformed_lines", {"task": "t1", "count": 1}) in rig.journal.records


def test_permission_denials_are_reported_by_tool(rig: Rig) -> None:
    rig.steps({"denials": ["Bash", "WebFetch"]})
    assert rig.run().denials == ("Bash", "WebFetch")


def test_a_missing_session_on_resume_is_reported_as_such(rig: Rig) -> None:
    rig.steps({"missing_session": True})
    report = rig.run(resume=True)
    assert report.session_missing and report.failure is not None


def test_the_cost_tokens_and_planning_fields_come_from_the_result(rig: Rig) -> None:
    rig.steps({"cost": 0.42, "plan": "Step 1", "assumptions": "A", "outcome": "planned",
               "questions": [{"text": "Which?", "context": "ctx"}]})
    report = rig.run(kind="plan")
    assert (report.cost_usd, report.input_tokens, report.output_tokens) == (0.42, 100, 50)
    assert (report.outcome, report.plan, report.assumptions) == ("planned", "Step 1", "A")
    assert [(q.text, q.context) for q in report.questions] == [("Which?", "ctx")]


# ---- killing the process ----------------------------------------------------------------------

def test_an_agent_silent_past_the_stall_timeout_is_killed(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = Rig(tmp_path, monkeypatch, stall_timeout_s=0.5)
    rig.steps({"hang": 30})
    start = time.monotonic()
    report = rig.run()
    assert report.failure is not None and report.failure.kind == "stalled"
    assert time.monotonic() - start < 10
    assert not alive(int(rig.calls()[-1]["pid"]))  # type: ignore[arg-type]


def test_an_agent_past_the_turn_timeout_is_killed(tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    rig = Rig(tmp_path, monkeypatch, turn_timeout_s=0.5)
    rig.steps({"hang": 30})
    report = rig.run()
    assert report.failure is not None and report.failure.kind == "timeout"
    assert "timeout" in report.failure.detail
    assert not alive(int(rig.calls()[-1]["pid"]))  # type: ignore[arg-type]


def test_cancelling_a_turn_kills_the_agent(rig: Rig) -> None:
    """What `task stop`, `task discard` and shutdown rely on: the worker is cancelled."""
    rig.steps({"hang": 30})

    async def go() -> None:
        turn = asyncio.create_task(rig.runner.run(rig.request()))
        calls = rig.plan.parent / "t1.calls.jsonl"
        for _ in range(200):
            if calls.exists():
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.2)
        turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await turn

    asyncio.run(go())
    pid = int(rig.calls()[-1]["pid"])  # type: ignore[arg-type]
    for _ in range(50):
        if not alive(pid):
            break
        time.sleep(0.05)
    assert not alive(pid)


# ---- readiness --------------------------------------------------------------------------------

def test_readiness_follows_claude_auth_status(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    assert asyncio.run(rig.runner.ready()).ok
    monkeypatch.setenv("FAKE_CLAUDE_LOGGED_OUT", "1")
    ready = asyncio.run(rig.runner.ready())
    assert not ready.ok and "loggedIn" in ready.detail
