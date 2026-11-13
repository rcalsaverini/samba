"""Shell completion driven through the environment, and the manual against the real help."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from e2e_box import Box, samba_cmd
from test_cli_shape import bare, listed

ROOT = Path(__file__).resolve().parents[2]


def complete(box: Box, *words: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = box.env(_SAMBA_COMPLETE="complete_bash", COMP_WORDS=" ".join(["samba", *words]),
                  COMP_CWORD=str(len(words)))
    return subprocess.run(samba_cmd(), cwd=cwd or box.repo, env=env, capture_output=True,
                          text=True, timeout=60)


def offered(res: subprocess.CompletedProcess[str]) -> list[str]:
    assert res.returncode == 0, res.stderr
    return [line.split(",", 1)[-1] for line in res.stdout.splitlines()]


def test_completion_offers_commands_options_and_the_tasks_a_verb_can_act_on(box: Box) -> None:
    """Completion is a protocol between the shell and the process."""
    review = box.new_task("In review")
    todo = box.new_task("Still todo", "--skip-plan")
    box.run_idle()  # the planner runs once: plan-todo -> plan-review
    assert box.state_of(review) == "plan-review" and box.state_of(todo) == "work-review"
    assert "plan" in offered(complete(box, "pl"))
    assert "reject" in offered(complete(box, "plan", "r"))
    assert "--feedback" in offered(complete(box, "plan", "reject", "t1", "--f"))
    assert "dev" not in offered(complete(box, ""))
    assert offered(complete(box, "plan", "accept", "")) == [review]
    assert offered(complete(box, "work", "accept", "")) == [todo]


def test_completion_honors_a_repo_typed_on_the_line(box: Box) -> None:
    """The partly typed command line, --repo included, is only seen by the process."""
    review = box.new_task("In review")
    box.run_idle()
    res = complete(box, "plan", "accept", "--repo", str(box.repo), "", cwd=box.root)
    assert review in offered(res)


@pytest.mark.parametrize("where", ["no repo", "broken workflow"])
def test_completion_is_silent_when_it_cannot_read_a_repo(box: Box, where: str) -> None:
    """A shell must never see a traceback while completing."""
    if where == "broken workflow":
        (box.repo / "WORKFLOW.md").write_text("---\nmax_concurrent: [1\n---\n")
        res = complete(box, "plan", "accept", "")
    else:
        res = complete(box, "plan", "accept", "", cwd=box.root)
    assert res.returncode == 0 and res.stderr == ""
    assert res.stdout.strip() == ""  # no candidate (bash reads an empty line as none)


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_show_completion_prints_a_script_for_each_shell(box: Box, shell: str) -> None:
    """The completion script is what the shell sources (never installed in a test)."""
    res = subprocess.run([*samba_cmd(), "--show-completion", shell], cwd=box.repo,
                         env=box.env(_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION="1"),
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    assert "samba" in res.stdout.lower()


def test_the_manual_mentions_every_command_the_help_lists(box: Box) -> None:
    """The manual follows the real command surface, read from --help."""
    manual = (ROOT / "docs" / "manual.md").read_text()
    top = listed(bare(box, "--help").stdout)
    assert {"run", "task", "plan", "work", "question", "adr", "explore"} <= set(top)
    missing: list[str] = []
    for noun in top:
        verbs = listed(bare(box, noun, "--help").stdout)
        for words in ([noun] if not verbs else [f"{noun} {v}" for v in verbs]):
            if not re.search(rf"samba {re.escape(words)}\b", manual):
                missing.append(words)
    assert missing == []
