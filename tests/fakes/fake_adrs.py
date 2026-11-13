"""In-memory `Adrs` port: ADR records by number, with the status rules of the real store."""

from __future__ import annotations

from samba.domain.ports import AdrError, AdrInfo


class FakeAdrs:
    def __init__(self, *adrs: AdrInfo) -> None:
        self.adrs = {a.number: a for a in adrs}
        self.calls: list[tuple[object, ...]] = []

    def parse_number(self, text: str) -> int:
        if not text.isdigit():
            raise AdrError(f"not an ADR number: {text!r}", 2)
        return int(text)

    def load_all(self) -> list[AdrInfo]:
        return [self.adrs[n] for n in sorted(self.adrs)]

    def find(self, number: int) -> AdrInfo:
        if number not in self.adrs:
            raise AdrError(f"unknown ADR {number:04d}", 2)
        return self.adrs[number]

    def set_status(self, number: int, verb: str, allowed_from: str, status: str) -> list[str]:
        adr = self.find(number)
        if adr.status != allowed_from:
            raise AdrError(f"ADR {number:04d} is {adr.status}; {verb} not allowed", 1)
        self.calls.append(("set_status", number, verb, status))
        return [adr.file]

    def supersede(self, old: int, new: int) -> list[str]:
        self.calls.append(("supersede", old, new))
        return [self.find(old).file, self.find(new).file]
