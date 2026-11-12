"""Black-box tests of `samba explore` with the fake claude (spec: cli, explore). Must not import samba."""

from __future__ import annotations

from legacy_support import Sandbox, flag

FORBIDDEN = ["plan", "work", "adr accept", "adr reject", "adr supersede", "task discard",
             "task stop", "task retry", "question answer"]
SAMBA_ALLOWED = ["task new", "task list", "task show", "question list", "question show",
                 "adr list", "adr show"]


def values(argv: list[str], name: str) -> list[str]:
    out: list[str] = []
    for item in argv[argv.index(name) + 1:]:
        if item.startswith("--"):
            break
        out.append(item)
    return out


def explore(sb: Sandbox, *args: str) -> list[str]:
    res = sb.run("explore", *args)
    assert res.returncode == 0, res.stderr
    calls = sb.calls("repo")
    assert len(calls) == 1, calls
    return calls[0]


def test_the_topic_is_the_first_prompt_and_there_is_no_headless_flag(sb: Sandbox) -> None:
    argv = explore(sb, "queue design")
    assert argv[0] == "queue design"
    assert "-p" not in argv and "--output-format" not in argv


def test_without_a_topic_there_is_no_positional(sb: Sandbox) -> None:
    argv = explore(sb)
    assert argv[0] == "--append-system-prompt"


def test_the_guide_is_appended(sb: Sandbox) -> None:
    guide = flag(explore(sb, "t"), "--append-system-prompt")
    assert guide is not None
    for phrase in ("status: proposed", "docs/adr/NNNN", "One decision per ADR",
                   "say which task it is and why"):
        assert phrase in guide


def test_the_allow_list_is_the_adr_0004_list_and_nothing_forbidden(sb: Sandbox) -> None:
    allow = values(explore(sb, "t"), "--allowedTools")
    assert [a for a in allow if a.startswith("Bash(")] == [
        f"Bash(samba {c}:*)" for c in SAMBA_ALLOWED]
    for cmd in FORBIDDEN:
        assert not any(f"samba {cmd}" in a for a in allow), cmd


def test_the_deny_list_names_every_forbidden_command(sb: Sandbox) -> None:
    deny = values(explore(sb, "t"), "--disallowedTools")
    assert deny == [f"Bash(samba {c}:*)" for c in FORBIDDEN]


def test_the_session_runs_in_the_repo_and_is_not_isolated(sb: Sandbox) -> None:
    argv = explore(sb, "t")
    for name in ("--permission-mode", "--setting-sources", "--settings", "--strict-mcp-config"):
        assert name not in argv
    call = (sb.plan_dir / "repo.calls.jsonl").read_text()
    assert str(sb.repo.resolve()) in call


def test_the_model_comes_from_the_workflow(sb: Sandbox) -> None:
    sb.write_workflow(claude={"model": "opus"})
    assert flag(explore(sb, "t"), "--model") == "opus"


def test_the_exit_code_of_claude_is_returned(sb: Sandbox) -> None:
    sb.steps("repo", {"outcome": None, "no_result": True, "exit_code": 7})
    assert sb.run("explore", "t").returncode == 7


def test_a_missing_workflow_is_a_config_error_and_nothing_starts(sb: Sandbox) -> None:
    (sb.repo / "WORKFLOW.md").unlink()
    res = sb.run("explore", "t")
    assert res.returncode == 2
    assert "config error" in res.stderr
    assert sb.calls("repo") == []


def test_a_missing_claude_binary_is_refused(sb: Sandbox) -> None:
    sb.write_workflow(claude={"command": "/nonexistent/claude-binary"})
    res = sb.run("explore", "t")
    assert res.returncode == 1
    assert res.stderr.startswith("samba: ")


def test_nothing_is_created_under_samba(sb: Sandbox) -> None:
    explore(sb, "t")
    assert not (sb.repo / ".samba").exists()
