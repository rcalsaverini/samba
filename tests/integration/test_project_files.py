"""The `ProjectFiles` port: the contract run against `FakeProjectFiles` and `FsProjectFiles`, then
what only the file system shows (parent directories, symlinks)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fake_project_files import FakeProjectFiles

from samba.adapters.project_files import FsProjectFiles
from samba.app.ports import ProjectFiles, ProjectFilesError


@pytest.fixture(params=["fake", "fs"])
def files(request: pytest.FixtureRequest, tmp_path: Path) -> ProjectFiles:
    if request.param == "fake":
        return FakeProjectFiles()
    return FsProjectFiles(tmp_path / "repo")


def test_a_written_file_exists_and_a_missing_one_does_not(files: ProjectFiles) -> None:
    assert not files.exists("docs/adr/0000-x.md")
    files.write("docs/adr/0000-x.md", "text")
    assert files.exists("docs/adr/0000-x.md")
    assert not files.exists("docs/adr/0001-x.md")


@pytest.mark.parametrize("path", ["../evil.md", "a/../../evil.md", "/etc/evil", "", "a\\..\\b"])
def test_paths_outside_the_repository_are_refused(files: ProjectFiles, path: str) -> None:
    with pytest.raises(ProjectFilesError):
        files.exists(path)
    with pytest.raises(ProjectFilesError):
        files.write(path, "x")


def test_the_real_adapter_creates_parents_and_writes_utf8(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    FsProjectFiles(repo).write("a/b/c.md", "olá\n")
    assert (repo / "a" / "b" / "c.md").read_text(encoding="utf-8") == "olá\n"


def test_nothing_is_written_outside_the_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(ProjectFilesError):
        FsProjectFiles(repo).write("../evil.md", "x")
    assert not (tmp_path / "evil.md").exists()


def test_a_symlink_that_leaves_the_repository_is_refused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ProjectFilesError):
        FsProjectFiles(repo).write("link/evil.md", "x")
    assert not (outside / "evil.md").exists()
