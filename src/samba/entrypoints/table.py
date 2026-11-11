"""Terminal output helpers for the CLI entry point (spec: cli, observability): the table printer."""

from __future__ import annotations

from collections.abc import Sequence

__all__ = ["print_table"]

MIN_FLEX = 20


def print_table(rows: Sequence[Sequence[str]], width: int | None = None,
                flex: int | None = None) -> None:
    """Print left-aligned columns separated by two spaces. With `flex` (a column index), that
    column gets the room left in `width` and longer cells are cut with `...`; other columns are
    never cut. The flex column is at least MIN_FLEX wide."""
    table = [list(r) for r in rows]
    widths = [max(len(r[i]) for r in table) for i in range(len(table[0]))]
    if flex is not None and width is not None:
        used = sum(w + 2 for i, w in enumerate(widths) if i != flex)
        room = max(width - used, MIN_FLEX)
        if widths[flex] > room:
            widths[flex] = room
            table = [r[:flex] + [r[flex] if len(r[flex]) <= room else r[flex][:room - 3] + "..."]
                     + r[flex + 1:] for r in table]
    for r in table:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
