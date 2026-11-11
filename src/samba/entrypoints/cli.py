"""Command line on Typer: `samba run`, `samba explore`, and `<noun> <verb>` for task, plan, work,
question, adr, dev (spec: cli).

Each command is a function whose signature declares its arguments and options. It builds the use
cases through `bootstrap`, calls one, and `render` maps the closed result set to output and the
exit code. No rule lives here.
"""

import asyncio
import shutil
import signal
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from typer.core import TyperGroup

from samba.app.results import Done, Refused, Result, Table, Text, Written
from samba.app.startup import StartupError
from samba.bootstrap import build, build_adr, build_explore, build_orchestrator
from samba.domain.settings import ConfigError
from samba.domain.transitions import render_markdown_table
from samba.entrypoints.table import print_table

ORDER = ("run", "task", "plan", "work", "question", "adr", "explore", "dev")


class OrderedGroup(TyperGroup):
    """Lists the commands in the order of `ORDER`, not commands first and groups after."""

    def list_commands(self, ctx: Any) -> list[str]:
        return [n for n in ORDER if n in self.commands]


Repo = Annotated[Path | None, typer.Option("--repo", show_default=False,
                                           help="repository root (default: current directory)")]
Id = Annotated[str, typer.Argument(metavar="ID", help="task id or unique prefix")]
TaskQid = Annotated[str, typer.Argument(metavar="TASK[/QID]", help="task id or prefix, optionally /QID")]
AdrNumber = Annotated[str, typer.Argument(metavar="N", help="ADR number: 3, 03 or 0003")]
Yes = Annotated[bool, typer.Option("--yes", help="skip the confirmation prompt")]
Feedback = Annotated[str | None, typer.Option("--feedback", metavar="TEXT", help="feedback for the agent")]
Edit = Annotated[bool, typer.Option("--edit", help="write the feedback in $EDITOR")]

CONTEXT = {"help_option_names": ["-h", "--help"]}


def make_app(help: str | None = None, **kwargs: Any) -> typer.Typer:
    return typer.Typer(help=help, rich_markup_mode=None, pretty_exceptions_enable=False,
                       context_settings=CONTEXT, **kwargs)


app = make_app(
    cls=OrderedGroup,
    epilog="\b\ndevelopment commands:\n    dev    commands for working on Samba itself "
           "(dev transitions)")
task_app = make_app("task commands: new, list, show, retry, stop, discard")
plan_app = make_app("plan review commands: accept, reject")
work_app = make_app("work review commands: accept, reject")
question_app = make_app("question commands: list, show, answer")
adr_app = make_app("ADR commands: list, show, accept, reject, supersede")
dev_app = make_app("Commands for working on Samba itself.")
app.add_typer(task_app, name="task")
app.add_typer(plan_app, name="plan")
app.add_typer(work_app, name="work")
app.add_typer(question_app, name="question")
app.add_typer(adr_app, name="adr")
app.add_typer(dev_app, name="dev", hidden=True)


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


def finish(result: Result) -> None:
    """Print the result and leave with its exit code."""
    code = render(result)
    if code:
        raise typer.Exit(code)


def root(repo: Path | None) -> Path:
    return repo if repo is not None else Path.cwd()


def exclusive(feedback: str | None, edit: bool) -> None:
    if feedback is not None and edit:
        raise typer.BadParameter("give --feedback or --edit, not both")


@app.command("run")
def run_cmd(
    exit_when_idle: Annotated[bool, typer.Option(
        "--exit-when-idle",
        help="exit once nothing is running and plan-todo/ and work-todo/ are empty")] = False,
    repo: Repo = None,
) -> None:
    """run the orchestrator loop"""
    orch = build_orchestrator(root(repo))

    async def loop_forever() -> None:
        loop = asyncio.get_running_loop()
        current = asyncio.current_task()
        assert current is not None
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, current.cancel)
        await orch.run(exit_when_idle=exit_when_idle)

    try:
        asyncio.run(loop_forever())
    except StartupError as e:
        print(f"samba: {e}", file=sys.stderr)
        raise typer.Exit(1)
    except asyncio.CancelledError:
        print("samba: stopped", file=sys.stderr)


@app.command("explore")
def explore_cmd(
    topic: Annotated[str | None, typer.Argument(metavar="TOPIC", help="what to explore (first prompt)")] = None,
    repo: Repo = None,
) -> None:
    """start an interactive session to explore a topic and write ADRs"""
    result = build_explore(root(repo)).run(topic)
    if isinstance(result, Refused):
        finish(result)
    elif result.exit_code:
        raise typer.Exit(result.exit_code)


@dev_app.command("transitions")
def dev_transitions(repo: Repo = None) -> None:
    """print the transition table as Markdown (spec: states)"""
    print(render_markdown_table())


@task_app.command("new")
def task_new(
    title: Annotated[str | None, typer.Argument(metavar="TITLE")] = None,
    body: Annotated[str | None, typer.Option("--body", metavar="TEXT", help="the task description")] = None,
    depends_on: Annotated[str | None, typer.Option(
        "--depends-on", metavar="IDS", help="comma separated task ids or unique prefixes")] = None,
    priority: Annotated[int, typer.Option("--priority", help="priority (default: 3)")] = 3,
    skip_plan: Annotated[bool, typer.Option(
        "--skip-plan", help="create the task in work-todo/ instead of plan-todo/")] = False,
    repo: Repo = None,
) -> None:
    """create a task (asks for missing fields on a terminal)"""
    finish(build(root(repo)).create_task.run(title, body, depends_on, priority, skip_plan))


