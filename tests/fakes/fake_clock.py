"""In-memory `Clock`: time stands still at `t` unless a test moves it."""

from __future__ import annotations

from samba.domain.now import Now

FAKE_ISO = "2026-01-01T00:00:00+00:00"
FAKE_STAMP = "2026-01-01 00:00"


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.t = now
        self.reads = 0
        """How many times `now()` was called (a use case reads it once per operation)."""

    def time(self) -> float:
        return self.t

    def monotonic(self) -> float:
        return self.t

    def now(self) -> Now:
        self.reads += 1
        return Now(self.t, FAKE_ISO, FAKE_STAMP)
