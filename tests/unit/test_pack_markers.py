"""The marker filling of method packs: pure text in, text out (spec: packs, Markers)."""

from __future__ import annotations

import yaml

from samba.domain.pack_markers import fill_markers

FRONT = "---\nmax_turns: 15\n@@VALIDATE@@\n---\nTask: {{ task.title }}\n"


def test_the_date_marker_is_replaced_everywhere() -> None:
    text = "date: @@DATE@@\nagain @@DATE@@\n"
    assert fill_markers(text, "2026-11-14", None) == "date: 2026-11-14\nagain 2026-11-14\n"


def test_the_validate_marker_becomes_a_quoted_command() -> None:
    out = fill_markers(FRONT, "2026-11-14", "make check")
    assert "validate:\n  command: \"make check\"\n" in out
    assert "@@VALIDATE@@" not in out


def test_no_command_gives_the_commented_form() -> None:
    out = fill_markers(FRONT, "2026-11-14", None)
    assert ("# validate:\n#   command: set your validation command here\n") in out
    front = yaml.safe_load(out.split("---\n")[1])
    assert front == {"max_turns": 15}


def test_a_command_with_quotes_and_colons_is_valid_yaml() -> None:
    command = 'echo "a: b" && pytest -k \'x: y\' # not a comment'
    out = fill_markers(FRONT, "2026-11-14", command)
    front = yaml.safe_load(out.split("---\n")[1])
    assert front["validate"] == {"command": command}


def test_everything_else_is_copied_untouched() -> None:
    out = fill_markers(FRONT, "2026-11-14", None)
    assert out.endswith("---\nTask: {{ task.title }}\n")
    text = "no markers {{ task.body }} @@OTHER@@ inline @@VALIDATE@@ text\n"
    assert fill_markers(text, "2026-11-14", "x") == text

