"""Black-box tests for the shape of the command line (SPEC §11). Must not import symphony."""

from __future__ import annotations

import re

from conftest import Sandbox


def test_help_lists_only_the_six_nouns(sb: Sandbox) -> None:
    res = sb.run("--help")
    assert res.returncode == 0, res.stderr
    names = [n for n in re.findall(r"^ +(\S+)\s", res.stdout, flags=re.MULTILINE)
             if not n.startswith("-") and n != "COMMAND"]
    assert names == ["run", "task", "plan", "work", "question", "dev"], res.stdout
    assert res.stdout.index("development commands:") > res.stdout.index("question")
    assert "Symphony itself" in res.stdout


def test_dev_transitions_prints_the_table(sb: Sandbox) -> None:
    res = sb.run("dev", "transitions")
    assert res.returncode == 0, res.stderr
    assert "plan.accept" in res.stdout
    assert res.stdout.lstrip().startswith("|")


def test_dev_transitions_needs_no_repo_config(sb: Sandbox) -> None:
    (sb.repo / "WORKFLOW.md").unlink()
    assert sb.run("dev", "transitions").returncode == 0
