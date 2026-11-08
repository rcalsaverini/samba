"""Black-box behavior tests (see conftest.py). They must not import the samba package."""

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
    assert sb.branch_exists("samba/t1")
    assert "fake commit" in git(sb.repo, "log", "--oneline", "samba/t1")
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
    assert (sb.repo / ".samba" / "runs" / "t1").is_dir()


def test_blocked_moves_to_question(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "blocked", "summary": "which db?",
                    "questions": [{"text": "Which database?", "context": "storage"}]})
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
    assert "samba/t1" in system
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
    assert "--settings" not in argv


def test_isolation_excludes_ancestor_claude_md(sb: Sandbox) -> None:
    # Claude Code loads CLAUDE.md from every ancestor of its cwd, which --setting-sources does not
    # cover: a worktree under $HOME would load the user's ~/.claude/CLAUDE.md (spec: running-claude, User config isolation).
    sb.add_task("t1")
    sb.run_idle()
    argv = sb.calls("t1")[0]
    settings = json.loads(flag(argv, "--settings") or "{}")
    excludes = settings["claudeMdExcludes"]
    wt = sb.worktree("t1").resolve()
    for parent in (wt.parent, wt.parents[2], sb.root.resolve()):
        assert str(parent / "CLAUDE.md") in excludes
        assert str(parent / ".claude" / "CLAUDE.md") in excludes
        assert str(parent / "CLAUDE.local.md") in excludes
    assert "/.claude/CLAUDE.md" in excludes  # filesystem root, so every ancestor is covered
    for own in ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md"):
        assert str(wt / own) not in excludes  # the repo's own memory files still load


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
    assert sb.branch_exists("samba/t1")


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


def test_samba_dir_is_git_excluded(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.run_idle()
    assert ".samba/" in (sb.repo / ".git" / "info" / "exclude").read_text()
    assert git(sb.repo, "status", "--porcelain") == "?? WORKFLOW.md"


def test_task_new_creates_plan_todo_task(sb: Sandbox) -> None:
    res = sb.run("task", "new", "Add CSV export!", "--priority", "2")
    assert res.returncode == 0, res.stderr
    text = (sb.tasks_dir / "plan-todo" / "add-csv-export.md").read_text()
    assert "# Add CSV export!" in text
    assert "priority: 2" in text
    assert "Describe the goal" not in text
    res = sb.run("task", "new", "Add CSV export!")
    assert (sb.tasks_dir / "plan-todo" / "add-csv-export-2.md").exists()


def test_task_list_shows_cause_and_cost(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "blocked", "cost": 0.5})
    sb.run_idle()
    res = sb.run("task", "list")
    assert res.returncode == 0, res.stderr
    assert "t1" in res.stdout and "blocked" in res.stdout and "0.50" in res.stdout


# ---- task list / task show (spec: cli) --------------------------------------------------------


def _ids(stdout: str) -> list[str]:
    return [line.split()[0] for line in stdout.splitlines()[1:]]


def _populate(sb: Sandbox) -> None:
    sb.add_task("a-plan", state="plan-review")
    sb.add_task("b-todo", state="work-todo")
    sb.add_task("c-run", state="work-running")
    sb.add_task("d-review", state="work-review")
    sb.add_task("e-q", state="question")
    sb.write_sidecar("e-q", {"blocked_cause": "question", "last_stage": "work"})
    sb.add_task("f-stuck", state="stuck")
    sb.write_sidecar("f-stuck", {"blocked_cause": "budget", "last_stage": "plan"})
    sb.add_task("g-done", state="done")
    sb.add_task("h-dis", state="discarded")


def test_list_without_filter_shows_all_states(sb: Sandbox) -> None:
    _populate(sb)
    listed = sb.run("task", "list")
    assert listed.returncode == 0
    assert len(_ids(listed.stdout)) == 8


