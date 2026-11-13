"""The user manual's text (spec: cli): completion is documented, and the docs keep the style rule."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_manual_documents_shell_completion() -> None:
    manual = (ROOT / "docs" / "manual.md").read_text()
    assert "--install-completion" in manual and "--show-completion" in manual


def test_the_readme_and_the_manual_have_no_em_dashes() -> None:
    for name in ("README.md", "docs/manual.md"):
        assert "—" not in (ROOT / name).read_text(), name
