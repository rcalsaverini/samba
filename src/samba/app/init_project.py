"""`InitProject`: `samba init` (spec: cli, init; packs). Writes the files of a method pack into
the repository: never overwrites, never commits, needs no config."""

from __future__ import annotations

from samba.app.ports import Clock, Packs, ProjectFiles, ProjectFilesError, Terminal
from samba.app.results import Refused, Text, Written, refused, usage
from samba.domain.pack_markers import fill_markers

DEFAULT_METHOD = "base"
BASE_METHOD = "base"
VALIDATE_PROMPT = "Validation command (empty to skip): "


class InitProject:
    def __init__(self, packs: Packs, files: ProjectFiles, terminal: Terminal,
                 clock: Clock) -> None:
        self._packs = packs
        self._files = files
        self._terminal = terminal
        self._clock = clock

    def _merged(self, method: str) -> dict[str, str]:
        """The files of `base`, overlaid by those of `method` (the method wins)."""
        merged: dict[str, str] = {}
        for name in dict.fromkeys((BASE_METHOD, method)):
            if name in self._packs.names():
                merged.update(self._packs.files(name))
        return merged

    def _command(self, given: str | None) -> str | None:
        """The validation command: the flag, else one question on a terminal, else none."""
        if given is None and self._terminal.is_interactive():
            try:
                given = self._terminal.ask(VALIDATE_PROMPT)
            except EOFError:
                given = None
        return given.strip() or None if given is not None else None

    def run(self, method: str | None, validate: str | None,
            dry_run: bool) -> Written | Text | Refused:
        name = method or DEFAULT_METHOD
        known = self._packs.names()
        if name not in known:
            return usage(f"unknown method {name!r}; known methods: {', '.join(known)}")
        files = self._merged(name)
        try:
            plan = [(path, self._files.exists(path)) for path in sorted(files)]
        except ProjectFilesError as e:
            return refused(f"{e}; nothing written")
        if dry_run:
            return Text("".join(f"skip {p} (exists)\n" if found else f"create {p}\n"
                                for p, found in plan))
        command = self._command(validate)
        date = self._clock.now().log_stamp.split(" ")[0]
        created: list[str] = []
        notes: list[str] = []
        for path, found in plan:
            if found:
                notes.append(f"skip {path} (exists)")
                continue
            try:
                self._files.write(path, fill_markers(files[path], date, command))
            except ProjectFilesError as e:
                return refused(f"{e}; stopped after {len(created)} file(s)")
            created.append(path)
        return Written(tuple(created), tuple(notes))
