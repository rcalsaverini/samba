"""The AgentRunner port and its in-memory fake (spec: running-claude, Adapter boundary)."""

from __future__ import annotations

import asyncio

from samba.domain.agent import AgentReport, AgentRequest, Failure, QuestionDraft
from samba.ports import AgentRunner

from fake_agent import FakeAgentRunner


def request(n: int = 1) -> AgentRequest:
    return AgentRequest(prompt=f"p{n}", session_id="s", resume=False, system_prompt="sys",
                        max_budget_usd=None, kind="work", location="/ws", log_name=f"t/{n:03d}")


def test_fake_returns_scripted_reports_in_order_and_records_requests() -> None:
    reports = [
        AgentReport(outcome="continue", summary="one"),
        AgentReport(outcome="blocked", summary="two",
                    questions=(QuestionDraft(text="why?", context="c"),)),
        AgentReport(outcome="missing", failure=Failure(kind="timeout", detail="turn timeout")),
    ]
    fake = FakeAgentRunner(reports)
    runner: AgentRunner = fake

    async def go() -> list[AgentReport]:
        assert (await runner.ready()).ok
        return [await runner.run(request(i)) for i in (1, 2, 3)]

    assert asyncio.run(go()) == reports
    assert [r.prompt for r in fake.requests] == ["p1", "p2", "p3"]
    assert reports[0].ok and not reports[2].ok
