"""`PackagePacks`: the `Packs` port over the package data in `samba/packs/<name>/`."""

from __future__ import annotations

from importlib.resources import files
from importlib.resources.abc import Traversable

SKIPPED = {"__pycache__"}


class PackagePacks:
    def _root(self) -> Traversable:
        return files("samba").joinpath("packs")

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(p.name for p in self._root().iterdir()
                            if p.is_dir() and p.name not in SKIPPED))

    def files(self, method: str) -> dict[str, str]:
        if method not in self.names():
            raise KeyError(method)
        found: dict[str, str] = {}
        _walk(self._root().joinpath(method), "", found)
        return found


def _walk(directory: Traversable, prefix: str, found: dict[str, str]) -> None:
    for entry in sorted(directory.iterdir(), key=lambda e: e.name):
        if entry.name in SKIPPED:
            continue
        path = f"{prefix}{entry.name}"
        if entry.is_dir():
            _walk(entry, f"{path}/", found)
        else:
            found[path] = entry.read_text(encoding="utf-8")
