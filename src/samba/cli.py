"""Command line: `samba run`, and `<noun> <verb>` for task, plan, work, question, adr, dev (spec: cli)."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal, cast

from samba import adr as adr_mod
from samba import merge, workspace
from samba.adapters.system import SystemClock
from samba.config import Config, ConfigError, load_config
from samba.lock import repo_lock
from samba.orchestrator import Orchestrator, StartupError
from samba.domain.legacy_questions import (
    Question,
    answer_question,
    open_questions,
    qint,
    qstr,
    round_questions,
)
from samba.domain.states import STATES, State
from samba.domain.transitions import human_events, log_line, render_markdown_table
from samba.tasks import SidecarStore, TaskStore
from samba.transitions import Machine
from samba.views import (
    ResolveError,
    print_table,
    question_rows,
    render_show,
    resolve_states,
    resolve_task_id,
    task_rows,
)


def _setup_logging(config: Config) -> None:
    config.samba_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger("samba")
    root.setLevel(logging.DEBUG)
    file_handler = logging.FileHandler(config.samba_dir / "samba.log")
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
    tasks = TaskStore(config.samba_dir / "tasks")
    sidecars = SidecarStore(config.samba_dir / "state")
    print_table(task_rows(tasks, sidecars, chosen), shutil.get_terminal_size().columns, flex=6)
    return 0


def cmd_task_show(config: Config, text: str) -> int:
    tasks = TaskStore(config.samba_dir / "tasks")
    sidecars = SidecarStore(config.samba_dir / "state")
    try:
        task = tasks.find(resolve_task_id(tasks, text))
    except ResolveError as e:
        print(f"samba: {e.render()}", file=sys.stderr)
        return 2
    if task is None:
        print(f"samba: unknown task {text!r}", file=sys.stderr)
        return 2
    print("\n".join(render_show(tasks, task, sidecars.load(task.id))))
    return 0


def _edit_feedback() -> str | None:
    """Collect text in `$EDITOR` (then `$VISUAL`, then `vi`). None if the editor failed."""
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "feedback.md"
        path.write_text("")
        try:
            res = subprocess.run([*shlex.split(editor), str(path)])
        except OSError as e:
            print(f"samba: cannot run editor {editor!r}: {e}", file=sys.stderr)
            return None
        if res.returncode != 0:
            print(f"samba: editor exited with {res.returncode}; nothing changed",
                  file=sys.stderr)
            return None
        return path.read_text().strip()


def confirm(prompt: str, command: str, yes: bool) -> int | None:
    """The confirmation policy of dangerous commands (spec: cli). Returns the exit code to stop
    with, or None to proceed: `--yes` skips; without a terminal exit 2; else ask `[y/N]`."""
    if yes:
        return None
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print(f"samba: {command} needs confirmation: run it on a terminal or pass --yes; "
              "nothing changed", file=sys.stderr)
        return 2
    print(f"{prompt}? [y/N] ", end="", flush=True)
    if sys.stdin.readline().strip().lower() not in ("y", "yes"):
        print("samba: not confirmed; nothing changed", file=sys.stderr)
        return 1
    return None


def _retry_hint(cause: str | None) -> str | None:
    if cause == "budget":
        return ("hint: raise the budget cap in WORKFLOW.md first (max_turns, max_attempts or "
                "max_cost_usd_per_task), or the task will go straight back to stuck")
    if cause in ("dependency_discarded", "dependency_cycle"):
        return ("hint: edit depends_on in the task file first, or the dependency check will "
                "send it back to stuck")
    return None


def cmd_transition(config: Config, text: str, event: str, label: str, *,
                   feedback: str | None = None, edit: bool = False,
                   feedback_mode: Literal["none", "optional", "required"] = "none",
                   confirm_plan: str | None = None, yes: bool = False,
                   hints: bool = False) -> int:
    """The command pattern (spec: cli): resolve, check the event is legal, do the outside effect
    (feedback text), then `Machine.fire`. Nothing else moves a task. Holds the repo lock.
    `confirm_plan` marks a dangerous command (asks after the legality check, before the lock)."""
    tasks = TaskStore(config.samba_dir / "tasks")
    sidecars = SidecarStore(config.samba_dir / "state")
    takes_feedback = feedback_mode != "none"

    def legal(task_id: str) -> State | None:
        """The task's state if `event` is legal there, else report and return None."""
        state = tasks.state_of(task_id)
        if state is None:
            print(f"samba: task {task_id!r} has no file", file=sys.stderr)
            return None
        events = [r.event for r in human_events(state, sidecars.load(task_id))]
        if event in events:
            return state
        names = ", ".join(events) or "none"
        print(f"samba: {task_id} is in {state}; {label} not allowed. Legal events: {names}",
              file=sys.stderr)
        return None

    try:
        task_id = resolve_task_id(tasks, text)
    except ResolveError as e:
        print(f"samba: {e.render()}", file=sys.stderr)
        return 2
    if legal(task_id) is None:
        return 1
    if takes_feedback and edit:  # before the lock: editing can take long
        feedback = _edit_feedback()
        if feedback is None:
            return 1
    feedback = (feedback or "").strip()
    if not feedback and feedback_mode == "optional":
        print("warning: rejecting without feedback", file=sys.stderr)
    if not feedback and feedback_mode == "required":
        print(f"samba: {label} needs text (argument or --edit); nothing changed",
              file=sys.stderr)
        return 2
    if confirm_plan is not None:
        code = confirm(confirm_plan.format(id=task_id), label, yes)
        if code is not None:
            return code

    with repo_lock(config.samba_dir) as held:
        if not held:
            print("samba: another command or the orchestrator holds .samba/lock; "
                  "try again", file=sys.stderr)
            return 1
        if legal(task_id) is None:  # re-check: a hand move may have raced in
            return 1
        cause = sidecars.load(task_id).blocked_cause  # the row clears it
        tasks.ensure()  # the destination folder may not exist yet
        message = ""
        if feedback:
            n = tasks.append_feedback(task_id, feedback)
            message = f"feedback round {n}"
        if not Machine(tasks, sidecars, SystemClock()).fire(task_id, event, message=message):
            note = "; the feedback was already written" if feedback else ""
            print(f"samba: {event} did not apply to {task_id}{note}", file=sys.stderr)
            return 1
    state = tasks.state_of(task_id)
    if state is not None:
        print(tasks.path(task_id, state))
    hint = _retry_hint(cause) if hints else None
    if hint:
        print(hint, file=sys.stderr)
    return 0


