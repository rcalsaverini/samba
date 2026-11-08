"""Black-box tests for the planning phase (SPEC §14). Must not import the samba package."""

from __future__ import annotations

import json
import time

from conftest import Sandbox, flag, git, prompt_of


def move(sb: Sandbox, task_id: str, src: str, dst: str) -> None:
    (sb.tasks_dir / dst).mkdir(exist_ok=True)
    (sb.tasks_dir / src / f"{task_id}.md").rename(sb.tasks_dir / dst / f"{task_id}.md")


def plan_section_count(text: str) -> int:
    return sum(1 for ln in text.splitlines() if ln.strip() == "## Plan")


def test_plan_task_ends_in_plan_review_read_only(sb: Sandbox) -> None:
    sb.add_task("t1", state="plan-todo")
    sb.steps("t1", {"plan": "Step one\n- [ ] do it", "summary": "planned it"})
    sb.run_idle()

    assert sb.state_of("t1") == "plan-review"
    text = sb.task_text("t1")
    assert "## Plan" in text and "- [ ] do it" in text
    assert "planned it" in sb.log_section("t1")
    argv = sb.calls("t1")[0]
    assert flag(argv, "--permission-mode") == "dontAsk"
    allow = argv[argv.index("--allowedTools") + 1:]
    assert allow[:3] == ["Read", "Grep", "Glob"]
    assert "Edit" not in argv and "Write" not in argv
    schema = json.loads(flag(argv, "--json-schema") or "{}")
    assert schema["properties"]["outcome"]["enum"] == ["planned", "blocked"]
    assert git(sb.repo, "rev-list", "--count", "main..samba/t1") == "0"
    assert sb.sidecar("t1")["last_outcome"] == "planned"


def test_allow_list_is_exactly_planning_allow(sb: Sandbox) -> None:
    sb.write_workflow(planning={"allow": ["Read", "Glob"]},
                      claude={"permission_mode": "bypassPermissions", "allow": ["Edit"]})
    sb.add_task("t1", state="plan-todo")
    sb.run_idle()
    argv = sb.calls("t1")[0]
    assert flag(argv, "--permission-mode") == "dontAsk"
    i = argv.index("--allowedTools")
    assert argv[i + 1:i + 3] == ["Read", "Glob"]
    assert argv[i + 3].startswith("--")


def test_approval_runs_execution_in_a_new_session(sb: Sandbox) -> None:
    sb.add_task("t1", state="plan-todo")
    sb.steps("t1", {"plan": "the plan"}, {"outcome": "done"})
    sb.run_idle()
    plan_session = sb.sidecar("t1")["plan_session_id"]
    assert plan_session

    move(sb, "t1", "plan-review", "work-todo")
    sb.run_idle()
    assert sb.state_of("t1") == "work-review"
    calls = sb.calls("t1")
    assert len(calls) == 2
    run = calls[1]
    session = flag(run, "--session-id")
    assert session and session != plan_session
    assert flag(run, "--resume") is None
    assert "approved plan" in (flag(run, "--append-system-prompt") or "")
    assert flag(run, "--permission-mode") == "dontAsk"
    assert "Edit" in run
    side = sb.sidecar("t1")
    assert side["plan_approved"] is True
    assert side["last_stage"] == "work"


def test_rejection_revises_the_same_plan(sb: Sandbox) -> None:
    sb.add_task("t1", state="plan-todo")
    sb.steps("t1", {"plan": "first plan"}, {"plan": "second plan"})
    sb.run_idle()
    plan_session = sb.sidecar("t1")["plan_session_id"]

    p = sb.tasks_dir / "plan-review" / "t1.md"
    p.write_text(p.read_text() + "\n## Feedback\nPlease use a different approach.\n")
    move(sb, "t1", "plan-review", "plan-todo")
    sb.run_idle()

    assert sb.state_of("t1") == "plan-review"
    run = sb.calls("t1")[1]
    assert flag(run, "--resume") == plan_session
    assert "revised plan" in prompt_of(run)
    text = sb.task_text("t1")
    assert plan_section_count(text) == 1
    assert "second plan" in text and "first plan" not in text
    assert "Please use a different approach." in text


def test_require_plan_plans_todo_tasks_first(sb: Sandbox) -> None:
    sb.write_workflow(planning={"require_plan": True})
    sb.add_task("t1")
    sb.steps("t1", {"plan": "gated plan"}, {"outcome": "done"})
    sb.run_idle()
    assert sb.state_of("t1") == "plan-review"
    assert len(sb.calls("t1")) == 1

    move(sb, "t1", "plan-review", "work-todo")
    sb.run_idle()
    assert sb.state_of("t1") == "work-review"
    assert len(sb.calls("t1")) == 2
    assert "Edit" in sb.calls("t1")[1]


def test_default_config_executes_todo_directly(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "done"})
    sb.run_idle()
    assert sb.state_of("t1") == "work-review"
    calls = sb.calls("t1")
    assert len(calls) == 1
    schema = json.loads(flag(calls[0], "--json-schema") or "{}")
    assert "planned" not in schema["properties"]["outcome"]["enum"]
    assert "plan_session_id" not in sb.sidecar("t1") or not sb.sidecar("t1")["plan_session_id"]


