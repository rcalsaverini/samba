"""Repository files that must agree with the code: the states chapter table, the WORKFLOW.md body."""

from __future__ import annotations

import re
from pathlib import Path

from samba.domain.transitions import TABLE_BEGIN, render_markdown_table

ROOT = Path(__file__).resolve().parents[2]


def norm(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in text.strip().splitlines()]


def test_the_states_chapter_embeds_the_table_the_code_renders() -> None:
    text = (ROOT / "docs" / "spec" / "states.md").read_text()
    end = TABLE_BEGIN.replace("begin", "end")
    assert TABLE_BEGIN in text and end in text
    block = text.split(TABLE_BEGIN, 1)[1].split(end, 1)[0]
    assert norm(block) == norm(render_markdown_table())


def test_the_repository_workflow_asks_agents_for_the_spec_step() -> None:
    text = (ROOT / "WORKFLOW.md").read_text()
    assert "Spec changes" in text
    assert "docs/spec" in text and "docs/adr" in text
