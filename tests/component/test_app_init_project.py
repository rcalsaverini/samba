"""`InitProject` and `CompleteMethods` over the in-memory fakes (spec: cli, init; packs)."""

from __future__ import annotations

from fake_clock import FakeClock
from fake_packs import FakePacks
from fake_project_files import FakeProjectFiles
from fake_terminal import FakeTerminal

from samba.app.completion import CompleteMethods
from samba.app.init_project import DEFAULT_METHOD, InitProject
from samba.app.results import Refused, Text, Written

WORKFLOW = "---\n@@VALIDATE@@\n---\nTask: {{ task.title }}\n"
ADR = "---\nstatus: accepted\ndate: @@DATE@@\n---\n"


def base_pack() -> dict[str, str]:
    return {"WORKFLOW.md": WORKFLOW, "CLAUDE.md": "# Project\n", "docs/adr/0000-x.md": ADR}


class Rig:
    def __init__(self, existing: dict[str, str] | None = None, interactive: bool = False,
                 lines: list[str] | None = None, **packs: dict[str, str]) -> None:
        self.packs = FakePacks(**(packs or {"base": base_pack()}))
        self.files = FakeProjectFiles(existing)
        self.terminal = FakeTerminal(interactive=interactive, lines=lines)
        self.clock = FakeClock()
        self.uc = InitProject(self.packs, self.files, self.terminal, self.clock)


def test_the_default_method_is_base() -> None:
    assert DEFAULT_METHOD == "base"


def test_missing_files_are_written_with_the_markers_filled() -> None:
    rig = Rig()
    res = rig.uc.run(None, "make check", dry_run=False)
    assert res == Written(("CLAUDE.md", "WORKFLOW.md", "docs/adr/0000-x.md"))
    assert rig.files.files["docs/adr/0000-x.md"] == "---\nstatus: accepted\ndate: 2026-01-01\n---\n"
    assert 'command: "make check"' in rig.files.files["WORKFLOW.md"]
    assert "{{ task.title }}" in rig.files.files["WORKFLOW.md"]
    assert rig.clock.reads == 1


def test_existing_files_are_skipped_and_reported_in_notes() -> None:
    rig = Rig(existing={"CLAUDE.md": "mine"})
    res = rig.uc.run(None, None, dry_run=False)
    assert res == Written(("WORKFLOW.md", "docs/adr/0000-x.md"), ("skip CLAUDE.md (exists)",))
    assert rig.files.files["CLAUDE.md"] == "mine"


def test_the_method_overlays_base_and_wins() -> None:
    rig = Rig(base=base_pack(), other={"CLAUDE.md": "# Other\n", "extra.md": "x"})
    res = rig.uc.run("other", None, dry_run=False)
    assert isinstance(res, Written)
    assert res.files == ("CLAUDE.md", "WORKFLOW.md", "docs/adr/0000-x.md", "extra.md")
    assert rig.files.files["CLAUDE.md"] == "# Other\n"
    assert "Task:" in rig.files.files["WORKFLOW.md"]


def test_dry_run_lists_the_plan_writes_nothing_and_asks_nothing() -> None:
    rig = Rig(existing={"CLAUDE.md": "mine"}, interactive=True)
    res = rig.uc.run(None, None, dry_run=True)
    assert res == Text("skip CLAUDE.md (exists)\ncreate WORKFLOW.md\ncreate docs/adr/0000-x.md\n")
    assert rig.files.writes == [] and rig.terminal.prompts == [] and rig.clock.reads == 0


def test_an_unknown_method_is_a_usage_refusal_naming_the_known_ones() -> None:
    rig = Rig(base=base_pack(), other={})
    res = rig.uc.run("nope", None, dry_run=False)
    assert res == Refused("usage", ("samba: unknown method 'nope'; known methods: base, other",))
    assert rig.files.writes == []


def test_a_given_command_is_not_asked_for() -> None:
    rig = Rig(interactive=True)
    rig.uc.run(None, "true", dry_run=False)
    assert rig.terminal.prompts == []


def test_on_a_terminal_the_command_is_asked_once() -> None:
    rig = Rig(interactive=True, lines=["  pytest -q "])
    rig.uc.run(None, None, dry_run=False)
    assert len(rig.terminal.prompts) == 1
    assert 'command: "pytest -q"' in rig.files.files["WORKFLOW.md"]


def test_an_empty_answer_or_end_of_input_skips_validation() -> None:
    for lines in ([""], []):
        rig = Rig(interactive=True, lines=lines)
        rig.uc.run(None, None, dry_run=False)
        assert "# validate:" in rig.files.files["WORKFLOW.md"]


def test_without_a_terminal_validation_is_skipped_silently() -> None:
    rig = Rig(interactive=False)
    rig.uc.run(None, None, dry_run=False)
    assert rig.terminal.prompts == []
    assert "#   command: set your validation command here" in rig.files.files["WORKFLOW.md"]


def test_a_path_that_escapes_the_repository_is_refused() -> None:
    for bad in ("../evil.md", "/etc/evil", "a/../../evil"):
        rig = Rig(base={"ok.md": "x", bad: "y"})
        res = rig.uc.run(None, None, dry_run=False)
        assert isinstance(res, Refused) and res.kind == "refused"
        assert "outside the repository" in res.messages[0]
        assert rig.files.writes == []


def test_complete_methods_filters_by_prefix() -> None:
    complete = CompleteMethods(FakePacks(base=base_pack(), ddd={"a": "x"}))
    assert complete.run("") == [("base", "method pack, 3 files"), ("ddd", "method pack, 1 files")]
    assert [name for name, _ in complete.run("d")] == ["ddd"]
