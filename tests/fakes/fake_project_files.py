"""In-memory `ProjectFiles` port, with the path rules of the real adapter.

`tests/integration/test_project_files.py` runs the port's contract against this fake and
`FsProjectFiles`.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from samba.app.ports import ProjectFilesError


class FakeProjectFiles:
    def __init__(self, existing: dict[str, str] | None = None) -> None:
        self.files: dict[str, str] = dict(existing or {})
        self.writes: list[str] = []

    def _check(self, path: str) -> None:
        rel = PurePosixPath(path)
        if not path or rel.is_absolute() or ".." in rel.parts or "\\" in path:
            raise ProjectFilesError(f"refusing path outside the repository: {path!r}")

    def exists(self, path: str) -> bool:
        self._check(path)
        return path in self.files

    def write(self, path: str, text: str) -> None:
        self._check(path)
        self.files[path] = text
        self.writes.append(path)
