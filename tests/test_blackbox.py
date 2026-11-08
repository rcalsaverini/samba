"""Black-box behavior tests (see conftest.py). They must not import the symphony package."""

from __future__ import annotations

import json
import time

from conftest import Sandbox, flag, git, prompt_of

# ---- happy paths ---------------------------------------------------------------------------


def test_done_with_passing_validation_goes_to_review(sb: Sandbox) -> None:
    sb.write_workflow(validate={"command": "test -f result.txt"})
    sb.add_task("t1", title="Make result")
    sb.steps("t1", {"outcome": "done", "summary": "made it", "write": {"result.txt": "ok"},
                    "commit": True, "cost": 0.25})
    sb.run_idle()

    assert sb.state_of("t1") == "work-review"
    log = sb.log_section("t1")
    assert "work-review" in log and "made it" in log
    assert sb.branch_exists("symphony/t1")
    assert "fake commit" in git(sb.repo, "log", "--oneline", "symphony/t1")
    assert sb.worktree("t1").is_dir()
    side = sb.sidecar("t1")
    assert side["attempts"] == 0
    assert side["last_outcome"] == "done"
    assert abs(side["cost_usd_total"] - 0.25) < 1e-9
    assert side["turns_total"] == 1


def test_no_validate_command_done_goes_straight_to_review(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "done"})
    sb.run_idle()
    assert sb.state_of("t1") == "work-review"


def test_continue_then_done_resumes_same_session(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "continue"}, {"outcome": None}, {"outcome": "done"})
    sb.run_idle()

    assert sb.state_of("t1") == "work-review"
    calls = sb.calls("t1")
    assert len(calls) == 3
    sid = flag(calls[0], "--session-id")
    assert sid
    assert flag(calls[1], "--resume") == sid
    assert flag(calls[2], "--resume") == sid
    assert flag(calls[1], "--session-id") is None
    assert "Work on t1." in prompt_of(calls[0])
    assert "Continue working" in prompt_of(calls[1])


def test_validation_failure_is_fed_back_then_passes(sb: Sandbox) -> None:
    sb.write_workflow(validate={"command": "test -f fixed.txt || (echo 'MISSING fixed.txt'; exit 1)"})
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "done"}, {"outcome": "done", "write": {"fixed.txt": "x"}})
    sb.run_idle()

    assert sb.state_of("t1") == "work-review"
    calls = sb.calls("t1")
    assert len(calls) == 2
    p = prompt_of(calls[1])
    assert "failed" in p and "MISSING fixed.txt" in p
    assert (sb.repo / ".symphony" / "runs" / "t1").is_dir()


def test_blocked_moves_to_question(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "blocked", "summary": "which db?",
                    "task_log": "## Questions\nWhich database?"})
    sb.run_idle()

    assert sb.state_of("t1") == "question"
    text = sb.task_text("t1")
    assert "Which database?" in text
    assert "which db?" in sb.log_section("t1")
    assert sb.sidecar("t1")["last_outcome"] == "blocked"


def test_rework_from_review_resumes_session_with_resume_prompt(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "done"}, {"outcome": "done"})
    sb.run_idle()
    assert sb.state_of("t1") == "work-review"
    sid = sb.sidecar("t1")["session_id"]

    src = sb.tasks_dir / "work-review" / "t1.md"
    src.write_text(src.read_text() + "\n## Feedback\nPlease rename it.\n")
    src.rename(sb.tasks_dir / "work-todo" / "t1.md")
    sb.run_idle()

    assert sb.state_of("t1") == "work-review"
    calls = sb.calls("t1")
    assert flag(calls[1], "--resume") == sid
    assert "resuming" in prompt_of(calls[1])


# ---- failures and retries ------------------------------------------------------------------


def test_failure_is_retried_then_succeeds(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.steps("t1", {"exit_code": 2, "no_result": True}, {"outcome": "done"})
    sb.run_idle()

    assert sb.state_of("t1") == "work-review"
    assert len(sb.calls("t1")) == 2
    assert sb.sidecar("t1")["attempts"] == 0
    assert "retry" in sb.log_section("t1").lower()


def test_is_error_result_counts_as_failure(sb: Sandbox) -> None:
    sb.write_workflow(max_attempts=1, reflect_on_give_up=False)
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "done", "is_error": True, "exit_code": 0})
    sb.run_idle()
    assert sb.state_of("t1") == "stuck"
    assert sb.sidecar("t1")["last_outcome"] == "failed"


