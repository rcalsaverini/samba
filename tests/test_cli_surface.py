"""Black-box tests for the shape of the command line (spec: cli). Must not import samba."""

from __future__ import annotations

import re
import subprocess

from conftest import Sandbox, samba_cmd


def bare(sb: Sandbox, *words: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Run samba with exactly these words (the fixture's `run` appends `--repo`, which help and completion do not take)."""
    return subprocess.run([*samba_cmd(), *words], cwd=sb.repo, env=sb.env(**env),
                          capture_output=True, text=True, timeout=60)


def listed_commands(text: str) -> list[str]:
    """Names in the `Commands:` block of a plain Click help text."""
    names: list[str] = []
    in_block = False
    for line in text.splitlines():
        if line.startswith("Commands:"):
            in_block = True
        elif in_block:
            m = re.match(r"^ +(\S+)(\s{2,}|$)", line)
            if not m:
                break
            names.append(m.group(1))
    return names


def test_help_lists_only_the_known_commands(sb: Sandbox) -> None:
    res = bare(sb, "--help")
    assert res.returncode == 0, res.stderr
    assert listed_commands(res.stdout) == ["run", "task", "plan", "work", "question", "adr",
                                           "explore"], res.stdout
    assert res.stdout.index("development commands:") > res.stdout.index("question")
    assert "Samba itself" in res.stdout


def test_help_is_plain_text_when_piped(sb: Sandbox) -> None:
    for words in (("--help",), ("task", "--help"), ("work", "accept", "--help")):
        res = bare(sb, *words)
        assert res.returncode == 0, res.stderr
        assert "\x1b" not in res.stdout and "\x1b" not in res.stderr
        assert not re.search("[─-╿]", res.stdout), res.stdout


def test_dev_transitions_prints_the_table(sb: Sandbox) -> None:
    res = sb.run("dev", "transitions")
    assert res.returncode == 0, res.stderr
    assert "plan.accept" in res.stdout
    assert res.stdout.lstrip().startswith("|")


def test_dev_transitions_needs_no_repo_config(sb: Sandbox) -> None:
    (sb.repo / "WORKFLOW.md").unlink()
    assert sb.run("dev", "transitions").returncode == 0


def test_usage_errors_exit_2(sb: Sandbox) -> None:
    for words in (("nonsense",), ("plan", "accept"), ("plan", "reject", "t1", "--feedback", "a", "--edit"),
                  ("question", "answer", "t1", "text", "--edit"), ("task", "new", "--priority", "x"),
                  ("task",)):
        res = sb.run(*words)
        assert res.returncode == 2, (words, res.stdout, res.stderr)
        assert res.stderr.strip(), words


def test_repo_option_may_follow_the_arguments(sb: Sandbox) -> None:
    res = sb.run("task", "list", "done", "--repo", str(sb.repo))
    assert res.returncode == 0, res.stderr


def test_show_completion_prints_a_script(sb: Sandbox) -> None:
    """With shell detection off, `--show-completion SHELL` prints that script (never install in a test)."""
    for shell in ("bash", "zsh", "fish"):
        res = bare(sb, "--show-completion", shell, _TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION="1")
        assert res.returncode == 0, res.stderr
        assert "samba" in res.stdout.lower(), shell


def test_bash_completion_offers_command_names_and_options(sb: Sandbox) -> None:
    def complete(*words: str) -> list[str]:
        res = bare(sb, _SAMBA_COMPLETE="complete_bash", COMP_WORDS=" ".join(["samba", *words]),
                   COMP_CWORD=str(len(words)))
        assert res.returncode == 0, res.stderr
        return [line.split(",", 1)[-1] for line in res.stdout.splitlines()]

    assert "plan" in complete("pl")
    assert "reject" in complete("plan", "r") and "accept" not in complete("plan", "r")
    assert "--feedback" in complete("plan", "reject", "t1", "--f")
    assert "dev" not in complete("")
