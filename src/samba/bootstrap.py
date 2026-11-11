"""The bootstrap: the only place that builds adapters and wires use cases (spec: architecture).

`build(repo)` reads `WORKFLOW.md` and returns `Commands`: only use cases, the contract any front
end (the CLI, a web page, an MCP server) can call. `build_adr(repo)` serves the ADR commands,
which need no config. `build_orchestrator(repo)` serves `samba run` alone: the orchestrator is not
a use case. `build_explore(repo)` serves `samba explore`, which needs only the `claude` command
and model. Every entry point calls it.
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
from samba.app.completion import CompleteAdrs, CompleteQuestions, CompleteTaskIds
from samba.app.create_task import CreateTask
from samba.app.explore import StartExplore
from samba.app.machine import Machine
from samba.app.queries import ListQuestions, ListTasks, ShowQuestion, ShowTask
from samba.app.task_commands import (AcceptPlan, DiscardTask, RejectPlan, RejectWork, RetryTask,
                                     StopTask)
from samba.adapters.workflow_file import load_config
from samba.domain.ports import Journal
from samba.domain.settings import Config
from samba.entrypoints.orchestrator import Orchestrator


@dataclass(frozen=True)
class AdrCommands:
    list: ListAdrs
    show: ShowAdr
    set_status: SetAdrStatus
    supersede: SupersedeAdr
    complete: CompleteAdrs


@dataclass(frozen=True)
class Commands:
    """Use cases only: each takes plain values and returns a result of the closed set."""

    accept_plan: AcceptPlan
    reject_plan: RejectPlan
    reject_work: RejectWork
    retry_task: RetryTask
    stop_task: StopTask
    discard_task: DiscardTask
    list_tasks: ListTasks
    show_task: ShowTask
    list_questions: ListQuestions
    show_question: ShowQuestion
    answer_question: AnswerQuestion
    accept_work: AcceptWork
    create_task: CreateTask
    complete_tasks: CompleteTaskIds
    complete_questions: CompleteQuestions


@dataclass(frozen=True)
class _Parts:
    """The adapters and settings the builders share."""

    config: Config
    sym: Path
    repo: Path
    clock: SystemClock
    tasks: MarkdownTasks
    terminal: StdTerminal
    lock: FileLock
    vcs: GitVcs
    validator: ShellValidator


def _parts(repo: Path) -> _Parts:
    config, locations = load_config(repo)
    sym = locations.samba_dir
    clock = SystemClock()
    return _Parts(
        config=config, sym=sym, repo=locations.repo, clock=clock,
        tasks=MarkdownTasks(sym / "tasks", sym / "state", clock),
        terminal=StdTerminal(), lock=FileLock(sym),
        vcs=GitVcs(locations, config.repository.base_branch, config.hooks, config.validation.shell),
        validator=ShellValidator(config.validation, sym / "runs"))


def build(repo: Path) -> Commands:
    """Load the config of `repo` (raises `ConfigError`) and build every use case. Nothing here
    journals: only `samba run` (`build_orchestrator`) writes `samba.log`."""
    p = _parts(repo)
    machine = Machine(p.tasks, p.clock, NullJournal())
    change_state = ChangeState(p.tasks, machine, p.terminal, p.lock)
    return Commands(
        accept_plan=AcceptPlan(change_state),
        reject_plan=RejectPlan(change_state),
        reject_work=RejectWork(change_state),
        retry_task=RetryTask(change_state),
        stop_task=StopTask(change_state),
        discard_task=DiscardTask(change_state),
        list_tasks=ListTasks(p.tasks, p.clock),
        show_task=ShowTask(p.tasks, p.clock),
        list_questions=ListQuestions(p.tasks),
        show_question=ShowQuestion(p.tasks),
        answer_question=AnswerQuestion(p.tasks, machine, p.terminal, p.lock, p.clock),
        accept_work=AcceptWork(p.tasks, machine, p.terminal, p.lock, p.vcs, p.validator,
                               p.config.repository.base_branch, p.config.validation.command),
        create_task=CreateTask(p.tasks, p.terminal, p.clock),
        complete_tasks=CompleteTaskIds(p.tasks),
        complete_questions=CompleteQuestions(p.tasks),
    )


def build_orchestrator(repo: Path) -> Orchestrator:
    """The orchestrator for `samba run` (raises `ConfigError`); it writes `samba.log` and logs to
    stderr. It is not a use case and is not part of `Commands`."""
    p = _parts(repo)
    journal: Journal = LogJournal(p.sym)
    agent = ClaudeCliRunner(p.config.agent, (p.sym / "tasks").resolve(), p.sym / "runs", p.repo,
                            journal)
    return Orchestrator(p.config, p.clock, UuidGenerator(), agent, p.tasks, p.vcs, p.validator,
                        p.lock, journal)


def build_explore(repo: Path) -> StartExplore:
    """`samba explore` needs only `claude.command` and `claude.model` from `WORKFLOW.md` (raises
    `ConfigError`): no lock, no journal, nothing under `.samba/`."""
    config, locations = load_config(repo)
    return StartExplore(config.agent.command, config.agent.model, str(locations.repo),
                        TerminalSession())


def build_adr(repo: Path) -> AdrCommands:
    """The ADR commands are plain file edits: no WORKFLOW.md, no lock."""
    adrs = FileAdrs(repo)
    return AdrCommands(ListAdrs(adrs), ShowAdr(adrs), SetAdrStatus(adrs), SupersedeAdr(adrs),
                       CompleteAdrs(adrs))