def test_gives_up_after_max_attempts_with_reflection_turn(sb: Sandbox) -> None:
    sb.write_workflow(max_attempts=2, reflect_on_give_up=True)
    sb.add_task("t1")
    sb.steps("t1", {"is_error": True}, {"is_error": True}, {"outcome": "continue"})
    sb.run_idle()

    assert sb.state_of("t1") == "stuck"
    calls = sb.calls("t1")
    assert len(calls) == 3
    assert "Harness gaps" in prompt_of(calls[2])
    side = sb.sidecar("t1")
    assert side["attempts"] == 2
    assert side["last_outcome"] == "failed"
    assert side["last_error"]


def test_max_turns_exhausted_is_a_failure(sb: Sandbox) -> None:
    sb.write_workflow(max_turns=2, max_attempts=1, reflect_on_give_up=False)
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "continue"}, {"outcome": "continue"})
    sb.run_idle()
    assert sb.state_of("t1") == "stuck"
    assert "max_turns" in sb.sidecar("t1")["last_error"]


def test_stall_kills_agent_and_retries(sb: Sandbox) -> None:
    sb.write_workflow(claude={"stall_timeout_s": 0.5})
    sb.add_task("t1")
    sb.steps("t1", {"hang": 20}, {"outcome": "done"})
    started = time.monotonic()
    sb.run_idle(timeout=30)
    assert time.monotonic() - started < 15
    assert sb.state_of("t1") == "work-review"
    assert len(sb.calls("t1")) == 2


def test_turn_timeout_kills_agent(sb: Sandbox) -> None:
    sb.write_workflow(max_attempts=1, reflect_on_give_up=False,
                      claude={"turn_timeout_s": 0.5, "stall_timeout_s": 10})
    sb.add_task("t1")
    sb.steps("t1", {"hang": 20})
    started = time.monotonic()
    sb.run_idle(timeout=30)
    assert time.monotonic() - started < 15
    assert sb.state_of("t1") == "stuck"
    assert "timeout" in sb.sidecar("t1")["last_error"].lower()


def test_malformed_lines_are_skipped(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "done", "malformed": True})
    sb.run_idle()
    assert sb.state_of("t1") == "work-review"


def test_missing_session_on_resume_starts_fresh(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.write_sidecar("t1", {"session_id": "00000000-0000-0000-0000-000000000000"})
    sb.steps("t1", {"missing_session": True}, {"outcome": "done"})
    sb.run_idle()

    assert sb.state_of("t1") == "work-review"
    calls = sb.calls("t1")
    assert flag(calls[0], "--resume") == "00000000-0000-0000-0000-000000000000"
    new_sid = flag(calls[1], "--session-id")
    assert new_sid and new_sid != "00000000-0000-0000-0000-000000000000"
    assert "Work on t1." in prompt_of(calls[1])
    assert sb.sidecar("t1")["attempts"] == 0


def test_budget_cap_blocks_task(sb: Sandbox) -> None:
    sb.write_workflow(max_cost_usd_per_task=0.15)
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "continue", "cost": 0.1}, {"outcome": "continue", "cost": 0.1},
             {"outcome": "done"})
    sb.run_idle()

    assert sb.state_of("t1") == "stuck"
    assert sb.sidecar("t1")["blocked_cause"] == "budget"
    calls = sb.calls("t1")
    assert len(calls) == 2
    assert flag(calls[0], "--max-budget-usd") is not None
    assert float(flag(calls[1], "--max-budget-usd") or 0) < 0.06
    assert "budget" in sb.log_section("t1").lower()


def test_permission_denials_are_logged(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "done", "denials": ["Bash"]})
    sb.run_idle()
    assert "denied" in sb.log_section("t1").lower()
    assert "Bash" in sb.log_section("t1")


def test_after_create_hook_failure_fails_attempt(sb: Sandbox) -> None:
    sb.write_workflow(max_attempts=1, reflect_on_give_up=False,
                      hooks={"after_create": "echo boom; exit 3"})
    sb.add_task("t1")
    sb.run_idle()
    assert sb.state_of("t1") == "stuck"
    assert sb.calls("t1") == []
    assert not sb.worktree("t1").exists()


