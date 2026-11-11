"""Command line: `samba run`, `samba explore`, and `<noun> <verb>` for task, plan, work, question, adr, dev (spec: cli).

Parse, one call, render: each leaf parser binds one call that passes plain values to one use case,
and `render` maps the closed result set to output and the exit code.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import signal
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar, cast

from samba.app.results import Done, Refused, Result, Table, Text, Written
from samba.app.startup import StartupError
from samba.bootstrap import AdrCommands, build, build_adr, build_explore, build_orchestrator
from samba.domain.settings import ConfigError
from samba.domain.transitions import render_markdown_table
from samba.entrypoints.table import print_table

T = TypeVar("T")
Handler = Callable[[argparse.Namespace], int]


def render(result: Result) -> int:
    """Print a result and return the exit code: 0, 1 for refused, 2 for usage."""
    if isinstance(result, Done):
        if result.location is not None:
            print(result.location)
        for line in result.notes:
            print(line, file=sys.stderr)
        return 0
    if isinstance(result, Table):
        print_table(result.rows, shutil.get_terminal_size().columns, flex=result.flex)
        return 0
    if isinstance(result, Text):
        sys.stdout.write(result.text)
        return 0
    if isinstance(result, Written):
        for file in result.files:
            print(file)
        return 0
    for line in result.messages:
        print(line, file=sys.stderr)
    return 2 if result.kind == "usage" else 1


def bind(p: argparse.ArgumentParser, make: Callable[[Path], T],
         call: Callable[[T, argparse.Namespace], Result]) -> None:
    """Bind the leaf parser `p` to one call: build the use cases of `make`, call one, return its result."""

    def handler(a: argparse.Namespace) -> int:
        return render(call(make(cast(Path, a.repo)), a))

    p.set_defaults(handler=handler)


def cmd_run(args: argparse.Namespace) -> int:
    """`run`: the orchestrator loop; not a use case, so outside the render contract."""
    orch = build_orchestrator(cast(Path, args.repo))
    exit_when_idle = bool(args.exit_when_idle)

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


def cmd_explore(args: argparse.Namespace) -> int:
    """`explore` (spec: cli, explore): run the `StartExplore` use case, exit with the session's code."""
    result = build_explore(cast(Path, args.repo)).run(cast(str | None, args.topic))
    if isinstance(result, Refused):
        return render(result)
    return result.exit_code


