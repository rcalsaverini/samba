"""Drift checks for the specification in docs/spec/. Reads files only; must not import samba."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
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


def test_no_stale_references_outside_the_adrs() -> None:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    for name in out.stdout.splitlines():
        path = ROOT / name
        if name.startswith("docs/adr/") or path == Path(__file__) or not path.is_file():
            continue
        text = path.read_text(errors="ignore")
        assert OLD_NAME not in text and OLD_REF not in text, name
