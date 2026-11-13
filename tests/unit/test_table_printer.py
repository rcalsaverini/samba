"""The table printer of the command line (spec: cli, observability): widths and the cut column."""

from __future__ import annotations

import pytest

from samba.entrypoints.table import MIN_FLEX, print_table

ROWS = (("ID", "STATE", "ERROR"),
        ("t1", "stuck", "the validation command failed after the merge with a very long message"),
        ("t22", "work-todo", ""))


def lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return capsys.readouterr().out.splitlines()


def test_columns_are_left_aligned_two_spaces_apart_and_trailing_space_is_dropped(
        capsys: pytest.CaptureFixture[str]) -> None:
    print_table((("A", "BB"), ("ccc", "d")))
    assert lines(capsys) == ["A    BB", "ccc  d"]


def test_a_narrow_terminal_cuts_only_the_flex_column_with_dots(
        capsys: pytest.CaptureFixture[str]) -> None:
    print_table(ROWS, width=50, flex=2)
    out = lines(capsys)
    assert all(len(line) <= 50 for line in out), out
    assert out[1].startswith("t1   stuck      ") and out[1].endswith("...")
    assert out[2].startswith("t22  work-todo")  # other columns are never cut


def test_a_wide_terminal_shows_the_whole_flex_column(capsys: pytest.CaptureFixture[str]) -> None:
    print_table(ROWS, width=200, flex=2)
    assert lines(capsys)[1].endswith("with a very long message")


def test_the_flex_column_keeps_a_minimum_width_on_a_tiny_terminal(
        capsys: pytest.CaptureFixture[str]) -> None:
    print_table(ROWS, width=10, flex=2)
    cut = lines(capsys)[1].split("  ")[-1]
    assert len(cut) == MIN_FLEX and cut.endswith("...")
