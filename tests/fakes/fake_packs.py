"""Scripted `Packs` port: the packs are whatever the test gives."""

from __future__ import annotations


class FakePacks:
    def __init__(self, **packs: dict[str, str]) -> None:
        self.packs = packs

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.packs))

    def files(self, method: str) -> dict[str, str]:
        return dict(self.packs[method])