def test_list_filters_by_full_name_and_prefix(sb: Sandbox) -> None:
    _populate(sb)
    assert _ids(sb.run("task", "list", "plan-review").stdout) == ["a-plan"]
    assert _ids(sb.run("task", "list", "work").stdout) == ["b-todo", "c-run", "d-review"]
    assert _ids(sb.run("task", "list", "q").stdout) == ["e-q"]
    assert "question (question)" in sb.run("task", "list", "q").stdout
    assert _ids(sb.run("task", "list", "d").stdout) == ["g-done", "h-dis"]


def test_list_several_states_in_canonical_order(sb: Sandbox) -> None:
    _populate(sb)
    res = sb.run("task", "list", "stuck", "plan-review")
    assert res.returncode == 0
    assert _ids(res.stdout) == ["a-plan", "f-stuck"]
    assert "stuck (budget)" in res.stdout


def test_list_unknown_state_exits_2(sb: Sandbox) -> None:
    _populate(sb)
    res = sb.run("task", "list", "zzz")
    assert res.returncode == 2
    assert "zzz" in res.stderr and "work-todo" in res.stderr


def test_list_shows_waiting_on(sb: Sandbox) -> None:
    sb.add_task("dep", state="work-review")
    sb.add_task("child", depends_on=["dep"])
    res = sb.run("task", "list", "work-todo")
    assert _ids(res.stdout) == ["child"]
    assert "waiting on dep" in res.stdout


def test_list_empty_prints_header_only(sb: Sandbox) -> None:
    res = sb.run("task", "list", "stuck")
    assert res.returncode == 0
    assert len(res.stdout.splitlines()) == 1


def _table_events(sb: Sandbox, state: str, last_stage: str | None) -> list[tuple[str, str]]:
    """Human events for `state` read from the `samba dev transitions` output (the table)."""
    want = last_stage or "unset"
    seen: list[tuple[str, str]] = []
    for line in sb.run("dev", "transitions").stdout.splitlines():
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or cells[3] != "human" or cells[1] != state:
            continue
        stage_guards = [g for g in cells[4].split(",") if g.startswith("last_stage=")]
        if stage_guards and stage_guards != [f"last_stage={want}"]:
            continue
        if cells[0] not in [e for e, _ in seen]:
            seen.append((cells[0], cells[2]))
    return seen


def _shown_events(out: str) -> list[tuple[str, str]]:
    lines = out.splitlines()
    if "events: (none)" in lines:
        return []
    start = lines.index("events:") + 1
    events: list[tuple[str, str]] = []
    for line in lines[start:]:
        if not line.startswith("  ") or "->" not in line:
            break
        ev, dst = line.strip().split(" -> ")
        events.append((ev, dst))
    return events


def test_task_list_error_column_uses_terminal_width(sb: Sandbox) -> None:
    sb.add_task("p1", state="plan-review")
    err = "something went wrong " * 6
    err = err.strip()
    sb.write_sidecar("p1", {"last_outcome": "planned", "last_error": err})
    wide = sb.run("task", "list", COLUMNS="200").stdout.splitlines()
    assert wide[1].endswith(err) and "..." not in wide[1]
    narrow = sb.run("task", "list", COLUMNS="80").stdout.splitlines()
    assert narrow[1].endswith("...") and len(narrow[1]) <= 80


def test_show_plan_review(sb: Sandbox) -> None:
    sb.add_task("p1", state="plan-review", title="Plan me", priority=3)
    sb.write_sidecar("p1", {"attempts": 2, "turns_total": 7, "cost_usd_total": 1.5,
                            "last_outcome": "planned", "last_error": "x" * 100,
                            "branch": "samba/p1", "workspace": "/tmp/ws/p1",
                            "session_id": "sess-1", "plan_session_id": "psess-1"})
    res = sb.run("task", "show", "p1")
    assert res.returncode == 0, res.stderr
    out = res.stdout
    assert "title: Plan me" in out
    assert "state: plan-review" in out
    assert "blocked_cause: -" in out
    assert "attempts: 2" in out and "turns: 7" in out and "cost: $1.50" in out
    assert "last_outcome: planned" in out
    assert "last_error: " + "x" * 100 in out
    assert "branch: samba/p1" in out and "worktree: /tmp/ws/p1" in out
    assert "session_id: sess-1" in out and "plan_session_id: psess-1" in out
    assert _shown_events(out) == _table_events(sb, "plan-review", None)
    assert [e for e, _ in _shown_events(out)] == ["plan.accept", "plan.reject", "task.discard"]