def test_after_create_hook_runs_once_in_worktree(sb: Sandbox) -> None:
    sb.write_workflow(hooks={"after_create": "echo hook >> hook-ran.txt"})
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "continue"}, {"outcome": "done"})
    sb.run_idle()
    assert (sb.worktree("t1") / "hook-ran.txt").read_text() == "hook\n"


# ---- claude invocation contract --------------------------------------------------------------


def test_claude_argv_contract(sb: Sandbox) -> None:
    sb.write_workflow(validate={"command": "true"},
                      claude={"allow": ["Edit", "Bash(git commit:*)"], "model": "haiku"})
    sb.add_task("t1")
    sb.run_idle()
    argv = sb.calls("t1")[0]

    assert argv[0] == "-p"
    assert flag(argv, "--output-format") == "stream-json"
    assert "--verbose" in argv
    assert flag(argv, "--permission-mode") == "dontAsk"
    assert flag(argv, "--model") == "haiku"
    i = argv.index("--allowedTools")
    assert argv[i + 1:i + 3] == ["Edit", "Bash(git commit:*)"]
    assert flag(argv, "--setting-sources") == "project,local"
    assert "--strict-mcp-config" in argv
    assert flag(argv, "--add-dir") == str((sb.tasks_dir).resolve())
    schema = json.loads(flag(argv, "--json-schema") or "{}")
    assert schema["properties"]["outcome"]["enum"] == ["done", "blocked", "continue"]
    system = flag(argv, "--append-system-prompt") or ""
    assert "authorized to commit" in system
    assert "symphony/t1" in system
    assert "running/t1.md" in system
    assert "system runs `true`" in system
    assert "`Bash(git commit:*)`" in system  # agent is told what it may run
    assert "no pipes" in system
    assert flag(argv, "--max-budget-usd") is None


def test_isolation_can_be_disabled(sb: Sandbox) -> None:
    sb.write_workflow(claude={"isolate_user_config": False})
    sb.add_task("t1")
    sb.run_idle()
    argv = sb.calls("t1")[0]
    assert "--setting-sources" not in argv
    assert "--strict-mcp-config" not in argv


def test_agent_runs_in_worktree_outside_repo(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.run_idle()
    calls_file = (sb.plan_dir / "t1.calls.jsonl").read_text().splitlines()
    cwd = json.loads(calls_file[0])["cwd"]
    assert cwd == str(sb.worktree("t1").resolve())
    assert not str(sb.worktree("t1").resolve()).startswith(str(sb.repo.resolve()))


def test_template_unknown_variable_fails_attempt(sb: Sandbox) -> None:
    sb.write_workflow(body="Hello {{ task.nope }}", max_attempts=1, reflect_on_give_up=False)
    sb.add_task("t1")
    sb.run_idle()
    assert sb.state_of("t1") == "stuck"
    assert "task.nope" in sb.sidecar("t1")["last_error"]
    assert sb.calls("t1") == []


# ---- scheduling ----------------------------------------------------------------------------


def test_priority_order_with_single_slot(sb: Sandbox) -> None:
    sb.write_workflow(max_concurrent=1)
    sb.add_task("low", priority=3)
    sb.add_task("none")
    sb.add_task("high", priority=1)
    sb.run_idle()
    order: list[tuple[float, str]] = []
    for tid in ("low", "none", "high"):
        side = sb.sidecar(tid)
        order.append((side["first_dispatched_at"], tid))
    assert [t for _, t in sorted(order)] == ["high", "low", "none"]


def test_concurrency_limit_respected(sb: Sandbox) -> None:
    sb.write_workflow(max_concurrent=2)
    for i in range(4):
        sb.add_task(f"t{i}")
        sb.steps(f"t{i}", {"outcome": "done", "hang": 0.6})
    proc = sb.popen("run", "--exit-when-idle")
    max_running = 0
    deadline = time.monotonic() + 30
    while proc.poll() is None and time.monotonic() < deadline:
        run_dir = sb.tasks_dir / "work-running"
        running = list(run_dir.glob("*.md")) if run_dir.exists() else []
        max_running = max(max_running, len(running))
        time.sleep(0.05)
    assert proc.wait(timeout=5) == 0
    assert max_running == 2
    assert all(sb.state_of(f"t{i}") == "work-review" for i in range(4))


def test_running_tasks_recovered_on_startup(sb: Sandbox) -> None:
    sb.add_task("t1", state="work-running")
    sb.write_sidecar("t1", {"session_id": "11111111-1111-1111-1111-111111111111", "attempts": 1})
    sb.steps("t1", {"outcome": "done"})
    sb.run_idle()
    assert sb.state_of("t1") == "work-review"
    assert flag(sb.calls("t1")[0], "--resume") == "11111111-1111-1111-1111-111111111111"


def test_human_discarding_running_task_kills_agent_and_removes_worktree(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "done", "hang": 30})
    proc = sb.popen("run", "--exit-when-idle")
    running = sb.tasks_dir / "work-running" / "t1.md"
    deadline = time.monotonic() + 15
    while not (running.exists() and sb.calls("t1")) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert running.exists()
    running.rename(sb.tasks_dir / "discarded" / "t1.md")
    assert proc.wait(timeout=15) == 0
    assert sb.state_of("t1") == "discarded"
    assert not sb.worktree("t1").exists()
    assert sb.branch_exists("symphony/t1")