@task_app.command("list")
def task_list(
    states: Annotated[list[str] | None, typer.Argument(
        metavar="[STATE]...", help="state names or unique prefixes (default: all)")] = None,
    repo: Repo = None,
) -> None:
    """list tasks, optionally filtered by state"""
    finish(build(root(repo)).list_tasks.run(states or []))


@task_app.command("show")
def task_show(id: Id, repo: Repo = None) -> None:
    """show one task in detail"""
    finish(build(root(repo)).show_task.run(id))


@task_app.command("retry")
def task_retry(id: Id, repo: Repo = None) -> None:
    """send a stuck task back to its todo folder"""
    finish(build(root(repo)).retry_task.run(id))


@task_app.command("stop")
def task_stop(id: Id, repo: Repo = None) -> None:
    """stop a running task; it goes to stuck until `task retry`"""
    finish(build(root(repo)).stop_task.run(id))


@task_app.command("discard")
def task_discard(id: Id, yes: Yes = False, repo: Repo = None) -> None:
    """discard a task (asks for confirmation)"""
    finish(build(root(repo)).discard_task.run(id, yes))


@plan_app.command("accept")
def plan_accept(id: Id, repo: Repo = None) -> None:
    """approve the plan; the task goes to work-todo"""
    finish(build(root(repo)).accept_plan.run(id))


@plan_app.command("reject")
def plan_reject(id: Id, feedback: Feedback = None, edit: Edit = False, repo: Repo = None) -> None:
    """send the plan back; the task goes to plan-todo"""
    exclusive(feedback, edit)
    finish(build(root(repo)).reject_plan.run(id, feedback, edit))


@work_app.command("reject")
def work_reject(
    id: Id, feedback: Feedback = None, edit: Edit = False,
    fresh: Annotated[bool, typer.Option(
        "--fresh", help="also clear the session so rework starts a fresh conversation")] = False,
    repo: Repo = None,
) -> None:
    """send the work back; the task goes to work-todo"""
    exclusive(feedback, edit)
    finish(build(root(repo)).reject_work.run(id, feedback, edit, fresh))


@work_app.command("accept")
def work_accept(
    id: Id,
    no_merge: Annotated[bool, typer.Option(
        "--no-merge", help="mark done without merging (already merged by hand)")] = False,
    no_validate: Annotated[bool, typer.Option(
        "--no-validate", help="skip validate.command on the merged result")] = False,
    yes: Yes = False,
    dry_run: Annotated[bool, typer.Option(
        "--dry-run", help="print what would happen, change nothing")] = False,
    repo: Repo = None,
) -> None:
    """merge the task branch; the task goes to done"""
    finish(asyncio.run(build(root(repo)).accept_work.run(
        id, no_merge=no_merge, no_validate=no_validate, yes=yes, dry_run=dry_run)))


@question_app.command("list")
def question_list(repo: Repo = None) -> None:
    """list the open questions of every task"""
    finish(build(root(repo)).list_questions.run())


@question_app.command("show")
def question_show(id: TaskQid, repo: Repo = None) -> None:
    """show a question, or the latest round of a task"""
    finish(build(root(repo)).show_question.run(id))


@question_app.command("answer")
def question_answer(
    id: Annotated[str, typer.Argument(
        metavar="TASK[/QID]", help="task id or prefix; /QID may be left out with one open question")],
    text: Annotated[str | None, typer.Argument(help="the answer (or use --edit)")] = None,
    edit: Annotated[bool, typer.Option("--edit", help="write the answer in $EDITOR")] = False,
    repo: Repo = None,
) -> None:
    """answer a question; the task resumes when none of the round is open"""
    if text is not None and edit:
        raise typer.BadParameter("give the answer text or --edit, not both")
    finish(build(root(repo)).answer_question.run(id, text, edit))


@adr_app.command("list")
def adr_list(
    all: Annotated[bool, typer.Option(
        "--all", help="also show proposed, superseded and rejected ADRs")] = False,
    repo: Repo = None,
) -> None:
    """list accepted ADRs (--all: every status)"""
    finish(build_adr(root(repo)).list.run(all))


@adr_app.command("show")
def adr_show(number: AdrNumber, repo: Repo = None) -> None:
    """print one ADR"""
    finish(build_adr(root(repo)).show.run(number))


@adr_app.command("accept")
def adr_accept(number: AdrNumber, repo: Repo = None) -> None:
    """mark a proposed ADR accepted (edits the file, no commit)"""
    finish(build_adr(root(repo)).set_status.run("accept", number))


@adr_app.command("reject")
def adr_reject(number: AdrNumber, repo: Repo = None) -> None:
    """mark a proposed ADR rejected (edits the file, no commit)"""
    finish(build_adr(root(repo)).set_status.run("reject", number))


@adr_app.command("supersede")
def adr_supersede(
    number: AdrNumber,
    new: Annotated[str, typer.Argument(metavar="NEW", help="number of the ADR that replaces N")],
    repo: Repo = None,
) -> None:
    """mark an accepted ADR superseded by NEW (no commit)"""
    finish(build_adr(root(repo)).supersede.run(number, new))


def main(argv: list[str] | None = None) -> int:
    try:
        app(args=argv, prog_name="samba")
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except ConfigError as e:
        print(f"samba: config error: {e}", file=sys.stderr)
        return 2
    return 0
