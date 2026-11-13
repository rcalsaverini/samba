"""In-memory `IdGenerator`: session ids count up ("s1", "s2", ...)."""

from __future__ import annotations


class FakeIds:
    def __init__(self) -> None:
        self.n = 0

    def new_session_id(self) -> str:
        self.n += 1
        return f"s{self.n}"
