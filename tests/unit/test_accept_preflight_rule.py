"""`preflight_problem`: the rule that decides whether `work accept` may start."""

from __future__ import annotations

from samba.app.accept_work import preflight_problem
from samba.app.ports import Preflight


def problem(facts: Preflight) -> str | None:
    return preflight_problem(facts, "samba/x", "main")


def test_all_good_facts_have_no_problem() -> None:
    assert problem(Preflight("main", False, True)) is None


def test_another_branch_refuses() -> None:
    assert problem(Preflight("other", False, True)) == (
        "the main checkout is on other, not the base branch main")


def test_a_detached_head_refuses() -> None:
    assert problem(Preflight(None, False, True)) == (
        "the main checkout is on a detached HEAD, not the base branch main")


def test_tracked_changes_refuse() -> None:
    assert problem(Preflight("main", True, True)) == (
        "the main checkout has uncommitted changes to tracked files")


def test_a_missing_branch_refuses() -> None:
    assert problem(Preflight("main", False, False)) == "branch samba/x does not exist"


def test_the_first_failed_check_wins() -> None:
    assert problem(Preflight("other", True, False)) == (
        "the main checkout is on other, not the base branch main")
