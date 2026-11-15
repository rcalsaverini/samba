"""`FsProjectFiles`: the `ProjectFiles` port over a repository directory. The only rule is path
safety: nothing outside the repository is read or written."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from samba.app.ports import ProjectFilesError


class FsProjectFiles:
    def __init__(self, repo: Path) -> None:
        self._repo = repo

    def _target(self, path: str) -> Path:
        rel = PurePosixPath(path)
        if (not path or rel.is_absolute() or ".." in rel.parts or "\\" in path
                or Path(path).is_absolute()):
            raise ProjectFilesError(f"refusing path outside the repository: {path!r}")
        root = self._repo.resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise ProjectFilesError(f"refusing path outside the repository: {path!r}")
        return target

    def exists(self, path: str) -> bool:
        return self._target(path).exists()

    def write(self, path: str, text: str) -> None:
        target = self._target(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
