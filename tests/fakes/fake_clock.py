"""In-memory `Clock`: time stands still at `now` unless a test moves it."""

from __future__ import annotations

FAKE_ISO = "2026-01-01T00:00:00+00:00"


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def time(self) -> float:
        return self.now

    def monotonic(self) -> float:
        return self.now

    def iso_seconds(self) -> str:
        return FAKE_ISO

    def log_stamp(self) -> str:
        return "2026-01-01 00:00"
