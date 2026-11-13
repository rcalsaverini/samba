"""Unit tests of the `StartExplore` use case over a fake session (spec: cli, explore)."""

from __future__ import annotations

from fake_session import FakeSession

from samba.app.explore import StartExplore
from samba.app.results import Explored, Refused
from samba.domain.prompts import EXPLORE_ALLOW, EXPLORE_DENY, EXPLORE_GUIDE

FORBIDDEN = ["plan", "work", "adr accept", "adr reject", "adr supersede", "task discard",
             "task stop", "task retry", "question answer"]
ADR_0004_ALLOW = ["Bash(samba task new:*)", "Bash(samba task list:*)", "Bash(samba task show:*)",
                  "Bash(samba question list:*)", "Bash(samba question show:*)",
                  "Bash(samba adr list:*)", "Bash(samba adr show:*)"]


def start(session: FakeSession, topic: str | None) -> Explored | Refused:
    return StartExplore(EXPLORE_GUIDE, EXPLORE_ALLOW, EXPLORE_DENY, "/the/repo", session).run(topic)


def test_the_session_names_the_topic_and_the_location() -> None:
    s = FakeSession()
    start(s, "queues")
    assert s.sessions[0].topic == "queues"
    assert s.sessions[0].location == "/the/repo"


def test_no_topic_means_none() -> None:
    s = FakeSession()
    start(s, None)
    assert s.sessions[0].topic is None


def test_allow_and_deny_lists() -> None:
    s = FakeSession()
    start(s, "t")
    allow = list(s.sessions[0].allowed)
    deny = list(s.sessions[0].denied)
    assert allow == list(EXPLORE_ALLOW)
    assert [a for a in allow if a.startswith("Bash(")] == ADR_0004_ALLOW
    assert deny == [f"Bash(samba {c}:*)" for c in FORBIDDEN]
    assert not set(allow) & set(deny)


def test_the_guide_is_appended_to_the_system_prompt() -> None:
    s = FakeSession()
    start(s, "t")
    assert s.sessions[0].guide == EXPLORE_GUIDE
    for phrase in ("proposed", "docs/adr", "One decision per ADR", "NNNN",
                   "say which task it is and why"):
        assert phrase in EXPLORE_GUIDE
    assert "—" not in EXPLORE_GUIDE


def test_the_exit_code_of_the_session_is_returned() -> None:
    assert start(FakeSession(exit_code=3), None) == Explored(3)


def test_a_launch_error_is_a_refusal() -> None:
    assert start(FakeSession(error="cannot start claude"), None) == Refused(
        "refused", ("samba: cannot start claude",))
