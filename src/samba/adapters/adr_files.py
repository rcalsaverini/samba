"""`FileAdrs`: the `Adrs` port over the ADR files under `docs/adr/` (wraps `samba.adr`)."""

from __future__ import annotations

from pathlib import Path

from samba import adr
from samba.ports import AdrInfo


class FileAdrs:
    def __init__(self, repo: Path) -> None:
        self._repo = repo

    def parse_number(self, text: str) -> int:
        return adr.parse_number(text)

    def load_all(self) -> list[AdrInfo]:
        return [_info(a) for a in adr.load_all(self._repo)]

    def find(self, number: int) -> AdrInfo:
        return _info(adr.find(self._repo, number))

    def set_status(self, number: int, verb: str, allowed_from: str, status: str) -> list[str]:
        return [str(p) for p in adr.set_status(self._repo, number, verb, allowed_from, status)]

    def supersede(self, old: int, new: int) -> list[str]:
        return [str(p) for p in adr.supersede(self._repo, old, new)]


def _info(a: adr.Adr) -> AdrInfo:
    return AdrInfo(a.number, str(a.path), a.status, a.title, a.summary, a.text)
