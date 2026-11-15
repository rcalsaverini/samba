"""`samba init` through the real process: files on disk, stderr notes, exit codes."""

from __future__ import annotations

from e2e_box import Box


def test_init_scaffolds_a_project_that_samba_then_uses(box: Box) -> None:
    """Only the whole process shows that a repository with nothing but git becomes one Samba
    can use: init writes the files, a second run skips them on stderr with exit 0, and the new
    ADR 0 and WORKFLOW.md are read by the other commands."""
    (box.repo / "WORKFLOW.md").unlink()
    first = box.run("init", "--validate", "true")
    assert first.returncode == 0, first.stderr
    created = set(first.stdout.split())
    assert created == {"WORKFLOW.md", "CLAUDE.md", "docs/spec/README.md",
                       "docs/adr/0000-record-architecture-decisions.md"}
    assert 'command: "true"' in (box.repo / "WORKFLOW.md").read_text()
    again = box.run("init", "--validate", "true")
    assert again.returncode == 0 and again.stdout == ""
    assert not (box.repo / ".samba").exists()
    assert sorted(again.stderr.splitlines()) == sorted(f"skip {p} (exists)" for p in created)
    listed = box.run("adr", "list")
    assert listed.returncode == 0 and "0000" in listed.stdout
    assert box.run("task", "new", "First task", "--body", "Do it.").returncode == 0


def test_init_without_a_terminal_comments_validation_and_rejects_unknown_methods(
        box: Box) -> None:
    """Only a process without a terminal shows that init never asks and falls back to the
    commented form, that a dry run writes nothing, and that a bad method exits 2 (usage)."""
    (box.repo / "WORKFLOW.md").unlink()
    dry = box.run("init", "--dry-run")
    assert dry.returncode == 0 and "create WORKFLOW.md\n" in dry.stdout
    assert not (box.repo / "WORKFLOW.md").exists()
    res = box.run("init", stdin="")
    assert res.returncode == 0, res.stderr
    text = (box.repo / "WORKFLOW.md").read_text()
    assert "# validate:\n#   command: set your validation command here\n" in text
    bad = box.run("init", "--method", "nope")
    assert bad.returncode == 2 and "known methods: base" in bad.stderr
