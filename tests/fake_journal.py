"""In-memory `Journal`: records `(level, event, fields)`."""

from __future__ import annotations


class FakeJournal:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict[str, object]]] = []

    def debug(self, event: str, **fields: object) -> None:
        self.records.append(("debug", event, fields))

    def info(self, event: str, **fields: object) -> None:
        self.records.append(("info", event, fields))

    def warning(self, event: str, **fields: object) -> None:
        self.records.append(("warning", event, fields))

    def exception(self, event: str, **fields: object) -> None:
        self.records.append(("error", event, fields))

    def events(self, level: str | None = None) -> list[str]:
        return [e for lv, e, _ in self.records if level is None or lv == level]