def _err(msg: str) -> None:
    print(f"samba: {msg}", file=sys.stderr)


def _split_target(target: str) -> tuple[str, str | None]:
    """`TASK` or `TASK/QID`. Task ids never contain a slash."""
    task, sep, qid = target.rpartition("/")
    return (task, qid) if sep else (target, None)


def cmd_question_list(config: Config) -> int:
    tasks = TaskStore(config.samba_dir / "tasks")
    sidecars = SidecarStore(config.samba_dir / "state")
    print_table(question_rows(tasks, sidecars), shutil.get_terminal_size().columns, flex=4)
    return 0


def cmd_question_show(config: Config, target: str) -> int:
    tasks = TaskStore(config.samba_dir / "tasks")
    sidecars = SidecarStore(config.samba_dir / "state")
    name, qid = _split_target(target)
    try:
        task_id = resolve_task_id(tasks, name)
    except ResolveError as e:
        _err(e.render())
        return 2
    questions = sidecars.load(task_id).questions
    shown = [q for q in questions if qstr(q, "id") == qid] if qid else round_questions(questions)
    if not shown:
        _err(f"unknown question {task_id}/{qid}" if qid else f"{task_id} has no questions")
        return 2
    blocks: list[str] = []
    for q in shown:
        lines = [f"{task_id}/{qstr(q, 'id')}  stage: {qstr(q, 'stage')}  round: {qint(q, 'round')}"
                 f"  status: {qstr(q, 'status')}  asked: {qstr(q, 'asked_at')}",
                 "", qstr(q, "text")]
        if qstr(q, "context"):
            lines += ["", "Context: " + qstr(q, "context")]
        if q.get("status") == "answered":
            lines += ["", "Answer: " + qstr(q, "answer")]
        blocks.append("\n".join(lines))
    print("\n\n".join(blocks))
    return 0


