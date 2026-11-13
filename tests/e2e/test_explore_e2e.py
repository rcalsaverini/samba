"""`samba explore` as a process (spec: cli, explore): what it needs and what it leaves behind."""

from __future__ import annotations

from e2e_box import Box


def test_explore_without_a_workflow_is_a_config_error_and_starts_nothing(box: Box) -> None:
    """Which configuration explore needs is decided where the program is wired."""
    (box.repo / "WORKFLOW.md").unlink()
    res = box.run("explore", "a topic")
    assert res.returncode == 2 and res.stderr.startswith("samba: config error")
    assert box.calls("repo") == []


def test_explore_with_a_missing_claude_binary_is_refused(box: Box) -> None:
    """Starting a program on the person's terminal can only fail in a real process."""
    box.workflow(claude={"command": "/no/such/claude"})
    res = box.run("explore", "a topic")
    assert res.returncode == 1 and res.stderr.startswith("samba: ")


def test_explore_runs_claude_in_the_repo_and_leaves_no_samba_folder(box: Box) -> None:
    """Explore is an interactive session, not a task: nothing is written under .samba."""
    res = box.run("explore", "a topic")
    assert res.returncode == 0, res.stderr
    [call] = box.calls("repo")
    assert call["argv"][0] == "a topic" and call["cwd"] == str(box.repo.resolve())
    assert not (box.repo / ".samba").exists()