def test_planner_blocked_with_questions_then_replan(sb: Sandbox) -> None:
    sb.add_task("t1", state="plan-todo")
    sb.steps("t1", {"outcome": "blocked", "plan": "partial",
                    "questions": [{"text": "Which database?", "context": "storage"}]},
             {"plan": "full plan"})
    sb.run_idle()
    assert sb.state_of("t1") == "question"
    text = sb.task_text("t1")
    assert "## Questions" in text and "Which database?" in text
    assert sb.sidecar("t1")["last_outcome"] == "blocked"
    assert sb.sidecar("t1")["last_stage"] == "plan"

    move(sb, "t1", "question", "plan-todo")
    sb.run_idle()
    assert sb.state_of("t1") == "plan-review"
    assert "full plan" in sb.task_text("t1")
    assert sb.sidecar("t1")["attempts"] == 0


def test_planner_failure_is_retried_from_plan(sb: Sandbox) -> None:
    sb.add_task("t1", state="plan-todo")
    sb.steps("t1", {"is_error": True}, {"plan": "ok now"})
    sb.run_idle()
    assert sb.state_of("t1") == "plan-review"
    assert len(sb.calls("t1")) == 2
    assert "ok now" in sb.task_text("t1")


def test_planner_gives_up_without_reflection(sb: Sandbox) -> None:
    sb.write_workflow(max_attempts=1)
    sb.add_task("t1", state="plan-todo")
    sb.steps("t1", {"is_error": True}, {"plan": "never used"})
    sb.run_idle()
    assert sb.state_of("t1") == "stuck"
    assert len(sb.calls("t1")) == 1
    assert sb.sidecar("t1")["last_outcome"] == "failed"


def test_missing_plan_text_is_a_failure(sb: Sandbox) -> None:
    sb.write_workflow(max_attempts=1)
    sb.add_task("t1", state="plan-todo")
    sb.steps("t1", {"plan": "   "})
    sb.run_idle()
    assert sb.state_of("t1") == "stuck"


def test_planning_model_for_planning_and_claude_model_for_execution(sb: Sandbox) -> None:
    sb.write_workflow(planning={"model": "planner-model"}, claude={"model": "worker-model"})
    sb.add_task("t1", state="plan-todo")
    sb.steps("t1", {"plan": "p"}, {"outcome": "done"})
    sb.run_idle()
    move(sb, "t1", "plan-review", "work-todo")
    sb.run_idle()
    calls = sb.calls("t1")
    assert flag(calls[0], "--model") == "planner-model"
    assert flag(calls[1], "--model") == "worker-model"


def test_planning_model_defaults_to_claude_model(sb: Sandbox) -> None:
    sb.write_workflow(claude={"model": "worker-model"})
    sb.add_task("t1", state="plan-todo")
    sb.run_idle()
    assert flag(sb.calls("t1")[0], "--model") == "worker-model"


def test_recovery_replans_a_running_planning_task(sb: Sandbox) -> None:
    sb.add_task("t1", state="plan-running")
    sb.write_sidecar("t1", {"last_stage": "plan"})
    sb.steps("t1", {"plan": "recovered plan"})
    sb.run_idle()
    assert sb.state_of("t1") == "plan-review"
    argv = sb.calls("t1")[0]
    assert "planned" in (flag(argv, "--json-schema") or "")


def test_moving_task_out_of_running_stops_the_planner(sb: Sandbox) -> None:
    sb.add_task("t1", state="plan-todo")
    sb.steps("t1", {"hang": 30})
    proc = sb.popen("run", "--exit-when-idle")
    running = sb.tasks_dir / "plan-running" / "t1.md"
    deadline = time.monotonic() + 15
    while not (running.exists() and sb.calls("t1")) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert running.exists()
    move(sb, "t1", "plan-running", "discarded")
    assert proc.wait(timeout=15) == 0
    assert sb.state_of("t1") == "discarded"
    assert not sb.worktree("t1").exists()


def test_new_plan_creates_task_in_plan_folder(sb: Sandbox) -> None:
    res = sb.run("task", "new", "Design the thing")
    assert res.returncode == 0, res.stderr
    assert (sb.tasks_dir / "plan-todo" / "design-the-thing.md").exists()
    assert not (sb.tasks_dir / "work-todo" / "design-the-thing.md").exists()


def test_status_shows_plan_states(sb: Sandbox) -> None:
    sb.add_task("t1", state="plan-todo")
    sb.run_idle()
    res = sb.run("task", "list")
    assert "plan-review" in res.stdout


def test_plan_headings_do_not_split_the_plan_section(sb: Sandbox) -> None:
    sb.add_task("t1", state="plan-todo")
    sb.steps("t1", {"plan": "## Approach\nA\n## Steps\n- [ ] x"},
             {"plan": "## Approach\nB"})
    sb.run_idle()
    move(sb, "t1", "plan-review", "plan-todo")
    sb.run_idle()
    text = sb.task_text("t1")
    assert plan_section_count(text) == 1
    assert "- [ ] x" not in text and "B" in text