def _edit_answer(q: Question) -> str | None:
    """Collect an answer in `$EDITOR` with the question quoted as `# ` comment lines, which are
    stripped. None if the editor failed."""
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    shown = f"{qstr(q, 'id')}: {qstr(q, 'text')}"
    if qstr(q, "context"):
        shown += f"\n\nContext: {qstr(q, 'context')}"
    head = "\n".join(f"# {ln}" if ln else "#" for ln in shown.splitlines())
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "answer.md"
        path.write_text(head + "\n\n")
        try:
            res = subprocess.run([*shlex.split(editor), str(path)])
        except OSError as e:
            _err(f"cannot run editor {editor!r}: {e}")
            return None
        if res.returncode != 0:
            _err(f"editor exited with {res.returncode}; nothing changed")
            return None
        kept = [ln for ln in path.read_text().splitlines() if ln != "#" and not ln.startswith("# ")]
        return "\n".join(kept).strip()


def cmd_question_answer(config: Config, target: str, text: str | None, edit: bool) -> int:
    """`question answer` (spec: cli): records the answer at once; fires `question.answer` only when
    no question of the round is still open."""
    tasks = TaskStore(config.samba_dir / "tasks")
    sidecars = SidecarStore(config.samba_dir / "state")
    event = "question.answer"
    name, qid = _split_target(target)

    def check(task_id: str) -> Question | int:
        """The question to answer, or the exit code after reporting the problem."""
        state = tasks.state_of(task_id)
        if state is None:
            _err(f"task {task_id!r} has no file")
            return 1
        side = sidecars.load(task_id)
        events = [r.event for r in human_events(state, side)]
        if event not in events:
            _err(f"{task_id} is in {state}; question.answer not allowed. Legal events: "
                 f"{', '.join(events) or 'none'}")
            return 1
        open_qs = open_questions(side.questions)
        if qid is None:
            if len(open_qs) == 1:
                return open_qs[0]
            if not open_qs:
                _err(f"{task_id} has no open question; nothing changed")
                return 1
            _err(f"{task_id} has {len(open_qs)} open questions; name one as "
                 f"{task_id}/QID. Open:\n" + "\n".join(f"  {task_id}/{qstr(q, 'id')}"
                                                       for q in open_qs))
            return 2
        found = next((q for q in side.questions if qstr(q, "id") == qid), None)
        if found is None:
            _err(f"unknown question {task_id}/{qid}")
            return 2
        if found.get("status") != "open":
            _err(f"{task_id}/{qid} is {qstr(found, 'status')}, not open; nothing changed")
            return 1
        return found

    try:
        task_id = resolve_task_id(tasks, name)
    except ResolveError as e:
        _err(e.render())
        return 2
    q = check(task_id)
    if isinstance(q, int):
        return q
    answer = text
    if edit:  # before the lock: editing can take long
        answer = _edit_answer(q)
        if answer is None:
            return 1
    answer = (answer or "").strip()
    if not answer:
        _err("question answer needs text (argument or --edit); nothing changed")
        return 2

    with repo_lock(config.samba_dir) as held:
        if not held:
            _err("another command or the orchestrator holds .samba/lock; try again")
            return 1
        q = check(task_id)  # re-check: a hand move or another answer may have raced in
        if isinstance(q, int):
            return q
        side = sidecars.load(task_id)
        record = next(r for r in side.questions if qstr(r, "id") == qstr(q, "id"))
        clock = SystemClock()
        answer_question(record, answer, clock)
        sidecars.save(task_id, side)
        tasks.render_questions(task_id, side.questions)
        tasks.append_log(task_id, log_line(f"{event}: {task_id}/{qstr(record, 'id')} answered",
                                           clock))
        left = [r for r in open_questions(round_questions(side.questions))]
        if not left:
            tasks.ensure()
            if not Machine(tasks, sidecars, clock).fire(task_id, event):
                _err(f"{event} did not apply to {task_id}; the answer was recorded")
                return 1
    state = tasks.state_of(task_id)
    if state is not None:
        print(tasks.path(task_id, state))
    if left:
        _err(f"{len(left)} question(s) still open: " + ", ".join(
            f"{task_id}/{qstr(r, 'id')}" for r in left))
    return 0


