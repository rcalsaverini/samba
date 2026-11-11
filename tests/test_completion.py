"""Black-box tests for dynamic shell completion of ids (spec: cli, Shell completion). Drives
Click's environment-based completion. Must not import samba."""

from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import Sandbox, samba_cmd
from test_adr import write_adr


def complete(sb: Sandbox, *words: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = sb.env(_SAMBA_COMPLETE="complete_bash", COMP_WORDS=" ".join(["samba", *words]),
                 COMP_CWORD=str(len(words)))
    return subprocess.run(samba_cmd(), cwd=cwd or sb.repo, env=env, capture_output=True,
                          text=True, timeout=60)


def offered(sb: Sandbox, *words: str, cwd: Path | None = None) -> list[str]:
    res = complete(sb, *words, cwd=cwd)
    assert res.returncode == 0, res.stderr
    assert res.stderr == ""
    return [line.split(",", 1)[-1] for line in res.stdout.splitlines() if line]


def seed_tasks(sb: Sandbox) -> None:
    for tid, state in (("pa-one", "plan-review"), ("pb-two", "plan-review"),
                       ("wa-one", "work-review"), ("sa-one", "stuck"),
                       ("ra-one", "work-running"), ("da-one", "done")):
        sb.add_task(tid, state=state)


def test_plan_accept_and_reject_offer_plan_review_tasks(sb: Sandbox) -> None:
    seed_tasks(sb)
    assert sorted(offered(sb, "plan", "accept", "")) == ["pa-one", "pb-two"]
    assert sorted(offered(sb, "plan", "reject", "")) == ["pa-one", "pb-two"]


def test_work_accept_and_reject_offer_work_review_tasks(sb: Sandbox) -> None:
    seed_tasks(sb)
    assert offered(sb, "work", "accept", "") == ["wa-one"]
    assert offered(sb, "work", "reject", "") == ["wa-one"]


def test_task_retry_offers_stuck_and_stop_offers_running(sb: Sandbox) -> None:
    seed_tasks(sb)
    assert offered(sb, "task", "retry", "") == ["sa-one"]
    assert offered(sb, "task", "stop", "") == ["ra-one"]


def test_task_show_offers_every_task(sb: Sandbox) -> None:
    seed_tasks(sb)
    assert len(offered(sb, "task", "show", "")) == 6


def test_a_prefix_filters_the_candidates(sb: Sandbox) -> None:
    seed_tasks(sb)
    assert offered(sb, "plan", "accept", "pb") == ["pb-two"]
    assert offered(sb, "plan", "accept", "zz") == []


def test_question_answer_offers_task_slash_qid_of_open_questions(sb: Sandbox) -> None:
    sb.add_task("qa-one", state="question")
    sb.write_sidecar("qa-one", {"questions": [
        {"id": "q1", "round": 1, "stage": "work", "status": "open", "text": "Which database?"},
        {"id": "q2", "round": 1, "stage": "work", "status": "answered", "text": "Old?",
         "answer": "yes"}]})
    assert offered(sb, "question", "answer", "") == ["qa-one/q1"]
    assert offered(sb, "question", "show", "") == ["qa-one/q1"]


def test_adr_completion_follows_the_status(sb: Sandbox) -> None:
    write_adr(sb, 1, "First one", status="accepted")
    write_adr(sb, 2, "Second one", status="proposed")
    write_adr(sb, 3, "Third one", status="proposed")
    assert offered(sb, "adr", "accept", "") == ["0002", "0003"]
    assert offered(sb, "adr", "reject", "") == ["0002", "0003"]
    assert offered(sb, "adr", "supersede", "") == ["0001"]
    assert offered(sb, "adr", "show", "") == ["0001", "0002", "0003"]
    assert offered(sb, "adr", "accept", "0003") == ["0003"]


def test_repo_option_is_honored(sb: Sandbox, tmp_path: Path) -> None:
    seed_tasks(sb)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    got = offered(sb, "plan", "accept", "--repo", str(sb.repo), "", cwd=elsewhere)
    assert sorted(got) == ["pa-one", "pb-two"]


def test_no_repo_gives_no_candidates_and_no_noise(sb: Sandbox, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert offered(sb, "plan", "accept", "", cwd=empty) == []
    assert offered(sb, "adr", "accept", "", cwd=empty) == []


def test_broken_workflow_gives_no_candidates_and_no_noise(sb: Sandbox) -> None:
    seed_tasks(sb)
    (sb.repo / "WORKFLOW.md").write_text("---\n: : [unclosed\n---\nbody\n")
    res = complete(sb, "plan", "accept", "")
    assert res.returncode == 0 and res.stdout.strip() == "" and res.stderr == ""
