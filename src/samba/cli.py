"""Command line: `samba run`, and `<noun> <verb>` for task, plan, work, question, adr, dev (spec: cli)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import signal
import sys
from pathlib import Path
from typing import cast

from samba import adr as adr_mod
from samba.adapters.git_merger import GitMerger
from samba.adapters.markdown_tasks import MarkdownTasks
from samba.adapters.repo_lock import FileRepoLock
from samba.adapters.system import SystemClock
from samba.adapters.terminal import StdTerminal
from samba.app.accept_work import AcceptWork, DryRun
from samba.app.answer_question import AnswerQuestion
from samba.app.change_state import ChangeState, FeedbackMode
from samba.app.create_task import CreateTask
from samba.app.machine import Machine
from samba.app.resolve import ResolveError, resolve_task_id
from samba.app.results import Refused
from samba.config import Config, ConfigError, load_config
from samba.domain.questions import round_questions
from samba.domain.states import STATES
from samba.domain.transitions import render_markdown_table
from samba.orchestrator import Orchestrator, StartupError
from samba.ports import Tasks
from samba.views import print_table, question_rows, render_show, resolve_states, task_rows


def _setup_logging(config: Config) -> None:
    config.layout.samba_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger("samba")
    root.setLevel(logging.DEBUG)
    file_handler = logging.FileHandler(config.layout.samba_dir / "samba.log")
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    console.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console)


def cmd_run(config: Config, exit_when_idle: bool) -> int:
    _setup_logging(config)
    orch = Orchestrator(config)

    async def main() -> None:
        loop = asyncio.get_running_loop()
        current = asyncio.current_task()
        assert current is not None
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, current.cancel)
        await orch.run(exit_when_idle=exit_when_idle)

    try:
        asyncio.run(main())
    except StartupError as e:
        print(f"samba: {e}", file=sys.stderr)
        return 1
    except asyncio.CancelledError:
        print("samba: stopped", file=sys.stderr)
    return 0


def cmd_task_list(config: Config, states: list[str]) -> int:
    """`task list [STATE...]`."""
    try:
        chosen = resolve_states(states) if states else STATES
    except ResolveError as e:
        print(f"samba: {e.render()}", file=sys.stderr)
        return 2
    tasks = _store(config)
    print_table(task_rows(tasks, chosen), shutil.get_terminal_size().columns, flex=6)
    return 0


def _store(config: Config) -> Tasks:
    """The task store the commands use (the composition root arrives with a later task)."""
    sym = config.layout.samba_dir
    return MarkdownTasks(sym / "tasks", sym / "state", SystemClock())


def cmd_task_show(config: Config, text: str) -> int:
    tasks = _store(config)
    try:
        task = tasks.get(resolve_task_id(tasks, text))
    except ResolveError as e:
        print(f"samba: {e.render()}", file=sys.stderr)
        return 2
    if task is None:
        print(f"samba: unknown task {text!r}", file=sys.stderr)
        return 2
    print("\n".join(render_show(tasks, task)))
    return 0


def _report(result: Refused) -> int:
    for line in result.messages:
        print(line, file=sys.stderr)
    return 2 if result.kind == "usage" else 1


def cmd_transition(config: Config, text: str, event: str, label: str, *,
                   feedback: str | None = None, edit: bool = False,
                   feedback_mode: FeedbackMode = "none",
                   confirm_plan: str | None = None, yes: bool = False,
                   hints: bool = False) -> int:
    """Resolve the id, run the `ChangeState` use case, print its result (spec: cli)."""
    tasks = _store(config)
    try:
        task_id = resolve_task_id(tasks, text)
    except ResolveError as e:
        print(f"samba: {e.render()}", file=sys.stderr)
        return 2
    use_case = ChangeState(tasks, Machine(tasks, SystemClock()), StdTerminal(),
                           FileRepoLock(config.layout.samba_dir))
    result = use_case.run(task_id, event, label, feedback=feedback, edit=edit,
                          feedback_mode=feedback_mode, confirm_plan=confirm_plan, yes=yes,
                          hints=hints)
    if isinstance(result, Refused):
        return _report(result)
    if result.location is not None:
        print(result.location)
    for line in result.notes:
        print(line, file=sys.stderr)
    return 0


def _err(msg: str) -> None:
    print(f"samba: {msg}", file=sys.stderr)


def _split_target(target: str) -> tuple[str, str | None]:
    """`TASK` or `TASK/QID`. Task ids never contain a slash."""
    task, sep, qid = target.rpartition("/")
    return (task, qid) if sep else (target, None)


def cmd_question_list(config: Config) -> int:
    print_table(question_rows(_store(config)), shutil.get_terminal_size().columns, flex=4)
    return 0


def cmd_question_show(config: Config, target: str) -> int:
    tasks = _store(config)
    name, qid = _split_target(target)
    try:
        task_id = resolve_task_id(tasks, name)
    except ResolveError as e:
        _err(e.render())
        return 2
    task = tasks.get(task_id)
    questions = task.questions if task is not None else ()
    shown = [q for q in questions if q.id == qid] if qid else round_questions(questions)
    if not shown:
        _err(f"unknown question {task_id}/{qid}" if qid else f"{task_id} has no questions")
        return 2
    blocks: list[str] = []
    for q in shown:
        lines = [f"{task_id}/{q.id}  stage: {q.stage}  round: {q.round}"
                 f"  status: {q.status}  asked: {q.asked_at}", "", q.text]
        if q.context:
            lines += ["", "Context: " + q.context]
        if q.status == "answered":
            lines += ["", "Answer: " + (q.answer or "")]
        blocks.append("\n".join(lines))
    print("\n\n".join(blocks))
    return 0


def cmd_question_answer(config: Config, target: str, text: str | None, edit: bool) -> int:
    """`question answer` (spec: cli): resolve the id, run the `AnswerQuestion` use case."""
    tasks = _store(config)
    name, qid = _split_target(target)
    try:
        task_id = resolve_task_id(tasks, name)
    except ResolveError as e:
        _err(e.render())
        return 2
    clock = SystemClock()
    use_case = AnswerQuestion(tasks, Machine(tasks, clock), StdTerminal(),
                              FileRepoLock(config.layout.samba_dir), clock)
    result = use_case.run(task_id, qid, text, edit)
    if isinstance(result, Refused):
        return _report(result)
    if result.location is not None:
        print(result.location)
    for line in result.notes:
        print(line, file=sys.stderr)
    return 0


def cmd_work_accept(config: Config, text: str, *, no_merge: bool, no_validate: bool, yes: bool,
                    dry_run: bool) -> int:
    """`work accept` (spec: cli): the command pattern with a merge as the outside effect."""
    tasks = _store(config)
    try:
        task_id = resolve_task_id(tasks, text)
    except ResolveError as e:
        _err(e.render())
        return 2
    clock = SystemClock()
    use_case = AcceptWork(
        tasks, Machine(tasks, clock), StdTerminal(), FileRepoLock(config.layout.samba_dir),
        GitMerger(config.layout, config.validation), config.layout.base_branch,
        config.validation.command)
    result = use_case.run(task_id, no_merge=no_merge, no_validate=no_validate, yes=yes,
                          dry_run=dry_run)
    if isinstance(result, Refused):
        return _report(result)
    if isinstance(result, DryRun):
        for line in result.lines:
            print(line)
        return 0
    if result.location is not None:
        print(result.location)
    for line in result.notes:
        print(line, file=sys.stderr)
    return 0


def cmd_task_new(config: Config, title: str | None, body: str | None, depends: str | None,
                 priority: int, skip_plan: bool) -> int:
    """`task new` (spec: cli): run the `CreateTask` use case, print its result."""
    tasks = _store(config)
    result = CreateTask(tasks, StdTerminal(), SystemClock()).run(
        title, body, depends, priority, skip_plan)
    if isinstance(result, Refused):
        return _report(result)
    print(result.location)
    return 0


def cmd_adr(args: argparse.Namespace) -> int:
    """`adr list|show|accept|reject|supersede` (spec: cli, ADR commands). Plain file edits: no
    config, no lock, no confirmation, never a commit."""
    repo = cast(Path, args.repo)
    verb = str(args.adr_command)
    try:
        if verb == "list":
            adrs = adr_mod.load_all(repo)
            if not args.all:
                adrs = [a for a in adrs if a.status == "accepted"]
            if args.all:
                rows = [["NUMBER", "STATUS", "TITLE", "SUMMARY"]] + [
                    [f"{a.number:04d}", a.status, a.title, a.summary] for a in adrs]
            else:
                rows = [["NUMBER", "TITLE", "SUMMARY"]] + [
                    [f"{a.number:04d}", a.title, a.summary] for a in adrs]
            print_table(rows, shutil.get_terminal_size().columns, flex=len(rows[0]) - 1)
            return 0
        if verb == "show":
            sys.stdout.write(adr_mod.find(repo, adr_mod.parse_number(str(args.number))).text)
            return 0
        number = adr_mod.parse_number(str(args.number))
        if verb == "supersede":
            written = adr_mod.supersede(repo, number, adr_mod.parse_number(str(args.new)))
        elif verb == "accept":
            written = adr_mod.set_status(repo, number, "accept", "proposed", "accepted")
        else:
            written = adr_mod.set_status(repo, number, "reject", "proposed", "rejected")
    except adr_mod.AdrError as e:
        _err(str(e))
        return e.code
    for path in written:
        print(path)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="samba", formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="development commands:\n    dev    commands for working on Samba itself "
               "(dev transitions)")
    sub = parser.add_subparsers(dest="command", required=True, title="commands",
                                metavar="COMMAND")
    p_run = sub.add_parser("run", help="run the orchestrator loop")
    p_run.add_argument("--exit-when-idle", action="store_true",
                       help="exit once nothing is running and plan-todo/ and work-todo/ are empty")

    def add_list_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("states", nargs="*", metavar="STATE",
                       help="state names or unique prefixes (default: all)")

    def add_show_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("id", help="task id or unique prefix")

    p_task = sub.add_parser("task", help="task commands: new, list, show, retry, stop, discard")
    task_sub = p_task.add_subparsers(dest="task_command", required=True)
    p_tnew = task_sub.add_parser("new", help="create a task (asks for missing fields on a terminal)")
    p_tnew.add_argument("title", nargs="?", metavar="TITLE")
    p_tnew.add_argument("--body", metavar="TEXT", help="the task description")
    p_tnew.add_argument("--depends-on", metavar="IDS",
                        help="comma separated task ids or unique prefixes")
    p_tnew.add_argument("--priority", type=int, default=3, help="priority (default: 3)")
    p_tnew.add_argument("--skip-plan", action="store_true",
                        help="create the task in work-todo/ instead of plan-todo/")
    p_tlist = task_sub.add_parser("list", help="list tasks, optionally filtered by state")
    add_list_args(p_tlist)
    p_tshow = task_sub.add_parser("show", help="show one task in detail")
    add_show_args(p_tshow)
    p_dev = sub.add_parser("dev",  # no help=: it is listed in the epilog, apart from the others
                           description="Commands for working on Samba itself.")
    dev_sub = p_dev.add_subparsers(dest="dev_command", required=True)
    p_trans = dev_sub.add_parser("transitions",
                                 help="print the transition table as Markdown (spec: states)")

    def add_reject_args(p: argparse.ArgumentParser, fresh: bool = False) -> None:
        p.add_argument("id", help="task id or unique prefix")
        group = p.add_mutually_exclusive_group()
        group.add_argument("--feedback", metavar="TEXT", help="feedback for the agent")
        group.add_argument("--edit", action="store_true", help="write the feedback in $EDITOR")
        if fresh:
            p.add_argument("--fresh", action="store_true",
                           help="also clear the session so rework starts a fresh conversation")

    p_plan = sub.add_parser("plan", help="plan review commands: accept, reject")
    plan_sub = p_plan.add_subparsers(dest="plan_command", required=True)
    p_pacc = plan_sub.add_parser("accept", help="approve the plan; the task goes to work-todo")
    p_pacc.add_argument("id", help="task id or unique prefix")
    p_prej = plan_sub.add_parser("reject", help="send the plan back; the task goes to plan-todo")
    add_reject_args(p_prej)
    p_work = sub.add_parser("work", help="work review commands: accept, reject")
    work_sub = p_work.add_subparsers(dest="work_command", required=True)
    p_wrej = work_sub.add_parser("reject", help="send the work back; the task goes to work-todo")
    add_reject_args(p_wrej, fresh=True)
    p_wacc = work_sub.add_parser("accept", help="merge the task branch; the task goes to done")
    p_wacc.add_argument("id", help="task id or unique prefix")
    p_wacc.add_argument("--no-merge", action="store_true",
                        help="mark done without merging (already merged by hand)")
    p_wacc.add_argument("--no-validate", action="store_true",
                        help="skip validate.command on the merged result")
    p_wacc.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p_wacc.add_argument("--dry-run", action="store_true",
                        help="print what would happen, change nothing")
    p_ques = sub.add_parser("question", help="question commands: list, show, answer")
    ques_sub = p_ques.add_subparsers(dest="question_command", required=True)
    p_qlist = ques_sub.add_parser("list", help="list the open questions of every task")
    p_qshow = ques_sub.add_parser("show", help="show a question, or the latest round of a task")
    p_qshow.add_argument("id", metavar="TASK[/QID]", help="task id or prefix, optionally /QID")
    p_qans = ques_sub.add_parser(
        "answer", help="answer a question; the task resumes when none of the round is open")
    p_qans.add_argument("id", metavar="TASK[/QID]",
                        help="task id or prefix; /QID may be left out with one open question")
    p_qans.add_argument("text", nargs="?", help="the answer (or use --edit)")
    p_qans.add_argument("--edit", action="store_true", help="write the answer in $EDITOR")
    p_adr = sub.add_parser("adr", help="ADR commands: list, show, accept, reject, supersede")
    adr_sub = p_adr.add_subparsers(dest="adr_command", required=True)
    p_alist = adr_sub.add_parser("list", help="list accepted ADRs (--all: every status)")
    p_alist.add_argument("--all", action="store_true",
                         help="also show proposed, superseded and rejected ADRs")
    adr_parsers = [p_alist]
    for verb, text in (("show", "print one ADR"),
                       ("accept", "mark a proposed ADR accepted (edits the file, no commit)"),
                       ("reject", "mark a proposed ADR rejected (edits the file, no commit)"),
                       ("supersede", "mark an accepted ADR superseded by NEW (no commit)")):
        p_a = adr_sub.add_parser(verb, help=text)
        p_a.add_argument("number", metavar="N", help="ADR number: 3, 03 or 0003")
        if verb == "supersede":
            p_a.add_argument("new", metavar="NEW", help="number of the ADR that replaces N")
        adr_parsers.append(p_a)
    p_tretry = task_sub.add_parser("retry",help="send a stuck task back to its todo folder")
    p_tretry.add_argument("id", help="task id or unique prefix")
    p_tstop = task_sub.add_parser("stop", help="stop a running task; it goes to stuck until `task retry`")
    p_tstop.add_argument("id", help="task id or unique prefix")
    p_tdisc = task_sub.add_parser("discard", help="discard a task (asks for confirmation)")
    p_tdisc.add_argument("id", help="task id or unique prefix")
    p_tdisc.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    for p in (p_run, p_tnew, p_trans, p_tlist, p_tshow, p_pacc, p_prej,
              p_wrej, p_wacc, p_qlist, p_qshow, p_qans, p_tretry, p_tstop, p_tdisc, *adr_parsers):
        p.add_argument("--repo", type=Path, default=Path.cwd(),
                       help="repository root (default: current directory)")
    args = parser.parse_args(argv)
    if args.command == "question" and args.question_command == "answer" \
            and args.text is not None and args.edit:
        p_qans.error("give the answer text or --edit, not both")

    if args.command == "dev":  # only `transitions`; needs no repo or config
        print(render_markdown_table())
        return 0

    if args.command == "adr":  # plain files under docs/adr/: no WORKFLOW.md needed
        return cmd_adr(args)

    try:
        config = load_config(args.repo)
    except ConfigError as e:
        print(f"samba: config error: {e}", file=sys.stderr)
        return 2

    if args.command == "run":
        return cmd_run(config, args.exit_when_idle)
    command = str(args.command)
    if command == "plan":
        verb = str(args.plan_command)
        return cmd_transition(config, str(args.id), f"plan.{verb}", f"plan.{verb}",
                              feedback=cast(str | None, getattr(args, "feedback", None)),
                              edit=bool(getattr(args, "edit", False)),
                              feedback_mode="optional" if verb == "reject" else "none")
    if command == "work" and args.work_command == "accept":
        return cmd_work_accept(config, str(args.id), no_merge=bool(args.no_merge),
                               no_validate=bool(args.no_validate), yes=bool(args.yes),
                               dry_run=bool(args.dry_run))
    if command == "work":
        fresh = bool(args.fresh)
        return cmd_transition(config, str(args.id), "work.reject_fresh" if fresh else "work.reject",
                              "work.reject", feedback=cast(str | None, args.feedback),
                              edit=bool(args.edit), feedback_mode="optional")
    if command == "question":
        if args.question_command == "list":
            return cmd_question_list(config)
        if args.question_command == "show":
            return cmd_question_show(config, str(args.id))
        return cmd_question_answer(config, str(args.id), cast(str | None, args.text),
                                   bool(args.edit))
    if command == "task":
        command = str(args.task_command)
    if command == "retry":
        return cmd_transition(config, str(args.id), "task.retry", "task.retry", hints=True)
    if command == "stop":
        return cmd_transition(config, str(args.id), "task.stop", "task.stop")
    if command == "discard":
        return cmd_transition(config, str(args.id), "task.discard", "task.discard",
                              confirm_plan="Discard task {id}", yes=bool(args.yes))
    if command == "list":
        return cmd_task_list(config, cast(list[str], args.states))
    if command == "show":
        return cmd_task_show(config, str(args.id))
    return cmd_task_new(config, cast(str | None, args.title), cast(str | None, args.body),
                        cast(str | None, args.depends_on), int(args.priority),
                        bool(args.skip_plan))
