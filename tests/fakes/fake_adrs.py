"""In-memory `Adrs` port: ADR records by number, with the status rules of the real store.

`tests/integration/test_adr_store.py` runs the port's contract against this fake and `FileAdrs`.
"""

from __future__ import annotations

from dataclasses import replace

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
        self.adrs[number] = replace(adr, status=status)
        return [adr.file]

    def supersede(self, old: int, new: int) -> list[str]:
        if old == new:
            raise AdrError("an ADR cannot supersede itself", 2)
        old_adr, new_adr = self.find(old), self.find(new)
        if old_adr.status != "accepted":
            raise AdrError(f"ADR {old:04d} is {old_adr.status}; supersede not allowed", 1)
        if new_adr.status not in ("proposed", "accepted"):
            raise AdrError(f"ADR {new:04d} is {new_adr.status}; it cannot supersede", 1)
        self.calls.append(("supersede", old, new))
        self.adrs[old] = replace(old_adr, status="superseded")
        return [old_adr.file, new_adr.file]
