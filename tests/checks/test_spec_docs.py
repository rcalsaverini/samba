"""Drift checks for the specification in docs/spec/. Reads files only; must not import samba."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
SPEC_DIR = ROOT / "docs" / "spec"
OLD_NAME = "SPEC" + ".md"  # built in pieces so this file does not match itself
OLD_REF = "SPEC" + " §"


def chapters() -> list[Path]:
    return sorted(p for p in SPEC_DIR.glob("*.md")
                  if p.name != "README.md" and not p.name.startswith("."))


def test_index_links_every_chapter_and_every_link_resolves() -> None:
    index = (SPEC_DIR / "README.md").read_text()
    links = re.findall(r"\]\(([^)#]+)\)", index)
    assert set(links) == {p.name for p in chapters()}
    for link in links:
        assert (SPEC_DIR / link).is_file(), link


def test_the_single_file_spec_is_gone() -> None:
    assert not (ROOT / OLD_NAME).exists()


def test_chapters_have_no_section_numbers() -> None:
    for chapter in chapters():
        assert "§" not in chapter.read_text(), chapter.name


def test_no_chapter_is_named_after_a_phase_or_a_version() -> None:
    pattern = re.compile(r"\bv\d|phase|\blater\b", re.I)
    for chapter in chapters():
        assert not pattern.search(chapter.stem), chapter.name
        heading = chapter.read_text().splitlines()[0]
        assert not pattern.search(heading), (chapter.name, heading)


def test_dissolved_chapters_are_gone_and_the_backlog_is_indexed() -> None:
    for name in ("later.md", "planning.md", "dependencies.md"):
        assert not (SPEC_DIR / name).exists(), name
    assert (SPEC_DIR / "backlog.md").is_file()
    assert "(backlog.md)" in (SPEC_DIR / "README.md").read_text()


def test_no_references_to_the_dissolved_chapters() -> None:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    pattern = re.compile(r"\b(planning|dependencies|later), [A-Z]|implementation-notes, Verified"
                         r"|spec: (planning|dependencies|later)\b")
    for name in out.stdout.splitlines():
        path = ROOT / name
        if name.startswith("docs/adr/") or path == Path(__file__) or not path.is_file():
            continue
        match = pattern.search(path.read_text(errors="ignore"))
        assert match is None, (name, match and match.group(0))


def test_verified_claude_code_behavior_lives_in_running_claude() -> None:
    heading = re.compile(r"^## Verified Claude Code behavior \(\d+\.\d+\.\d+, \d{4}-\d{2}-\d{2}\)$", re.M)
    assert heading.search((SPEC_DIR / "running-claude.md").read_text())
    assert "Verified Claude Code behavior" not in (SPEC_DIR / "implementation-notes.md").read_text()


def test_no_stale_references_outside_the_adrs() -> None:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    for name in out.stdout.splitlines():
        path = ROOT / name
        if name.startswith("docs/adr/") or path == Path(__file__) or not path.is_file():
            continue
        text = path.read_text(errors="ignore")
        assert OLD_NAME not in text and OLD_REF not in text, name
