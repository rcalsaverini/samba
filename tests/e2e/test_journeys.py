"""A few whole journeys of a task through the real program (spec: overview, states).

Each rule on the way is tested lower down; these show that the pieces are wired together: the
command line, the orchestrator loop, the markdown store, git worktrees and the agent process.
"""

from __future__ import annotations

from e2e_box import Box, git


def test_a_task_goes_from_new_through_plan_and_work_to_merged(box: Box) -> None:
    """The main journey, with a real merge into the base branch."""
    tid = box.new_task("Add a feature")
    box.steps(tid, {"plan": "1. write feature.txt"},
              {"write": {"feature.txt": "done\n"}, "commit": True, "summary": "wrote it"})
    box.run_idle()
    assert box.state_of(tid) == "plan-review"
    assert "1. write feature.txt" in box.task_text(tid)
    assert box.run("plan", "accept", tid).returncode == 0
    box.run_idle()
    assert box.state_of(tid) == "work-review"
    res = box.run("work", "accept", tid, "--yes")
    assert res.returncode == 0, res.stderr
    assert box.state_of(tid) == "done"
    assert (box.repo / "feature.txt").read_text() == "done\n"
    assert git(box.repo, "status", "--porcelain", "--untracked-files=no") == ""
    assert git(box.repo, "log", "-1", "--format=%s").startswith(f"Merge samba/{tid}")


def test_a_blocked_agent_asks_and_the_answer_resumes_the_task(box: Box) -> None:
    """A question round through the files and the command line."""
    tid = box.new_task("Pick a database", "--skip-plan")
    box.steps(tid, {"outcome": "blocked", "summary": "need input",
                    "questions": [{"text": "Which database?", "context": "storage"}]},
              {"summary": "used postgres"})
    box.run_idle()
    assert box.state_of(tid) == "question"
    listed = box.run("question", "list")
    assert f"{tid}/q1" in listed.stdout and "Which database?" in listed.stdout
    assert box.run("question", "answer", tid, "postgres").returncode == 0
    box.run_idle()
    assert box.state_of(tid) == "work-review"
    assert "postgres" in box.calls(tid)[-1]["argv"][1]  # the answer reaches the next prompt


def test_failures_are_retried_then_given_up_and_a_retry_runs_again(box: Box) -> None:
    """Retries, give up and a human retry across several runs of the program."""
    box.workflow(max_attempts=2, reflect_on_give_up=False)
    tid = box.new_task("Flaky", "--skip-plan")
    box.steps(tid, {"no_result": True, "exit_code": 1}, {"no_result": True, "exit_code": 1},
              {"summary": "fixed"})
    box.run_idle()
    assert box.state_of(tid) == "stuck"
    assert len(box.calls(tid)) == 2
    res = box.run("task", "retry", tid)
    assert res.returncode == 0, res.stderr
    box.run_idle()
    assert box.state_of(tid) == "work-review"


def test_exit_when_idle_returns_while_a_task_waits_on_its_dependency(box: Box) -> None:
    """The loop of the real program ends when nothing it can do is left."""
    first = box.new_task("First", "--skip-plan")
    second = box.new_task("Second", "--skip-plan", "--depends-on", first)
    box.run_idle()
    assert box.state_of(first) == "work-review"  # waits for a human, so second keeps waiting
    assert box.state_of(second) == "work-todo"
    assert box.calls(second) == []
