"""The ADR commands as use cases over the `Adrs` port (spec: cli, ADR commands). Plain record
edits: no config, no lock, no confirmation, never a commit."""

from __future__ import annotations

from samba.app.results import Refused, Table, Text, Written, refused, usage
from samba.ports import AdrError, Adrs


def _refusal(e: AdrError) -> Refused:
    return usage(str(e)) if e.code == 2 else refused(str(e))


class ListAdrs:
    def __init__(self, adrs: Adrs) -> None:
        self._adrs = adrs

    def run(self, show_all: bool) -> Table | Refused:
        try:
            adrs = self._adrs.load_all()
        except AdrError as e:
            return _refusal(e)
        if show_all:
            rows = [("NUMBER", "STATUS", "TITLE", "SUMMARY")] + [
                (f"{a.number:04d}", a.status, a.title, a.summary) for a in adrs]
        else:
            rows = [("NUMBER", "TITLE", "SUMMARY")] + [
                (f"{a.number:04d}", a.title, a.summary) for a in adrs if a.status == "accepted"]
        return Table(tuple(rows), flex=len(rows[0]) - 1)


class ShowAdr:
    def __init__(self, adrs: Adrs) -> None:
        self._adrs = adrs

    def run(self, number: str) -> Text | Refused:
        try:
            return Text(self._adrs.find(self._adrs.parse_number(number)).text)
        except AdrError as e:
            return _refusal(e)


class SetAdrStatus:
    """`accept` and `reject`: only from `proposed`."""

    def __init__(self, adrs: Adrs) -> None:
        self._adrs = adrs

    def run(self, verb: str, number: str) -> Written | Refused:
        status = "accepted" if verb == "accept" else "rejected"
        try:
            n = self._adrs.parse_number(number)
            return Written(tuple(self._adrs.set_status(n, verb, "proposed", status)))
        except AdrError as e:
            return _refusal(e)


class SupersedeAdr:
    def __init__(self, adrs: Adrs) -> None:
        self._adrs = adrs

    def run(self, number: str, new: str) -> Written | Refused:
        try:
            n = self._adrs.parse_number(number)
            return Written(tuple(self._adrs.supersede(n, self._adrs.parse_number(new))))
        except AdrError as e:
            return _refusal(e)
