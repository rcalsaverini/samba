"""The composition root: the only place that builds adapters and wires use cases (spec: architecture).

`build(repo)` reads `WORKFLOW.md` and returns the use cases of the commands that need it;
`build_adr(repo)` serves the ADR commands, which need no config; `build_explore(repo)` serves
`samba explore`, which needs only the `claude` command and model.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from samba.adapters.adr_files import FileAdrs
from samba.adapters.claude_cli import ClaudeCliRunner
from samba.adapters.file_lock import FileLock
from samba.adapters.git_vcs import GitVcs
from samba.adapters.log_journal import LogJournal, NullJournal
from samba.adapters.interactive_session import TerminalSession
from samba.adapters.markdown_tasks import MarkdownTasks
from samba.adapters.shell_validator import ShellValidator
from samba.adapters.system import SystemClock, UuidGenerator
from samba.adapters.terminal import StdTerminal
from samba.app.accept_work import AcceptWork
from samba.app.adr import ListAdrs, SetAdrStatus, ShowAdr, SupersedeAdr
from samba.app.answer_question import AnswerQuestion
from samba.app.change_state import ChangeState
from samba.app.create_task import CreateTask
from samba.app.explore import StartExplore
from samba.app.machine import Machine
from samba.app.queries import ListQuestions, ListTasks, ShowQuestion, ShowTask
from samba.adapters.workflow_file import load_config
from samba.domain.settings import Config
from samba.orchestrator import Orchestrator
from samba.domain.ports import Journal, Tasks


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


def build(repo: Path, *, for_run: bool = False) -> Services:
    """Load the config of `repo` (raises `ConfigError`) and build every use case. Only `samba run`
    (`for_run`) writes `samba.log` and logs to stderr; other commands journal nothing."""
    config, locations = load_config(repo)
    sym = locations.samba_dir
    journal: Journal = LogJournal(sym) if for_run else NullJournal()
    clock = SystemClock()
    tasks = MarkdownTasks(sym / "tasks", sym / "state", clock)
    terminal = StdTerminal()
    lock = FileLock(sym)
    machine = Machine(tasks, clock, journal)
    agent = ClaudeCliRunner(config.agent, (sym / "tasks").resolve(), sym / "runs", locations.repo,
                            journal)
    vcs = GitVcs(locations, config.repository.base_branch, config.hooks, config.validation.shell)
    validator = ShellValidator(config.validation, sym / "runs")
    return Services(
        config=config,
        tasks=tasks,
        change_state=ChangeState(tasks, machine, terminal, lock),
        answer_question=AnswerQuestion(tasks, machine, terminal, lock, clock),
        accept_work=AcceptWork(tasks, machine, terminal, lock, vcs, validator,
                               config.repository.base_branch, config.validation.command),
        create_task=CreateTask(tasks, terminal, clock),
        list_tasks=ListTasks(tasks, clock),
        show_task=ShowTask(tasks, clock),
        list_questions=ListQuestions(tasks),
        show_question=ShowQuestion(tasks),
        orchestrator=Orchestrator(config, clock, UuidGenerator(), agent, tasks, vcs, validator,
                                  lock, journal),
    )


def build_explore(repo: Path) -> StartExplore:
    """`samba explore` needs only `claude.command` and `claude.model` from `WORKFLOW.md` (raises
    `ConfigError`): no lock, no journal, nothing under `.samba/`."""
    config, locations = load_config(repo)
    return StartExplore(config.agent.command, config.agent.model, str(locations.repo),
                        TerminalSession())


def build_adr(repo: Path) -> AdrServices:
    """The ADR commands are plain file edits: no WORKFLOW.md, no lock."""
    adrs = FileAdrs(repo)
    return AdrServices(ListAdrs(adrs), ShowAdr(adrs), SetAdrStatus(adrs), SupersedeAdr(adrs))
