"""`Now`: one instant, as a value (ADR 0017). The domain takes this, never a clock.

The adapter preformats the two texts, so the domain imports no `datetime`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Now:
    time: float
    """Wall-clock time, seconds since the epoch."""
    iso_seconds: str
    """`time` as local-offset ISO 8601 text, to the second (question timestamps)."""
    log_stamp: str
    """`time` as local `YYYY-MM-DD HH:MM` text (`## Log` lines)."""
