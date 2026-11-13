"""Temporary check of the test migration (ADR 0016): every legacy test is accounted for.

`tests/migration/inventory.json` lists one entry per top-level test function in `tests/legacy/`
with the behavior it checks, the level it belongs to, and whether a new test covers it. Removed at
the end of the migration together with `tests/legacy/` and `tests/migration/`. Reads files only.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import cast

TESTS = Path(__file__).resolve().parents[1]
INVENTORY = TESTS / "migration" / "inventory.json"
LEGACY = TESTS / "legacy"

LEVELS = {"unit", "component", "integration", "e2e"}
AREAS = {"core", "commands", "e2e", "int-tasks", "int-lock", "int-journal", "int-validator",
         "int-terminal", "int-vcs", "int-agent", "int-session", "int-adrs", "int-config"}
STATUSES = {"todo", "covered", "dropped"}

Entry = dict[str, object]


def functions_of(path: Path) -> set[str]:
    """Names of the test functions in a file: top level, and methods of top-level classes."""
    names: set[str] = set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            names.update(n.name for n in node.body
                         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and n.name.startswith("test_"))
    return names


def legacy_ids() -> set[str]:
    return {f"{f.name}::{name}" for f in LEGACY.glob("test_*.py") for name in functions_of(f)}


def entries() -> list[Entry]:
    return cast(list[Entry], json.loads(INVENTORY.read_text()))


def new_test_exists(ref: str) -> bool:
    """`tests/<level>/<file>.py::<function>` (optionally `[case]`) names a test that exists."""
    file, sep, name = ref.partition("::")
    path = TESTS.parent / file
    base = name.split("[", 1)[0]
    folder = file.split("/")[1] if file.count("/") >= 2 else ""
    return bool(sep) and path.is_file() and folder in LEVELS | {"checks"} and base in functions_of(path)


def test_every_legacy_test_is_in_the_inventory_once() -> None:
    ids = [cast(str, e["id"]) for e in entries()]
    assert len(ids) == len(set(ids)), "duplicate inventory ids"
    assert set(ids) == legacy_ids(), (
        f"missing: {sorted(legacy_ids() - set(ids))}, unknown: {sorted(set(ids) - legacy_ids())}")


def test_entries_are_well_formed() -> None:
    for e in entries():
        where = e["id"]
        assert e["target"] in LEVELS, where
        assert e["area"] in AREAS, where
        assert e["status"] in STATUSES, where
        assert cast(str, e["behavior"]).strip(), where
        covered_by = cast(list[str], e.get("covered_by", []))
        if e["status"] == "covered":
            assert covered_by, f"{where}: covered by nothing"
            missing = [ref for ref in covered_by if not new_test_exists(ref)]
            assert not missing, f"{where}: unknown tests {missing}"
        if e["status"] == "dropped":
            assert cast(str, e.get("reason", "")).strip(), f"{where}: dropped without a reason"


def test_the_reference_check_tells_real_tests_from_unknown_ones() -> None:
    real = sorted(functions_of(TESTS / "unit" / "test_task_domain.py"))[0]
    assert new_test_exists(f"tests/unit/test_task_domain.py::{real}")
    assert not new_test_exists("tests/unit/test_task_domain.py::test_no_such_test")
    assert not new_test_exists("tests/component/test_nope.py::test_x")
    legacy = sorted(legacy_ids())[0].replace("::", "::", 1)
    assert not new_test_exists(f"tests/legacy/{legacy}"), "a legacy test never covers an entry"