def cmd_work_accept(config: Config, text: str, *, no_merge: bool, no_validate: bool, yes: bool,
                    dry_run: bool) -> int:
    """`work accept` (spec: cli): the command pattern with a merge as the outside effect."""
    tasks = TaskStore(config.samba_dir / "tasks")
    sidecars = SidecarStore(config.samba_dir / "state")
    event = "work.accept"

    def err(msg: str) -> None:
        print(f"samba: {msg}", file=sys.stderr)

    def check(task_id: str) -> bool:
        """State and preflight checks; reports the failure."""
        state = tasks.state_of(task_id)
        if state is None:
            err(f"task {task_id!r} has no file")
            return False
        events = [r.event for r in human_events(state, sidecars.load(task_id))]
        if event not in events:
            err(f"{task_id} is in {state}; {event} not allowed. Legal events: "
                f"{', '.join(events) or 'none'}")
            return False
        if not no_merge:
            problem = merge.preflight(config.repo, config.base_branch, branch)
            if problem:
                err(f"{problem}; nothing changed")
                return False
        return True

    try:
        task_id = resolve_task_id(tasks, text)
    except ResolveError as e:
        err(e.render())
        return 2
    branch = workspace.branch_name(task_id)
    base = config.base_branch
    if not check(task_id):
        return 1
    do_validate = not no_merge and not no_validate and config.validate_command is not None
    count = 0 if no_merge else merge.commit_count(config.repo, base, branch)
    plural = "" if count == 1 else "s"
    if no_merge:
        plan = f"Mark {task_id} done without merging (--no-merge)"
    else:
        plan = f"Merge {branch} into {base} ({count} commit{plural})"
        if do_validate:
            plan += f", then validate with `{config.validate_command}`"
    if dry_run:
        print(f"{plan}")
        print(f"branch: {branch}\nbase: {base}\ncommits: {count}")
        print(f"merge: {'no' if no_merge else 'yes (--no-ff)'}")
        print(f"validate: {config.validate_command if do_validate else 'skipped'}")
        print("final state: done")
        return 0
    code = confirm(plan, "work accept", yes)
    if code is not None:
        return code

    with repo_lock(config.samba_dir) as held:
        if not held:
            err("another command or the orchestrator holds .samba/lock; try again")
            return 1
        if not check(task_id):
            return 1
        message = "validation skipped" if no_validate else ""
        if no_merge:
            message = "no merge"
        else:
            task = tasks.find(task_id)
            title = task.title if task else task_id
            res = merge.merge_branch(
                config.repo, branch, f"Merge {branch}: {title}", shell=config.shell,
                validate_command=config.validate_command if do_validate else None,
                timeout_s=config.validate_timeout_s, tail_lines=config.validate_tail_lines,
                log_path=config.samba_dir / "runs" / task_id / "accept-validate.log")
            if res.status == "conflict":
                tasks.append_log(task_id, f"work.accept: merge failed (conflicts: {res.detail})")
                err(f"merge conflict in: {res.detail}; merge aborted, task stays in work-review")
                return 1
            if res.status == "error":
                tasks.append_log(task_id, f"work.accept: merge failed ({res.detail})")
                err(f"merge failed: {res.detail}; merge aborted, task stays in work-review")
                return 1
            if res.status == "validation_failed":
                tasks.append_log(task_id,
                                 f"work.accept: validation failed after merge: {res.detail}")
                err(f"validation failed after merge; merge aborted, task stays in work-review: "
                    f"{res.detail}")
                err(f"full output: {res.log_path}")
                return 1
            if res.status == "already":
                err(f"{branch} is already merged into {base}; nothing to merge")
                message = "already merged"
            else:
                message = f"merged {res.detail}" + (
                    ", validated" if res.validated else ", validation skipped" if no_validate
                    else "")
                if config.validate_command is None:
                    err("no validate.command; merged without validation")
        tasks.ensure()
        if not Machine(tasks, sidecars, SystemClock()).fire(task_id, event, message=message):
            err(f"{event} did not apply to {task_id}"
                + ("" if no_merge else f" after the merge ({message}); the merge is in {base}"))
            return 1
    state = tasks.state_of(task_id)
    if state is not None:
        print(tasks.path(task_id, state))
    return 0


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60].strip("-") or "task"


