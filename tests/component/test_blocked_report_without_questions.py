"""An agent that reports `blocked` with no question still reaches the human (spec: running-claude)."""

from __future__ import annotations

from test_app_run_task import Rig

from samba.domain.agent import AgentReport


def test_a_blocked_report_without_questions_gets_one_synthesized_from_its_summary() -> None:
    rig = Rig("work-running", [AgentReport(outcome="blocked", summary="cannot run tests",
                                           denials=("Bash",))])
    rig.run()
    assert rig.task.status == "question"
    assert len(rig.agent.requests) == 1  # a block is not a failure: never retried
    [q] = rig.task.questions
    assert q.status == "open" and q.text == "cannot run tests"
    assert "synthesized" in q.context and "Bash" in q.context