def test_stuck_task_moved_back_to_todo_resets_attempts(sb: Sandbox) -> None:
    sb.write_workflow(max_attempts=1, reflect_on_give_up=False)
    sb.add_task("t1")
    sb.steps("t1", {"is_error": True}, {"outcome": "done"})
    sb.run_idle()
    assert sb.state_of("t1") == "stuck"
    (sb.tasks_dir / "stuck" / "t1.md").rename(sb.tasks_dir / "work-todo" / "t1.md")
    sb.run_idle()
    assert sb.state_of("t1") == "work-review"


def test_invalid_task_names_are_skipped(sb: Sandbox) -> None:
    (sb.tasks_dir / "work-todo").mkdir(parents=True)
    (sb.tasks_dir / "work-todo" / "bad name!.md").write_text("# bad\n")
    sb.add_task("ok")
    sb.run_idle()
    assert sb.state_of("ok") == "work-review"
    assert (sb.tasks_dir / "work-todo" / "bad name!.md").exists()


# ---- startup and CLI -----------------------------------------------------------------------


def test_refuses_to_start_when_logged_out(sb: Sandbox) -> None:
    res = sb.run("run", "--exit-when-idle", FAKE_CLAUDE_LOGGED_OUT="1")
    assert res.returncode != 0
    assert "auth" in (res.stderr + res.stdout).lower()


def test_refuses_workspaces_inside_repo(sb: Sandbox) -> None:
    sb.write_workflow(workspaces_root=str(sb.repo / "inside"))
    res = sb.run("run", "--exit-when-idle")
    assert res.returncode != 0
    assert "workspaces_root" in res.stderr


def test_refuses_invalid_config(sb: Sandbox) -> None:
    sb.write_workflow(max_concurrent=0)
    res = sb.run("run", "--exit-when-idle")
    assert res.returncode != 0
    assert "max_concurrent" in res.stderr


def test_symphony_dir_is_git_excluded(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.run_idle()
    assert ".symphony/" in (sb.repo / ".git" / "info" / "exclude").read_text()
    assert git(sb.repo, "status", "--porcelain") == "?? WORKFLOW.md"


def test_new_command_creates_todo_task(sb: Sandbox) -> None:
    res = sb.run("new", "Add CSV export!", "--priority", "2")
    assert res.returncode == 0, res.stderr
    text = (sb.tasks_dir / "work-todo" / "add-csv-export.md").read_text()
    assert "# Add CSV export!" in text
    assert "priority: 2" in text
    res = sb.run("new", "Add CSV export!")
    assert (sb.tasks_dir / "work-todo" / "add-csv-export-2.md").exists()


def test_status_command_lists_tasks(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "blocked", "cost": 0.5})
    sb.run_idle()
    res = sb.run("status")
    assert res.returncode == 0, res.stderr
    assert "t1" in res.stdout and "blocked" in res.stdout and "0.50" in res.stdout