def cmd_dev_transitions(args: argparse.Namespace) -> int:
    """`dev transitions`: only prints the table; needs no repo or config."""
    print(render_markdown_table())
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
    p_run.set_defaults(handler=cmd_run)

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
    bind(p_tnew, build, lambda c, a: c.create_task.run(
        cast(str | None, a.title), cast(str | None, a.body), cast(str | None, a.depends_on),
        int(a.priority), bool(a.skip_plan)))
    p_tlist = task_sub.add_parser("list", help="list tasks, optionally filtered by state")
    add_list_args(p_tlist)
    bind(p_tlist, build, lambda c, a: c.list_tasks.run(cast(list[str], a.states)))
    p_tshow = task_sub.add_parser("show", help="show one task in detail")
    add_show_args(p_tshow)
    bind(p_tshow, build, lambda c, a: c.show_task.run(str(a.id)))
    p_dev = sub.add_parser("dev",  # no help=: it is listed in the epilog, apart from the others
                           description="Commands for working on Samba itself.")
    dev_sub = p_dev.add_subparsers(dest="dev_command", required=True)
    p_trans = dev_sub.add_parser("transitions",
                                 help="print the transition table as Markdown (spec: states)")
    p_trans.set_defaults(handler=cmd_dev_transitions)

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
    bind(p_pacc, build, lambda c, a: c.accept_plan.run(str(a.id)))
    p_prej = plan_sub.add_parser("reject", help="send the plan back; the task goes to plan-todo")
    add_reject_args(p_prej)
    bind(p_prej, build, lambda c, a: c.reject_plan.run(
        str(a.id), cast(str | None, a.feedback), bool(a.edit)))
    p_work = sub.add_parser("work", help="work review commands: accept, reject")
    work_sub = p_work.add_subparsers(dest="work_command", required=True)
    p_wrej = work_sub.add_parser("reject", help="send the work back; the task goes to work-todo")
    add_reject_args(p_wrej, fresh=True)
    bind(p_wrej, build, lambda c, a: c.reject_work.run(
        str(a.id), cast(str | None, a.feedback), bool(a.edit), bool(a.fresh)))
    p_wacc = work_sub.add_parser("accept", help="merge the task branch; the task goes to done")
    p_wacc.add_argument("id", help="task id or unique prefix")
    p_wacc.add_argument("--no-merge", action="store_true",
                        help="mark done without merging (already merged by hand)")
    p_wacc.add_argument("--no-validate", action="store_true",
                        help="skip validate.command on the merged result")
    p_wacc.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p_wacc.add_argument("--dry-run", action="store_true",
                        help="print what would happen, change nothing")
    bind(p_wacc, build, lambda c, a: asyncio.run(c.accept_work.run(
        str(a.id), no_merge=bool(a.no_merge), no_validate=bool(a.no_validate),
        yes=bool(a.yes), dry_run=bool(a.dry_run))))
    p_ques = sub.add_parser("question", help="question commands: list, show, answer")
    ques_sub = p_ques.add_subparsers(dest="question_command", required=True)
    p_qlist = ques_sub.add_parser("list", help="list the open questions of every task")
    bind(p_qlist, build, lambda c, a: c.list_questions.run())
    p_qshow = ques_sub.add_parser("show", help="show a question, or the latest round of a task")
    p_qshow.add_argument("id", metavar="TASK[/QID]", help="task id or prefix, optionally /QID")
    bind(p_qshow, build, lambda c, a: c.show_question.run(str(a.id)))
    p_qans = ques_sub.add_parser(
        "answer", help="answer a question; the task resumes when none of the round is open")
    p_qans.add_argument("id", metavar="TASK[/QID]",
                        help="task id or prefix; /QID may be left out with one open question")
    p_qans.add_argument("text", nargs="?", help="the answer (or use --edit)")
    p_qans.add_argument("--edit", action="store_true", help="write the answer in $EDITOR")
    bind(p_qans, build, lambda c, a: c.answer_question.run(
        str(a.id), cast(str | None, a.text), bool(a.edit)))

    def check_answer(a: argparse.Namespace) -> None:
        if a.text is not None and a.edit:
            p_qans.error("give the answer text or --edit, not both")

    p_qans.set_defaults(validate=check_answer)
    p_adr = sub.add_parser("adr", help="ADR commands: list, show, accept, reject, supersede")
    adr_sub = p_adr.add_subparsers(dest="adr_command", required=True)
    p_alist = adr_sub.add_parser("list", help="list accepted ADRs (--all: every status)")
    p_alist.add_argument("--all", action="store_true",
                         help="also show proposed, superseded and rejected ADRs")
    bind(p_alist, build_adr, lambda c, a: c.list.run(bool(a.all)))
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

    def adr_call(verb: str) -> Callable[[AdrCommands, argparse.Namespace], Result]:
        if verb == "show":
            return lambda c, a: c.show.run(str(a.number))
        if verb == "supersede":
            return lambda c, a: c.supersede.run(str(a.number), str(a.new))
        return lambda c, a: c.set_status.run(verb, str(a.number))

    for verb, p_a in zip(("show", "accept", "reject", "supersede"), adr_parsers[1:]):
        bind(p_a, build_adr, adr_call(verb))
    p_expl = sub.add_parser("explore", help="start an interactive session to explore a topic and "
                                            "write ADRs")
    p_expl.add_argument("topic", nargs="?", metavar="TOPIC", help="what to explore (first prompt)")
    p_expl.set_defaults(handler=cmd_explore)
    p_tretry = task_sub.add_parser("retry",help="send a stuck task back to its todo folder")
    p_tretry.add_argument("id", help="task id or unique prefix")
    bind(p_tretry, build, lambda c, a: c.retry_task.run(str(a.id)))
    p_tstop = task_sub.add_parser("stop", help="stop a running task; it goes to stuck until `task retry`")
    p_tstop.add_argument("id", help="task id or unique prefix")
    bind(p_tstop, build, lambda c, a: c.stop_task.run(str(a.id)))
    p_tdisc = task_sub.add_parser("discard", help="discard a task (asks for confirmation)")
    p_tdisc.add_argument("id", help="task id or unique prefix")
    p_tdisc.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    bind(p_tdisc, build, lambda c, a: c.discard_task.run(str(a.id), bool(a.yes)))
    for p in (p_run, p_expl, p_tnew, p_trans, p_tlist, p_tshow, p_pacc, p_prej,
              p_wrej, p_wacc, p_qlist, p_qshow, p_qans, p_tretry, p_tstop, p_tdisc, *adr_parsers):
        p.add_argument("--repo", type=Path, default=Path.cwd(),
                       help="repository root (default: current directory)")
    args = parser.parse_args(argv)
    validate = cast("Callable[[argparse.Namespace], None] | None", getattr(args, "validate", None))
    if validate is not None:
        validate(args)
    try:
        return cast(Handler, args.handler)(args)
    except ConfigError as e:
        print(f"samba: config error: {e}", file=sys.stderr)
        return 2
