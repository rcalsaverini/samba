"""Black-box tests for questions as data (spec: states, cli, running-claude). Must not import samba."""

from __future__ import annotations

from typing import Any

from conftest import Sandbox, prompt_of

TWO = [{"text": "Which database?", "context": "storage choice"},
       {"text": "Which port?", "context": "networking"}]


def block_two(sb: Sandbox, *more: dict[str, Any]) -> None:
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "blocked", "summary": "need input", "questions": TWO}, *more)
    sb.run_idle()


def qs(sb: Sandbox, task_id: str = "t1") -> list[dict[str, Any]]:
    return sb.sidecar(task_id)["questions"]


def answer(sb: Sandbox, *args: str) -> Any:
    return sb.run("question", "answer", *args)


def test_blocked_run_records_two_open_questions(sb: Sandbox) -> None:
    block_two(sb)
    assert sb.state_of("t1") == "question"
    q = qs(sb)
    assert [x["id"] for x in q] == ["q1", "q2"]
    assert all(x["status"] == "open" and x["round"] == 1 and x["stage"] == "work" for x in q)
    assert q[0]["text"] == "Which database?" and q[0]["context"] == "storage choice"
    assert q[0]["asked_at"] and q[0]["answer"] is None and q[0]["answered_at"] is None
    text = sb.task_text("t1")
    assert "## Questions" in text
    assert "q1 (round 1, open)" in text and "q2 (round 1, open)" in text
    assert "Which port?" in text and "Context: networking" in text
    res = sb.run("question", "list")
    assert res.returncode == 0
    lines = res.stdout.splitlines()
    assert lines[0].split() == ["TASK", "QID", "STAGE", "ASKED", "QUESTION"]
    assert len(lines) == 3
    assert "t1/q1" in lines[1] and "work" in lines[1] and "Which database?" in lines[1]
    assert "t1/q2" in lines[2]


def test_question_list_truncates_to_terminal_width(sb: Sandbox) -> None:
    sb.add_task("t1")
    long = "Should we use " + "a very long question text " * 10
    sb.steps("t1", {"outcome": "blocked", "questions": [{"text": long, "context": "c"}]})
    sb.run_idle()
    res = sb.run("question", "list", COLUMNS="70")
    rows = res.stdout.splitlines()
    assert all(len(r) <= 70 for r in rows), rows
    assert rows[1].endswith("...")


def test_question_list_shows_full_text_on_wide_terminal(sb: Sandbox) -> None:
    sb.add_task("t1")
    long = "Should we use the managed database " + "with a very long reason " * 5
    long = long.strip()
    sb.steps("t1", {"outcome": "blocked", "questions": [{"text": long, "context": "c"}]})
    sb.run_idle()
    wide = sb.run("question", "list", COLUMNS="200").stdout.splitlines()
    assert len(long) > 100
    assert wide[1].endswith(long) and "..." not in wide[1]
    narrow = sb.run("question", "list", COLUMNS="70").stdout.splitlines()
    assert narrow[1].endswith("...") and len(narrow[1]) <= 70
    for row in (wide[1], narrow[1]):
        assert row.split()[:3] == ["t1", "t1/q1", "work"]
        assert " 20" in row[:40]


def test_partial_answer_keeps_task_in_question_then_resumes(sb: Sandbox) -> None:
    block_two(sb, {"outcome": "done"})
    res = answer(sb, "t1/q1", "Use SQLite.")
    assert res.returncode == 0, res.stderr
    assert sb.state_of("t1") == "question"
    q = qs(sb)
    assert q[0]["status"] == "answered" and q[0]["answer"] == "Use SQLite."
    assert q[0]["answered_at"] and q[1]["status"] == "open"
    text = sb.task_text("t1")
    assert "q1 (round 1, answered)" in text and "Answer: Use SQLite." in text
    assert "q2 (round 1, open)" in text
    assert "question.answer: t1/q1 answered" in sb.log_section("t1")
    assert "t1/q2" in sb.run("question", "list").stdout
    assert "t1/q1" not in sb.run("question", "list").stdout

    res = answer(sb, "t1/q2", "Port 8080.")
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == str(sb.tasks_dir / "work-todo" / "t1.md")
    assert sb.state_of("t1") == "work-todo"
    assert "## Feedback" not in sb.task_text("t1")
    log = sb.log_section("t1")
    assert "question.answer: t1/q2 answered" in log
    assert "question.answer: question -> work-todo" in log

    sb.run_idle()
    assert sb.state_of("t1") == "work-review"
    prompt = prompt_of(sb.calls("t1")[1])
    assert "Which database?" in prompt and "Use SQLite." in prompt
    assert "Which port?" in prompt and "Port 8080." in prompt


def test_prefix_and_omitted_qid_with_one_open(sb: Sandbox) -> None:
    sb.add_task("task-one")
    sb.steps("task-one", {"outcome": "blocked",
                          "questions": [{"text": "Which?", "context": "c"}]})
    sb.run_idle()
    res = answer(sb, "task", "Left.")
    assert res.returncode == 0, res.stderr
    assert sb.state_of("task-one") == "work-todo"


def test_qid_omitted_with_two_open_is_usage_error(sb: Sandbox) -> None:
    block_two(sb)
    before = sb.sidecar("t1")
    res = answer(sb, "t1", "text")
    assert res.returncode == 2
    assert "t1/q1" in res.stderr and "t1/q2" in res.stderr
    assert sb.sidecar("t1") == before and sb.state_of("t1") == "question"


