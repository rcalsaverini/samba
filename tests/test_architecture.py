"""Architecture guard: the dependency rule of docs/spec/architecture.md.

Reads source files with `ast`; never imports samba.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "samba"

# Modules that belong to the pure domain, relative to src/samba. Later tasks of the refactor
# chain append to this list as they move modules in.
DOMAIN_MODULES = ["ports.py", "template.py", "prompts.py", "deps.py"]

FORBIDDEN = {"os", "time", "datetime", "uuid", "subprocess", "asyncio", "logging", "pathlib"}


def imported_modules(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level == 0:
                names.append(base)
                if base == "samba":  # `from samba import adapters`
                    names.extend(f"samba.{a.name}" for a in node.names)
    return names


def test_domain_modules_exist() -> None:
    for rel in DOMAIN_MODULES:
        assert (SRC / rel).is_file(), f"{rel} is listed as domain but does not exist"


def test_domain_modules_import_no_io_and_no_adapter() -> None:
    for rel in DOMAIN_MODULES:
        for name in imported_modules(SRC / rel):
            top = name.split(".")[0]
            assert top not in FORBIDDEN, f"{rel} imports {name}"
            assert not (name == "samba.adapters" or name.startswith("samba.adapters.")), \
                f"{rel} imports adapter {name}"


def code_without_comments(path: Path) -> str:
    return "\n".join(line.split("#", 1)[0] for line in path.read_text().splitlines())


def test_no_direct_clock_or_uuid_calls() -> None:
    pattern = re.compile(r"\btime\.(time|monotonic)\(|\bdatetime\.now\(|\buuid\.")
    for rel in ["orchestrator.py", "transitions.py"]:
        hits = pattern.findall(code_without_comments(SRC / rel))
        assert not hits, f"{rel} calls the clock or uuid directly"
