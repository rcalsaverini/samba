"""The end-to-end level stays small and says why each test is there (ADR 0016).

A new behavior gets an end-to-end test only when the whole process is the only place it shows. The
budget counts test functions (parametrized cases share one); raise it only with a reason in the
commit, and prefer moving a test down a level.
"""

from __future__ import annotations

import ast
from pathlib import Path

E2E = Path(__file__).resolve().parents[1] / "e2e"
BUDGET = 30


def e2e_tests() -> list[tuple[str, ast.FunctionDef]]:
    found: list[tuple[str, ast.FunctionDef]] = []
    for path in sorted(E2E.glob("test_*.py")):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                found.append((path.name, node))
    return found


def test_the_end_to_end_level_stays_within_its_budget() -> None:
    tests = e2e_tests()
    assert 0 < len(tests) <= BUDGET, f"{len(tests)} end-to-end tests, budget {BUDGET}"


def test_every_end_to_end_test_says_what_only_its_level_shows() -> None:
    missing = [f"{file}::{fn.name}" for file, fn in e2e_tests() if not ast.get_docstring(fn)]
    assert missing == []