DEPENDS_PROMPT = "Depends on (ids or prefixes, comma separated, empty for none): "


def _resolve_deps(tasks: TaskStore, text: str) -> list[str]:
    """Comma separated ids or prefixes to full ids, in order, without repeats. Raises ResolveError."""
    ids: list[str] = []
    for part in text.split(","):
        part = part.strip()
        if part:
            found = resolve_task_id(tasks, part)
            if found not in ids:
                ids.append(found)
    return ids


def _ask(prompt: str) -> str:
    """One line from stdin after `prompt`. EOF ends the whole command (exit 1)."""
    print(prompt, end="", flush=True)
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    return line.rstrip("\r\n")


def cmd_task_new(config: Config, title: str | None, body: str | None, depends: str | None,
                 priority: int, skip_plan: bool) -> int:
    """`task new` (spec: cli): flags give every field; on a terminal the missing ones are asked."""
    tasks = TaskStore(config.samba_dir / "tasks")
    tty = sys.stdin.isatty() and sys.stdout.isatty()
    if title is None and not tty:
        print("samba: task new needs a TITLE (or run it on a terminal to be asked); "
              "usage: samba task new TITLE [--body TEXT] [--depends-on IDS] [--priority N] "
              "[--skip-plan]", file=sys.stderr)
        return 2
    dep_ids: list[str] = []
    if depends is not None:  # by flag: errors are fatal
        try:
            dep_ids = _resolve_deps(tasks, depends)
        except ResolveError as e:
            print(f"samba: {e.render()}", file=sys.stderr)
            return 2
    if tty:
        try:
            while not (title or "").strip():
                title = _ask("Title: ").strip()
            if body is None:
                lines: list[str] = []
                print("Description (end with an empty line):", flush=True)
                while True:
                    line = sys.stdin.readline().rstrip("\r\n")
                    if not line:  # an empty line or EOF
                        break
                    lines.append(line)
                body = "\n".join(lines)
            if depends is None:
                while True:
                    try:
                        dep_ids = _resolve_deps(tasks, _ask(DEPENDS_PROMPT))
                        break
                    except ResolveError as e:
                        print(f"samba: {e.render()}", file=sys.stderr)
            if not skip_plan:
                skip_plan = _ask("Plan first? [Y/n] ").strip().lower() in ("n", "no")
        except EOFError:
            print("samba: input ended; nothing created", file=sys.stderr)
            return 1
    assert title is not None
    title = title.strip()
    tasks.ensure()
    base = slugify(title)
    task_id, n = base, 2
    while tasks.state_of(task_id) is not None:
        task_id, n = f"{base}-{n}", n + 1
    front: dict[str, object] = {"priority": priority}
    if dep_ids:
        front["depends_on"] = dep_ids
    text = "---\n" + "".join(f"{k}: {json.dumps(v)}\n" for k, v in front.items()) + "---\n"
    text += f"# {title}\n\n"
    if body and body.strip():
        text += body.rstrip("\n") + "\n"
    path = tasks.path(task_id, "work-todo" if skip_plan else "plan-todo")
    path.write_text(text)
    print(path)
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
