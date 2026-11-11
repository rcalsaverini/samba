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
DOMAIN_MODULES = ["domain/template.py", "domain/prompts.py", "domain/__init__.py",
                  "domain/ports.py", "domain/states.py", "domain/questions.py",
                  "domain/transitions.py", "domain/deps.py", "domain/agent.py",
                  "domain/policy.py", "domain/task.py", "domain/task_id.py",
                  "domain/validation.py", "domain/launch.py", "domain/settings.py"]

# Use cases: may log and await, but import no adapter and call no clock or uuid directly.
APP_MODULES = ["app/__init__.py", "app/turn.py", "app/machine.py", "app/results.py",
               "app/confirm.py", "app/change_state.py", "app/answer_question.py",
               "app/resolve.py", "app/accept_work.py", "app/create_task.py",
               "app/adr.py", "app/queries.py", "app/tick.py", "app/explore.py"]

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


def violations(path: Path) -> list[str]:
    """Imports in `path` that a domain module may not have."""
    bad: list[str] = []
    for name in imported_modules(path):
        if name.split(".")[0] in FORBIDDEN:
            bad.append(name)
        elif name == "samba.adapters" or name.startswith("samba.adapters."):
            bad.append(name)
    return bad


def test_domain_modules_import_no_io_and_no_adapter() -> None:
    for rel in DOMAIN_MODULES:
        assert violations(SRC / rel) == [], f"{rel} breaks the dependency rule"


def test_app_modules_import_no_adapter() -> None:
    for rel in APP_MODULES:
        assert (SRC / rel).is_file(), f"{rel} is listed as a use case but does not exist"
        for name in imported_modules(SRC / rel):
            assert not (name == "samba.adapters" or name.startswith("samba.adapters.")), (
                f"{rel} imports {name}")


