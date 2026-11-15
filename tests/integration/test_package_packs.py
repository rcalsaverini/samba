"""`PackagePacks` over the shipped `samba/packs/` and what the `base` pack must be when it is
loaded by the real readers (spec: packs)."""

from __future__ import annotations

from pathlib import Path

from samba.adapters.adr_files import FileAdrs
from samba.adapters.package_packs import PackagePacks
from samba.adapters.workflow_file import load_config
from samba.domain.pack_markers import fill_markers
from samba.domain.validation import NO_VALIDATION_WARNING


def test_the_base_pack_is_shipped_with_its_files() -> None:
    packs = PackagePacks()
    assert "base" in packs.names()
    files = packs.files("base")
    assert set(files) == {"WORKFLOW.md", "CLAUDE.md", "docs/adr/0000-record-architecture-decisions.md",
                          "docs/spec/README.md"}
    assert all(text.strip() for text in files.values())


def test_no_shipped_file_has_an_em_dash() -> None:
    packs = PackagePacks()
    for name in packs.names():
        for path, text in packs.files(name).items():
            assert chr(0x2014) not in text, f"{name}/{path}"


def test_an_unknown_pack_is_a_key_error() -> None:
    try:
        PackagePacks().files("nope")
    except KeyError:
        return
    raise AssertionError("expected KeyError")


def test_the_shipped_workflow_loads_with_and_without_a_validate_command(tmp_path: Path) -> None:
    text = PackagePacks().files("base")["WORKFLOW.md"]
    (tmp_path / "WORKFLOW.md").write_text(fill_markers(text, "2026-11-14", None))
    loaded = load_config(tmp_path)
    assert loaded.config.validate_command is None
    assert loaded.config.warnings == [NO_VALIDATION_WARNING]
    assert loaded.config.policy.max_turns == 15 and loaded.claude.model == "sonnet"
    assert "{{ task.title }}" in loaded.config.prompts.template
    (tmp_path / "WORKFLOW.md").write_text(fill_markers(text, "2026-11-14", 'pytest -k "a: b"'))
    loaded = load_config(tmp_path)
    assert loaded.config.validate_command == 'pytest -k "a: b"'
    assert loaded.config.warnings == []


def test_the_shipped_adr_zero_is_read_as_accepted(tmp_path: Path) -> None:
    for path, text in PackagePacks().files("base").items():
        if path.startswith("docs/adr/"):
            target = tmp_path / path
            target.parent.mkdir(parents=True)
            target.write_text(fill_markers(text, "2026-11-14", None))
    (adr,) = FileAdrs(tmp_path).load_all()
    assert adr.number == 0 and adr.status == "accepted"
    assert adr.title == "Record architecture decisions"
    assert adr.summary
