"""Architecture guard: the dependency rule of docs/spec/architecture.md.

Reads source files with `ast`; never imports samba.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
SRC = Path(__file__).resolve().parents[2] / "src" / "samba"

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
               "app/adr.py", "app/queries.py", "app/tick.py", "app/explore.py", "app/guard.py",
               "app/startup.py", "app/prompt_builder.py", "app/finish.py", "app/run_task.py",
               "app/task_commands.py", "app/completion.py"]

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
    for name in imported_modules(TESTS / "component" / "test_scenarios.py"):
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
    assert "samba.adapters.markdown_tasks" in imported_modules(SRC / "bootstrap.py")
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


ROOT_FILES = {"__init__.py", "__main__.py", "bootstrap.py"}
ROOT_PACKAGES = {"domain", "app", "adapters", "entrypoints"}
ENTRYPOINT_FILES = {"__init__.py", "cli.py", "table.py", "orchestrator.py", "workers.py"}


def root_problems(root: Path) -> list[str]:
    """What at the top of `root` is not one of the allowed files or packages."""
    entries = [p for p in root.iterdir() if p.name != "__pycache__"]
    files = {p.name for p in entries if p.is_file() and p.suffix == ".py"}
    dirs = {p.name for p in entries if p.is_dir()}
    other = {p.name for p in entries if p.is_file() and p.suffix != ".py"}
    return sorted([f"file {n}" for n in files ^ ROOT_FILES] + [f"dir {n}" for n in dirs ^ ROOT_PACKAGES]
                  + [f"other {n}" for n in other])


def test_the_root_holds_only_bootstrap_main_and_the_four_layers() -> None:
    assert root_problems(SRC) == []


def test_the_root_check_catches_a_stray_module_and_package(tmp_path: Path) -> None:
    for name in ROOT_FILES:
        (tmp_path / name).write_text("")
    for name in ROOT_PACKAGES:
        (tmp_path / name).mkdir()
    (tmp_path / "__pycache__").mkdir()
    assert root_problems(tmp_path) == []
    (tmp_path / "foo.py").write_text("")
    (tmp_path / "extra").mkdir()
    (tmp_path / "bootstrap.py").unlink()
    assert root_problems(tmp_path) == ["dir extra", "file bootstrap.py", "file foo.py"]


def test_the_old_root_modules_are_gone() -> None:
    for old in ("cli.py", "views.py", "orchestrator.py", "compose.py"):
        assert not (SRC / old).exists(), f"{old} moved into entrypoints/ or bootstrap.py"


def test_every_entrypoint_module_is_accounted_for() -> None:
    found = {p.name for p in (SRC / "entrypoints").rglob("*.py")}
    assert found == ENTRYPOINT_FILES


def is_outer(name: str) -> bool:
    return name in ("samba.bootstrap", "samba.entrypoints") or name.startswith("samba.entrypoints.")


def test_inner_layers_import_neither_bootstrap_nor_entrypoints() -> None:
    for sub in ("domain", "app", "adapters"):
        for path in sorted((SRC / sub).rglob("*.py")):
            bad = [n for n in imported_modules(path) if is_outer(n)]
            assert bad == [], f"{path.relative_to(SRC)} imports {bad}"


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
    for path in sorted((SRC / "entrypoints").rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        assert adapter_imports(path) == [], f"{rel} reaches an adapter outside the root"
    root = code_without_comments(SRC / "bootstrap.py")
    assert "MarkdownTasks(" in root
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in ("bootstrap.py", "adapters/markdown_tasks.py"):
            continue
        assert "MarkdownTasks(" not in code_without_comments(path), rel


def test_the_cli_adapter_holds_no_rule() -> None:
    code = code_without_comments(SRC / "entrypoints" / "cli.py")
    for word in ("human_events", "merge.", "TaskId.slug", "Machine", "subprocess"):
        assert word not in code, f"entrypoints/cli.py mentions {word}"


CLI_FORBIDDEN = {"samba.app.resolve", "samba.domain.task_id", "samba.entrypoints.orchestrator",
                 "samba.entrypoints.workers"}


def cli_violations(path: Path) -> list[str]:
    """Imports a CLI module may not have: id resolution (use cases resolve ids) and other entry points."""
    return [n for n in imported_modules(path) if n in CLI_FORBIDDEN]


def test_the_cli_resolves_no_id_and_calls_no_other_entry_point() -> None:
    assert cli_violations(SRC / "entrypoints" / "cli.py") == []


def test_the_cli_check_catches_resolution_and_entry_points(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("from samba.app.resolve import find_task\nfrom samba.domain.task_id import TaskId\n"
                   "from samba.entrypoints.orchestrator import Orchestrator\n"
                   "from samba.entrypoints.table import print_table\n")
    assert cli_violations(bad) == ["samba.app.resolve", "samba.domain.task_id",
                                   "samba.entrypoints.orchestrator"]


CLI_LIBRARIES = {"argparse", "typer", "click"}


def cli_library_imports(path: Path) -> list[str]:
    return [n for n in imported_modules(path) if n.split(".")[0] in CLI_LIBRARIES]


def test_domain_and_app_import_no_cli_library_and_nothing_uses_argparse(tmp_path: Path) -> None:
    for rel in [*DOMAIN_MODULES, *APP_MODULES]:
        assert cli_library_imports(SRC / rel) == [], rel
    for path in sorted(SRC.rglob("*.py")):
        assert "argparse" not in [n.split(".")[0] for n in imported_modules(path)], path
    bad = tmp_path / "bad.py"
    bad.write_text("import argparse\nimport typer\nfrom click import Command\n")
    assert cli_library_imports(bad) == ["argparse", "typer", "click"]


APP_FORBIDDEN = {"os", "subprocess", "pathlib", "logging", "asyncio"}  # use cases await ports, never the loop


def app_violations(path: Path) -> list[str]:
    return [n for n in imported_modules(path)
            if n.split(".")[0] in APP_FORBIDDEN or is_adapter(n)]


def test_app_modules_import_no_io_no_logging_no_adapter() -> None:
    for rel in APP_MODULES:
        assert app_violations(SRC / rel) == [], rel


def test_completion_queries_stay_in_app_without_typer_or_click(tmp_path: Path) -> None:
    assert (SRC / "app" / "completion.py").is_file()
    assert cli_library_imports(SRC / "app" / "completion.py") == []
    bad = tmp_path / "bad.py"
    bad.write_text("import typer\nimport click\n")
    assert cli_library_imports(bad) == ["typer", "click"]


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
    assert orchestrator_violations(SRC / "entrypoints" / "orchestrator.py") == []


def test_the_workers_import_no_io_adapter_or_old_module() -> None:
    assert orchestrator_violations(SRC / "entrypoints" / "workers.py") == []


def test_the_orchestrator_is_thin_and_holds_no_rule() -> None:
    path = SRC / "entrypoints" / "orchestrator.py"
    assert len(path.read_text().splitlines()) <= 110
    rules = {"samba.domain.policy", "samba.domain.prompts", "samba.domain.template"}
    assert rules & set(imported_modules(path)) == set()


def test_the_new_checks_catch_logging_pathlib_and_old_modules(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("import logging\nfrom pathlib import Path\nimport samba.merge\n"
                   "from samba.adapters.git_vcs import GitVcs\n")
    assert app_violations(bad) == ["logging", "pathlib", "samba.adapters.git_vcs"]
    assert orchestrator_violations(bad) == ["logging", "pathlib", "samba.merge",
                                            "samba.adapters.git_vcs"]

def test_app_modules_import_no_asyncio(tmp_path: Path) -> None:
    for rel in APP_MODULES:
        assert "asyncio" not in [n.split(".")[0] for n in imported_modules(SRC / rel)], rel
    bad = tmp_path / "bad.py"
    bad.write_text("import asyncio\n")
    assert app_violations(bad) == ["asyncio"]


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
    for rel in ["entrypoints/orchestrator.py", "entrypoints/workers.py", *APP_MODULES, *DOMAIN_MODULES]:
        hits = pattern.findall(code_without_comments(SRC / rel))
        assert not hits, f"{rel} calls the clock or uuid directly"


# Test levels (ADR 0016): what each folder of tests/ may import.
LEVELS = {"unit", "component", "integration", "e2e", "checks", "legacy"}


def fake_modules(tests: Path) -> set[str]:
    return {p.stem for p in (tests / "fakes").glob("*.py")}


def folder_imports(tests: Path, folder: str) -> list[tuple[str, str]]:
    """(file, imported module) pairs over the python files of one level folder."""
    return [(p.name, n) for p in sorted((tests / folder).rglob("*.py")) for n in imported_modules(p)]


def unit_violations(tests: Path) -> list[tuple[str, str]]:
    fakes = fake_modules(tests)
    return [(f, n) for f, n in folder_imports(tests, "unit")
            if is_adapter(n) or n.split(".")[0] in fakes
            or n.split(".")[0].startswith("test_") or n.split(".")[0] == "legacy_support"]


def component_violations(tests: Path) -> list[tuple[str, str]]:
    return [(f, n) for f, n in folder_imports(tests, "component") if is_adapter(n)]


def integration_violations(tests: Path) -> list[tuple[str, str]]:
    return [(f, n) for f, n in folder_imports(tests, "integration") if is_outer(n)]


def e2e_violations(tests: Path) -> list[tuple[str, str]]:
    return [(f, n) for f, n in folder_imports(tests, "e2e") if n.split(".")[0] == "samba"]


def test_unit_imports_no_adapter_and_no_fake() -> None:
    assert unit_violations(TESTS) == []


def test_component_imports_no_adapter() -> None:
    assert component_violations(TESTS) == []


def test_integration_imports_no_entrypoint_or_bootstrap() -> None:
    assert integration_violations(TESTS) == []


def test_e2e_imports_no_samba() -> None:
    assert e2e_violations(TESTS) == []


def level_problems(tests: Path) -> list[str]:
    """Test files outside a level folder, python files at the root, tests among the fakes."""
    problems = [f"{p.relative_to(tests).as_posix()}: not in a level folder"
                for p in sorted(tests.rglob("*.py"))
                if p.relative_to(tests).parts[0] not in {*LEVELS, "fakes"}]
    problems += [f"fakes/{p.name}: a test among the fakes" for p in sorted((tests / "fakes").rglob("test_*.py"))]
    return problems


def test_every_test_file_sits_in_a_level_folder() -> None:
    assert level_problems(TESTS) == []


def duplicate_names(tests: Path) -> list[str]:
    """Test file basenames used twice (no __init__.py: pytest would fail with an import mismatch)."""
    seen: dict[str, int] = {}
    for p in tests.rglob("test_*.py"):
        seen[p.name] = seen.get(p.name, 0) + 1
    return sorted(n for n, c in seen.items() if c > 1)


def test_test_file_names_are_unique_across_tests() -> None:
    assert duplicate_names(TESTS) == []


def test_the_level_checks_catch_violations(tmp_path: Path) -> None:
    for d in ("unit", "component", "integration", "e2e", "fakes"):
        (tmp_path / d).mkdir()
    (tmp_path / "fakes" / "fake_vcs.py").write_text("")
    (tmp_path / "unit" / "test_a.py").write_text(
        "from samba.adapters.system import SystemClock\nfrom fake_vcs import FakeVcs\n"
        "from samba.domain.task import Task\nfrom legacy_support import sb\n")
    (tmp_path / "component" / "test_b.py").write_text(
        "from fake_vcs import FakeVcs\nfrom samba.adapters.git_vcs import GitVcs\n")
    (tmp_path / "integration" / "test_c.py").write_text(
        "from samba.bootstrap import build\nimport samba.entrypoints.cli\nfrom samba.adapters import x\n")
    (tmp_path / "e2e" / "test_d.py").write_text("import samba.x\nfrom samba import y\nimport json\n")
    assert unit_violations(tmp_path) == [("test_a.py", "samba.adapters.system"), ("test_a.py", "fake_vcs"),
                                         ("test_a.py", "legacy_support")]
    assert component_violations(tmp_path) == [("test_b.py", "samba.adapters.git_vcs")]
    assert integration_violations(tmp_path) == [("test_c.py", "samba.bootstrap"),
                                                ("test_c.py", "samba.entrypoints.cli")]
    assert e2e_violations(tmp_path) == [("test_d.py", "samba.x"), ("test_d.py", "samba"),
                                      ("test_d.py", "samba.y")]


def test_the_layout_checks_catch_a_stray_test_and_a_duplicate_name(tmp_path: Path) -> None:
    for d in ("unit", "component", "fakes"):
        (tmp_path / d).mkdir()
    assert level_problems(tmp_path) == []
    (tmp_path / "test_x.py").write_text("")
    (tmp_path / "fakes" / "test_f.py").write_text("")
    (tmp_path / "unit" / "test_same.py").write_text("")
    (tmp_path / "component" / "test_same.py").write_text("")
    assert level_problems(tmp_path) == ["test_x.py: not in a level folder",
                                        "fakes/test_f.py: a test among the fakes"]
    assert duplicate_names(tmp_path) == ["test_same.py"]
