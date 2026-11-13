"""The `Adrs` port: the contract run against `FakeAdrs` and `FileAdrs`, then what only the files
show (spec: cli, ADR commands; ADR 0001 format)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fake_adrs import FakeAdrs

from samba.adapters.adr_files import FileAdrs
from samba.domain.ports import AdrError, AdrInfo, Adrs

STATUSES = {1: "accepted", 2: "proposed", 3: "rejected", 4: "proposed"}


def adr_text(number: int, status: str, decision: str | None = None,
             supersedes: str = "[]") -> str:
    decision = decision if decision is not None else f"- Decision {number} is made. More."
    return (f"---\nstatus: {status}\ndate: 2026-11-08\nsupersedes: {supersedes}\n---\n\n"
            f"# {number:04d}: Title {number}\n\n## Context\n\nWhy.\n\n## Decision\n\n{decision}\n\n"
            "## Consequences\n\n- Some.\n")


def write(repo: Path, number: int, status: str, **kw: str) -> Path:
    d = repo / "docs" / "adr"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{number:04d}-title-{number}.md"
    p.write_text(adr_text(number, status, **kw))
    return p


@pytest.fixture(params=["fake", "files"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Adrs:
    if request.param == "fake":
        return FakeAdrs(*(AdrInfo(n, f"docs/adr/{n:04d}.md", s, f"Title {n}", "S.", "text")
                          for n, s in STATUSES.items()))
    for n, s in STATUSES.items():
        write(tmp_path, n, s)
    return FileAdrs(tmp_path)


def code(e: pytest.ExceptionInfo[AdrError]) -> int:
    return e.value.code


# ---- the contract ------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["3", "03", "0003"])
def test_number_forms_name_the_same_adr(store: Adrs, text: str) -> None:
    assert store.parse_number(text) == 3


def test_a_non_number_is_a_usage_error(store: Adrs) -> None:
    with pytest.raises(AdrError) as e:
        store.parse_number("three")
    assert code(e) == 2


def test_every_adr_is_listed_in_number_order(store: Adrs) -> None:
    assert [(a.number, a.status) for a in store.load_all()] == sorted(STATUSES.items())


def test_an_unknown_adr_is_a_usage_error(store: Adrs) -> None:
    with pytest.raises(AdrError) as e:
        store.find(9)
    assert code(e) == 2


def test_accept_changes_a_proposed_adr_and_refuses_any_other(store: Adrs) -> None:
    assert len(store.set_status(2, "accept", "proposed", "accepted")) == 1
    assert store.find(2).status == "accepted"
    for number in (1, 2, 3):  # accepted, now accepted, rejected
        with pytest.raises(AdrError) as e:
            store.set_status(number, "accept", "proposed", "accepted")
        assert code(e) == 1
    assert store.find(3).status == "rejected"


def test_supersede_marks_the_old_one(store: Adrs) -> None:
    assert len(store.supersede(1, 2)) == 2
    assert store.find(1).status == "superseded"


@pytest.mark.parametrize("old, new, want", [(1, 1, 2), (2, 4, 1), (1, 3, 1)])
def test_illegal_supersedes_are_refused_and_change_nothing(store: Adrs, old: int, new: int,
                                                          want: int) -> None:
    before = [(a.number, a.status) for a in store.load_all()]
    with pytest.raises(AdrError) as e:
        store.supersede(old, new)  # itself; the old one not accepted; the new one rejected
    assert code(e) == want
    assert [(a.number, a.status) for a in store.load_all()] == before


# ---- only the files ----------------------------------------------------------------------------

def test_accept_and_reject_rewrite_only_the_status_line(tmp_path: Path) -> None:
    p1, p2 = write(tmp_path, 1, "proposed"), write(tmp_path, 2, "proposed")
    old1, old2 = p1.read_text(), p2.read_text()
    store = FileAdrs(tmp_path)
    assert store.set_status(1, "accept", "proposed", "accepted") == [str(p1)]
    assert store.set_status(2, "reject", "proposed", "rejected") == [str(p2)]
    assert p1.read_text() == old1.replace("status: proposed", "status: accepted")
    assert p2.read_text() == old2.replace("status: proposed", "status: rejected")


def test_supersede_lists_the_old_number_in_the_new_files_front_matter(tmp_path: Path) -> None:
    old = write(tmp_path, 1, "accepted")
    new = write(tmp_path, 2, "accepted", supersedes="[7]")
    FileAdrs(tmp_path).supersede(1, 2)
    assert "status: superseded" in old.read_text()
    assert "supersedes: [7, 1]" in new.read_text()


def test_show_returns_the_file_verbatim_for_any_status(tmp_path: Path) -> None:
    for number, status in STATUSES.items():
        p = write(tmp_path, number, status)
        assert FileAdrs(tmp_path).find(number).text == p.read_text()


def test_the_summary_is_the_first_sentence_of_the_decision(tmp_path: Path) -> None:
    write(tmp_path, 1, "accepted", decision="- A decision that wraps\n  over two lines. Then more.")
    write(tmp_path, 2, "accepted", decision="Plain paragraph without a bullet. And more.")
    write(tmp_path, 3, "accepted", decision="- Only one bullet\n- Another bullet.")
    summaries = [a.summary for a in FileAdrs(tmp_path).load_all()]
    assert summaries == ["A decision that wraps over two lines.",
                         "Plain paragraph without a bullet.", "Only one bullet"]


def test_a_file_without_front_matter_is_an_error_naming_it(tmp_path: Path) -> None:
    d = tmp_path / "docs" / "adr"
    d.mkdir(parents=True)
    (d / "0001-bare.md").write_text("# 0001: Bare\n\nNo front matter.\n")
    store = FileAdrs(tmp_path)
    for call in (store.load_all, lambda: store.find(1),
                 lambda: store.set_status(1, "accept", "proposed", "accepted")):
        with pytest.raises(AdrError) as e:
            call()
        assert code(e) == 1 and "front matter" in str(e.value)


def test_no_adr_folder_is_an_empty_list(tmp_path: Path) -> None:
    assert FileAdrs(tmp_path).load_all() == []
