"""Unit tests of the `StartExplore` use case over a fake session (spec: cli, explore)."""

from __future__ import annotations

from fake_session import FakeSession

from samba.app.explore import StartExplore
from samba.app.results import Explored, Refused
from samba.prompts import EXPLORE_ALLOW, EXPLORE_GUIDE

FORBIDDEN = ["plan", "work", "adr accept", "adr reject", "adr supersede", "task discard",
             "task stop", "task retry", "question answer"]
ADR_0004_ALLOW = ["Bash(samba task new:*)", "Bash(samba task list:*)", "Bash(samba task show:*)",
                  "Bash(samba question list:*)", "Bash(samba question show:*)",
                  "Bash(samba adr list:*)", "Bash(samba adr show:*)"]


def start(session: FakeSession, topic: str | None, model: str | None = None) -> Explored | Refused:
    return StartExplore(["claude", "--x"], model, "/the/repo", session).run(topic)


def values(argv: tuple[str, ...], flag: str) -> list[str]:
    rest = argv[argv.index(flag) + 1:]
    out: list[str] = []
    for item in rest:
        if item.startswith("--"):
            break
        out.append(item)
    return out


def test_a_topic_is_the_first_prompt_after_the_command_and_cwd_is_the_repo() -> None:
    s = FakeSession()
    start(s, "queues")
    assert s.specs[0].argv[:3] == ("claude", "--x", "queues")
    assert s.specs[0].cwd == "/the/repo"


def test_no_topic_means_no_positional() -> None:
    s = FakeSession()
    start(s, None)
    assert s.specs[0].argv[:3] == ("claude", "--x", "--append-system-prompt")


def test_model_only_when_configured() -> None:
    a, b = FakeSession(), FakeSession()
    start(a, None)
    start(b, None, "opus")
    assert "--model" not in a.specs[0].argv
    assert values(b.specs[0].argv, "--model") == ["opus"]


def test_the_session_is_interactive_and_not_isolated() -> None:
    s = FakeSession()
    start(s, "t")
    argv = s.specs[0].argv
    for flag in ("-p", "--permission-mode", "--output-format", "--setting-sources", "--settings",
                 "--json-schema", "--strict-mcp-config"):
        assert flag not in argv


def test_allow_and_deny_lists() -> None:
    s = FakeSession()
    start(s, "t")
    argv = s.specs[0].argv
    allow = values(argv, "--allowedTools")
    deny = values(argv, "--disallowedTools")
    assert allow == list(EXPLORE_ALLOW)
    assert [a for a in allow if a.startswith("Bash(")] == ADR_0004_ALLOW
    assert deny == [f"Bash(samba {c}:*)" for c in FORBIDDEN]
    assert not set(allow) & set(deny)


def test_the_guide_is_appended_to_the_system_prompt() -> None:
    s = FakeSession()
    start(s, "t")
    argv = s.specs[0].argv
    assert values(argv, "--append-system-prompt") == [EXPLORE_GUIDE]
    for phrase in ("proposed", "docs/adr", "One decision per ADR", "NNNN",
                   "say which task it is and why"):
        assert phrase in EXPLORE_GUIDE
    assert "—" not in EXPLORE_GUIDE


def test_the_exit_code_of_the_session_is_returned() -> None:
    assert start(FakeSession(exit_code=3), None) == Explored(3)


def test_a_launch_error_is_a_refusal() -> None:
    assert start(FakeSession(error="cannot start claude"), None) == Refused(
        "refused", ("samba: cannot start claude",))
