"""The composition root: the only place that builds adapters and wires use cases (spec: architecture).

`build(repo)` reads `WORKFLOW.md` and returns the use cases of the commands that need it;
`build_adr(repo)` serves the ADR commands, which need no config.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from samba.adapters.adr_files import FileAdrs
from samba.adapters.claude_cli import ClaudeCliRunner
from samba.adapters.git_merger import GitMerger
from samba.adapters.git_workspaces import GitWorkspaces
from samba.adapters.markdown_tasks import MarkdownTasks
from samba.adapters.repo_lock import FileRepoLock
from samba.adapters.system import SystemClock, UuidGenerator
from samba.adapters.terminal import StdTerminal
from samba.app.accept_work import AcceptWork
from samba.app.adr import ListAdrs, SetAdrStatus, ShowAdr, SupersedeAdr
from samba.app.answer_question import AnswerQuestion
from samba.app.change_state import ChangeState
from samba.app.create_task import CreateTask
from samba.app.machine import Machine
from samba.app.queries import ListQuestions, ListTasks, ShowQuestion, ShowTask
from samba.config import Config, load_config
from samba.orchestrator import Orchestrator
from samba.ports import Tasks


@dataclass(frozen=True)
class AdrServices:
    list: ListAdrs
    show: ShowAdr
    set_status: SetAdrStatus
    supersede: SupersedeAdr


@dataclass(frozen=True)
class Services:
    config: Config
    tasks: Tasks
    change_state: ChangeState
    answer_question: AnswerQuestion
    accept_work: AcceptWork
    create_task: CreateTask
    list_tasks: ListTasks
    show_task: ShowTask
    list_questions: ListQuestions
    show_question: ShowQuestion
    orchestrator: Orchestrator


def build(repo: Path) -> Services:
    """Load the config of `repo` (raises `ConfigError`) and build every use case."""
    config = load_config(repo)
    layout = config.layout
    sym = layout.samba_dir
    clock = SystemClock()
    tasks = MarkdownTasks(sym / "tasks", sym / "state", clock)
    terminal = StdTerminal()
    lock = FileRepoLock(sym)
    machine = Machine(tasks, clock)
    agent = ClaudeCliRunner(config.agent, (sym / "tasks").resolve(), sym / "runs", layout.repo)
    workspaces = GitWorkspaces(layout, config.hooks, config.validation.shell)
    return Services(
        config=config,
        tasks=tasks,
        change_state=ChangeState(tasks, machine, terminal, lock),
        answer_question=AnswerQuestion(tasks, machine, terminal, lock, clock),
        accept_work=AcceptWork(tasks, machine, terminal, lock,
                               GitMerger(layout, config.validation), layout.base_branch,
                               config.validation.command),
        create_task=CreateTask(tasks, terminal, clock),
        list_tasks=ListTasks(tasks, clock),
        show_task=ShowTask(tasks, clock),
        list_questions=ListQuestions(tasks),
        show_question=ShowQuestion(tasks),
        orchestrator=Orchestrator(config, clock, UuidGenerator(), agent, tasks, workspaces, lock),
    )


def build_adr(repo: Path) -> AdrServices:
    """The ADR commands are plain file edits: no WORKFLOW.md, no lock."""
    adrs = FileAdrs(repo)
    return AdrServices(ListAdrs(adrs), ShowAdr(adrs), SetAdrStatus(adrs), SupersedeAdr(adrs))