def test_show_events_come_from_the_table(sb: Sandbox) -> None:
    cases: list[tuple[str, str | None]] = [
        ("plan-todo", None), ("plan-running", None), ("work-todo", None),
        ("work-running", None), ("work-review", None), ("done", None),
        ("discarded", None), ("question", "plan"), ("question", "work"),
        ("question", None), ("stuck", "plan"), ("stuck", "work"), ("stuck", None),
    ]
    for i, (state, stage) in enumerate(cases):
        tid = f"t{i}"
        sb.add_task(tid, state=state)
        if stage:
            sb.write_sidecar(tid, {"last_stage": stage})
        out = sb.run("task", "show", tid).stdout
        assert _shown_events(out) == _table_events(sb, state, stage), (state, stage, out)
    assert "events: (none)" in sb.run("task", "show", "t5").stdout
    stuck = _shown_events(sb.run("task", "show", "t12").stdout)
    assert [e for e, _ in stuck].count("task.retry") == 1


def test_show_question_cause(sb: Sandbox) -> None:
    sb.add_task("q1", state="question")
    sb.write_sidecar("q1", {"blocked_cause": "question", "last_stage": "work"})
    out = sb.run("task", "show", "q1").stdout
    assert "state: question" in out and "blocked_cause: question" in out
    assert "question.answer -> work-todo" in out


def test_show_depends_on_with_states(sb: Sandbox) -> None:
    sb.add_task("d1", state="work-review")
    sb.add_task("d2", state="done")
    sb.add_task("child", depends_on=["d1", "d2", "ghost"])
    res = sb.run("task", "show", "child")
    assert res.returncode == 0, res.stderr
    assert "  d1 (work-review)" in res.stdout
    assert "  d2 (done)" in res.stdout
    assert "  ghost (unknown)" in res.stdout
    assert "waiting" in res.stdout


def test_show_done_task(sb: Sandbox) -> None:
    sb.add_task("fin", state="done")
    res = sb.run("task", "show", "fin")
    assert res.returncode == 0 and "state: done" in res.stdout


def test_resolver_exact_prefix_ambiguous_unknown(sb: Sandbox) -> None:
    sb.add_task("alpha", state="work-todo")
    sb.add_task("alpha-two", state="stuck")
    sb.add_task("beta-one", state="done")
    sb.add_task("beta-two", state="discarded")
    exact = sb.run("task", "show", "alpha")
    assert exact.returncode == 0 and "id: alpha\n" in exact.stdout
    pre = sb.run("task", "show", "alpha-t")
    assert pre.returncode == 0 and "id: alpha-two\n" in pre.stdout
    uniq = sb.run("task", "show", "beta-o")
    assert uniq.returncode == 0 and "id: beta-one\n" in uniq.stdout
    amb = sb.run("task", "show", "beta")
    assert amb.returncode == 2
    assert "beta-one" in amb.stderr and "beta-two" in amb.stderr
    unk = sb.run("task", "show", "nope")
    assert unk.returncode == 2 and "nope" in unk.stderr


def test_removed_top_level_commands_are_usage_errors(sb: Sandbox) -> None:
    for args in (("new", "x"), ("list",), ("show", "x"), ("status",), ("transitions",)):
        res = sb.run(*args)
        assert res.returncode == 2, args
        assert "invalid choice" in res.stderr, args