def test_the_check_catches_an_adapter_and_io_import(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("from samba.adapters.system import SystemClock\nimport datetime\n"
                   "from samba import adapters\n")
    assert violations(bad) == ["samba.adapters.system", "datetime", "samba.adapters"]


def test_scenario_runner_imports_no_adapter_and_no_store() -> None:
    for name in imported_modules(Path(__file__).parent / "test_scenarios.py"):
        assert not (name == "samba.adapters" or name.startswith("samba.adapters.")), name


def code_without_comments(path: Path) -> str:
    return "\n".join(line.split("#", 1)[0] for line in path.read_text().splitlines())


CLAUDE_JSON = re.compile(r"(?<!no_)structured_output|permission_denials|total_cost_usd|samba\.claude\b"
                         r"|\b(?:res|result)\.(?:init|result)\b|\.get\(\"is_error\"\)")


def test_only_the_claude_adapter_reads_claude_json() -> None:
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel == "adapters/claude_cli.py":
            continue
        hits = CLAUDE_JSON.findall(code_without_comments(path))
        assert not hits, f"{rel} reads Claude's JSON: {hits}"
    assert not (SRC / "claude.py").exists(), "claude.py moved to adapters/claude_cli.py"


STORAGE_WORDS = re.compile(r"Path|mtime|sidecar|front matter")


def test_domain_and_app_code_has_no_storage_vocabulary() -> None:
    # domain/prompts.py talks to the agent about its task file's front matter: exempt.
    for rel in [r for r in [*DOMAIN_MODULES, *APP_MODULES] if r != "domain/prompts.py"]:
        hits = STORAGE_WORDS.findall(code_without_comments(SRC / rel))
        assert not hits, f"{rel} mentions storage details: {hits}"


def test_the_storage_check_catches_path_and_sidecar(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("x = Path('a')  # fine here\ny = 'sidecar'\n# mtime in a comment is fine\n")
    assert STORAGE_WORDS.findall(code_without_comments(bad)) == ["Path", "sidecar"]


def test_the_old_task_store_is_gone_and_the_adapter_is_used() -> None:
    assert not (SRC / "tasks.py").exists(), "tasks.py moved to adapters/markdown_tasks.py"
    assert not (SRC / "transitions.py").exists(), "transitions.py moved to app/machine.py"
    assert not (SRC / "domain" / "sidecar.py").exists()
    assert "samba.adapters.markdown_tasks" in imported_modules(SRC / "compose.py")
    for path in sorted(SRC.rglob("*.py")):
        assert "samba.tasks" not in imported_modules(path), f"{path} imports the old folder helpers"


def test_the_root_modules_moved_into_their_layers() -> None:
    for old in ("prompts.py", "template.py", "proc.py", "logfmt.py", "adr.py"):
        assert not (SRC / old).exists(), f"{old} moved into domain/ or adapters/"
    assert (SRC / "adapters" / "process.py").is_file()
    assert (SRC / "adapters" / "adr_format.py").is_file()
    assert not (SRC / "config.py").exists(), "config.py split into domain/settings.py and the reader"
    assert (SRC / "adapters" / "workflow_file.py").is_file()
    assert (SRC / "domain" / "settings.py").is_file()


NO_PATH_NO_YAML = {"pathlib", "yaml"}


def path_or_yaml_imports(path: Path) -> list[str]:
    return [n for n in imported_modules(path) if n.split(".")[0] in NO_PATH_NO_YAML]


def test_domain_and_app_import_no_pathlib_or_yaml() -> None:
    for rel in [*DOMAIN_MODULES, *APP_MODULES]:
        assert path_or_yaml_imports(SRC / rel) == [], f"{rel} imports pathlib or yaml"


def test_the_pathlib_and_yaml_check_catches_both(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("import yaml\nfrom pathlib import Path\n")
    assert path_or_yaml_imports(bad) == ["yaml", "pathlib"]


def test_the_core_settings_carry_no_location() -> None:
    code = code_without_comments(SRC / "domain" / "settings.py")
    assert "Layout" not in code
    for word in ("repo", "samba_dir", "workspaces_root"):
        assert not re.search(rf"\b{word}\b", code), f"domain/settings.py has a {word} field"


def is_adapter(name: str) -> bool:
    return name == "samba.adapters" or name.startswith("samba.adapters.")


def adapter_imports(path: Path) -> list[str]:
    return [n for n in imported_modules(path) if is_adapter(n)]


def test_only_the_composition_root_builds_adapters() -> None:
    for rel in ["cli.py", "orchestrator.py"]:
        assert adapter_imports(SRC / rel) == [], f"{rel} reaches an adapter outside the root"
    root = code_without_comments(SRC / "compose.py")
    assert "MarkdownTasks(" in root
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in ("compose.py", "adapters/markdown_tasks.py"):
            continue
        assert "MarkdownTasks(" not in code_without_comments(path), rel


def test_the_cli_adapter_holds_no_rule() -> None:
    code = code_without_comments(SRC / "cli.py")
    for word in ("human_events", "merge.", "TaskId.slug", "Machine", "subprocess"):
        assert word not in code, f"cli.py mentions {word}"


APP_FORBIDDEN = {"os", "subprocess", "pathlib", "logging"}  # asyncio is fine: use cases await ports


def app_violations(path: Path) -> list[str]:
    return [n for n in imported_modules(path)
            if n.split(".")[0] in APP_FORBIDDEN or is_adapter(n)]


def test_app_modules_import_no_io_no_logging_no_adapter() -> None:
    for rel in APP_MODULES:
        assert app_violations(SRC / rel) == [], rel


def test_every_domain_and_app_module_is_listed() -> None:
    listed = {*DOMAIN_MODULES, *APP_MODULES}
    found = {p.relative_to(SRC).as_posix() for sub in ("domain", "app")
             for p in (SRC / sub).rglob("*.py")}
    assert found - listed == set(), f"add to DOMAIN_MODULES or APP_MODULES: {sorted(found - listed)}"


ORCHESTRATOR_FORBIDDEN = {"os", "subprocess", "pathlib", "logging", "samba.workspace",
                          "samba.merge", "samba.lock"}


def orchestrator_violations(path: Path) -> list[str]:
    return [n for n in imported_modules(path)
            if n in ORCHESTRATOR_FORBIDDEN or n.split(".")[0] in {"os", "subprocess", "pathlib",
                                                                   "logging"} or is_adapter(n)]


def test_the_orchestrator_imports_no_io_adapter_or_old_module() -> None:
    assert orchestrator_violations(SRC / "orchestrator.py") == []


def test_the_new_checks_catch_logging_pathlib_and_old_modules(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("import logging\nfrom pathlib import Path\nimport samba.merge\n"
                   "from samba.adapters.git_vcs import GitVcs\n")
    assert app_violations(bad) == ["logging", "pathlib", "samba.adapters.git_vcs"]
    assert orchestrator_violations(bad) == ["logging", "pathlib", "samba.merge",
                                            "samba.adapters.git_vcs"]

def test_the_check_catches_import_os(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("import os\n")
    assert violations(bad) == ["os"]


def test_only_the_adapter_splits_task_front_matter() -> None:
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in ("adapters/markdown_tasks.py", "adapters/workflow_file.py",
                   "adapters/adr_format.py"):
            continue  # the workflow file reader reads WORKFLOW.md, adr reads ADR files: their own front matter
        assert "split_front_matter" not in code_without_comments(path), rel


def test_no_direct_clock_or_uuid_calls() -> None:
    pattern = re.compile(r"\btime\.(time|monotonic)\(|\bdatetime\.now\(|\buuid\.")
    for rel in ["orchestrator.py", *APP_MODULES, *DOMAIN_MODULES]:
        hits = pattern.findall(code_without_comments(SRC / rel))
        assert not hits, f"{rel} calls the clock or uuid directly"