def test_answer_usage_and_state_errors(sb: Sandbox) -> None:
    block_two(sb)
    assert answer(sb, "t1/q9", "x").returncode == 2  # unknown qid
    assert answer(sb, "t1/q1").returncode == 2  # no text
    assert answer(sb, "t1/q1", "   ").returncode == 2  # blank text
    assert answer(sb, "nope/q1", "x").returncode == 2  # unknown task
    assert answer(sb, "t1/q1", "ok").returncode == 0
    res = answer(sb, "t1/q1", "again")  # answered, not open
    assert res.returncode == 1 and "not open" in res.stderr
    assert qs(sb)[0]["answer"] == "ok"


def test_second_round_gets_next_id_and_round(sb: Sandbox) -> None:
    block_two(sb, {"outcome": "blocked", "questions": [{"text": "Which cache?", "context": "c"}]})
    assert answer(sb, "t1/q1", "a").returncode == 0
    assert answer(sb, "t1/q2", "b").returncode == 0
    sb.run_idle()
    assert sb.state_of("t1") == "question"
    q = qs(sb)
    assert [(x["id"], x["round"], x["status"]) for x in q] == [
        ("q1", 1, "answered"), ("q2", 1, "answered"), ("q3", 2, "open")]
    shown = sb.run("question", "show", "t1")
    assert shown.returncode == 0
    assert "Which cache?" in shown.stdout and "Which database?" not in shown.stdout
    assert "open" in shown.stdout
    one = sb.run("question", "show", "t1/q1")
    assert "Which database?" in one.stdout and "storage choice" in one.stdout
    assert "Answer: a" in one.stdout
    assert sb.run("question", "show", "t1/q7").returncode == 2
    text = sb.task_text("t1")
    assert "q1 (round 1, answered)" in text and "q3 (round 2, open)" in text


def test_hand_move_dismisses_open_questions(sb: Sandbox) -> None:
    block_two(sb, {"outcome": "done"})
    assert answer(sb, "t1/q1", "Use SQLite.").returncode == 0
    sb.move("t1", "question", "work-todo")
    sb.run_idle()
    assert sb.state_of("t1") == "work-review"
    q = qs(sb)
    assert q[0]["status"] == "answered" and q[1]["status"] == "dismissed"
    assert q[1]["answer"] is None
    text = sb.task_text("t1")
    assert "q2 (round 1, dismissed)" in text and "q1 (round 1, answered)" in text
    assert "question.answer: question -> work-todo: observed hand move" in sb.log_section("t1")
    prompt = prompt_of(sb.calls("t1")[1])
    assert "Use SQLite." in prompt and "dismissed" in prompt


def test_plan_assumptions_render_under_the_new_name(sb: Sandbox) -> None:
    sb.add_task("t1", state="plan-todo")
    sb.steps("t1", {"plan": "the plan", "assumptions": "We assume Postgres."})
    sb.run_idle()
    text = sb.task_text("t1")
    assert "## Assumptions" in text and "We assume Postgres." in text
    assert "## Questions" not in text
    assert sb.sidecar("t1").get("questions", []) == []


def test_blocked_planner_records_plan_stage_questions(sb: Sandbox) -> None:
    sb.add_task("t1", state="plan-todo")
    sb.steps("t1", {"outcome": "blocked", "plan": "partial",
                    "questions": [{"text": "Which cloud?", "context": "cost"}]},
             {"plan": "full plan"})
    sb.run_idle()
    assert sb.state_of("t1") == "question"
    assert qs(sb)[0]["stage"] == "plan" and qs(sb)[0]["status"] == "open"
    assert "t1/q1" in sb.run("question", "list").stdout
    assert answer(sb, "t1", "AWS").returncode == 0
    assert sb.state_of("t1") == "plan-todo"
    sb.run_idle()
    assert sb.state_of("t1") == "plan-review"
    prompt = prompt_of(sb.calls("t1")[1])
    assert "Which cloud?" in prompt and "AWS" in prompt


def test_blocked_without_questions_synthesizes_one(sb: Sandbox) -> None:
    sb.add_task("t1")
    sb.steps("t1", {"outcome": "blocked", "summary": "cannot run tests", "denials": ["Bash"]})
    sb.run_idle()
    assert sb.state_of("t1") == "question"
    assert len(sb.calls("t1")) == 1  # never retried
    q = qs(sb)
    assert len(q) == 1 and q[0]["status"] == "open"
    assert q[0]["text"] == "cannot run tests"
    assert "synthesized" in q[0]["context"] and "Bash" in q[0]["context"]


def test_old_task_without_questions_field(sb: Sandbox) -> None:
    sb.add_task("old", state="question")
    sb.write_sidecar("old", {"state": "question", "last_stage": "work",
                             "blocked_cause": "question"})
    res = sb.run("question", "list")
    assert res.returncode == 0 and len(res.stdout.splitlines()) == 1
    assert answer(sb, "old", "text").returncode == 1
    sb.move("old", "question", "work-todo")
    sb.run_idle()
    assert sb.state_of("old") == "work-review"


def test_question_help_lists_verbs(sb: Sandbox) -> None:
    out = sb.run("question", "--help").stdout
    assert all(v in out for v in ("list", "show", "answer"))
    assert "question" in sb.run("--help").stdout


def test_task_show_counts_open_questions(sb: Sandbox) -> None:
    block_two(sb)
    assert "open_questions: 2" in sb.run("task", "show", "t1").stdout
