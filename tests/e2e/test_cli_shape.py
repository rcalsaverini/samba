"""The shape of the `samba` command (spec: cli): names, help, exit codes, stdout and stderr."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from e2e_box import Box, samba_cmd


def bare(box: Box, *words: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Exactly these words, no `--repo` appended (help takes none)."""
    return subprocess.run([*samba_cmd(), *words], cwd=cwd or box.repo, env=box.env(),
                          capture_output=True, text=True, timeout=60)


def listed(text: str) -> list[str]:
    """The names in the `Commands:` block of a plain help text."""
    names: list[str] = []
    block = False
    for line in text.splitlines():
        if line.startswith("Commands:"):
            block = True
        elif block:
            m = re.match(r"^ +(\S+)(\s{2,}|$)", line)
            if not m:
                break
            names.append(m.group(1))
    return names


def test_help_lists_exactly_the_public_commands_and_dev_apart(box: Box) -> None:
    """The command names and their order are what a person types."""
    res = bare(box, "--help")
    assert res.returncode == 0, res.stderr
    assert listed(res.stdout) == ["run", "task", "plan", "work", "question", "adr", "explore"]
    assert res.stdout.index("development commands:") > res.stdout.index("question")
    assert "Samba itself" in res.stdout


@pytest.mark.parametrize("noun, verbs", [
    ("task", ["new", "list", "show", "retry", "stop", "discard"]),
    ("question", ["list", "show", "answer"]),
    ("adr", ["list", "show", "accept", "reject", "supersede"]),
])
def test_each_noun_lists_its_verbs(box: Box, noun: str, verbs: list[str]) -> None:
    """Verbs are part of the command surface."""
    res = bare(box, noun, "--help")
    assert res.returncode == 0, res.stderr
    assert set(verbs) <= set(listed(res.stdout)), res.stdout


def test_help_is_plain_text_when_piped(box: Box) -> None:
    """Colors and boxes would break scripts that read the output."""
    for words in (("--help",), ("task", "--help"), ("work", "accept", "--help")):
        res = bare(box, *words)
        assert res.returncode == 0, res.stderr
        assert "\x1b" not in res.stdout + res.stderr
        assert not re.search("[─-╿]", res.stdout), res.stdout


@pytest.mark.parametrize("words", [
    ("nonsense",), ("new", "x"), ("list",), ("status",), ("transitions",),  # unknown or removed
    ("plan", "accept"),  # a missing argument
    ("plan", "reject", "t1", "--feedback", "a", "--edit"),  # options that exclude each other
    ("question", "answer", "t1", "text", "--edit"),
    ("task", "new", "--priority", "x"),  # a bad type
    ("task", "new", "T", "--plan"),  # an option that no longer exists
    ("task",),
])
def test_usage_errors_exit_2_with_a_message_on_stderr_and_change_nothing(
        box: Box, words: tuple[str, ...]) -> None:
    """Exit code 2 and stderr are the contract of a usage error."""
    res = box.run(*words)
    assert res.returncode == 2, (words, res.stdout, res.stderr)
    assert res.stderr.strip() and not res.stdout.strip(), words
    assert not (box.repo / ".samba" / "tasks" / "plan-todo" / "t.md").exists()


def test_the_repo_option_may_follow_the_arguments(box: Box) -> None:
    """Option placement is parsed by the command line."""
    res = bare(box, "task", "list", "done", "--repo", str(box.repo), cwd=box.root)
    assert res.returncode == 0, res.stderr


def test_a_refusal_exits_1_with_its_message_on_stderr_only(box: Box) -> None:
    """The exit code and the stdout and stderr split of a refused command."""
    tid = box.new_task("Feature", "--skip-plan")
    res = box.run("plan", "accept", tid)
    assert res.returncode == 1 and res.stdout == ""
    assert res.stderr.startswith("samba: ") and "plan.accept" in res.stderr
    assert box.state_of(tid) == "work-todo"


def test_a_done_command_prints_the_task_file_on_stdout(box: Box) -> None:
    """Where a command's result goes: the task file path on stdout."""
    tid = box.new_task("Feature")
    assert box.state_of(tid) == "plan-todo"
    res = box.run("task", "discard", tid, "--yes")
    assert res.returncode == 0, res.stderr
    assert Path(res.stdout.strip()) == box.repo / ".samba" / "tasks" / "discarded" / f"{tid}.md"


@pytest.mark.parametrize("workflow", ["missing", "broken"])
def test_a_missing_or_broken_workflow_is_a_config_error(box: Box, workflow: str) -> None:
    """Reading WORKFLOW.md happens in the composition of the whole program."""
    path = box.repo / "WORKFLOW.md"
    if workflow == "missing":
        path.unlink()
    else:
        path.write_text("---\nmax_concurrent: [1\n---\nbody\n")
    res = box.run("task", "list")
    assert res.returncode == 2
    assert res.stderr.startswith("samba: config error")


def test_adr_and_dev_commands_need_no_workflow(box: Box) -> None:
    """Which commands load WORKFLOW.md is decided where the program is wired."""
    (box.repo / "WORKFLOW.md").unlink()
    adr = box.run("adr", "list")
    assert adr.returncode == 0 and adr.stdout.split() == ["NUMBER", "TITLE", "SUMMARY"]
    dev = bare(box, "dev", "transitions", cwd=box.root)
    assert dev.returncode == 0 and dev.stdout.lstrip().startswith("|")
    assert "plan.accept" in dev.stdout


def test_claude_logged_out_refuses_to_start(box: Box) -> None:
    """Startup checks run before the loop, and their refusal is the exit code of `run`."""
    res = box.run("run", "--exit-when-idle", FAKE_CLAUDE_LOGGED_OUT="1")
    assert res.returncode == 1
    assert "claude auth login" in res.stderr
