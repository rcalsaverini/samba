"""`ChangeState`: the command pattern of the human commands (spec: cli) and the single legality
check every command uses.

Check the event is legal, do the outside effect (feedback text), then `Machine.fire`. Nothing
else moves a task. Holds the repo lock while it changes anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from samba.app.confirm import confirm
from samba.app.machine import Machine
from samba.app.resolve import find_task
from samba.app.results import LOCK_BUSY, Done, Refused, refused, usage
from samba.domain.task import Task
from samba.domain.task_id import TaskId
from samba.domain.transitions import human_events
from samba.domain.ports import Lock, Tasks, Terminal


@dataclass(frozen=True)
class Legal:
    task: Task


@dataclass(frozen=True)
class NotAllowed:
    """No such task, or the event is not legal in its state. `message` has no `samba: `."""

    message: str


def check_legal(tasks: Tasks, task_id: TaskId, event: str, label: str) -> Legal | NotAllowed:
    """The one legality check: the task exists and `event` is a legal human event in its state."""
    task = tasks.get(task_id)
    if task is None:
        return NotAllowed(f"task {task_id!r} has no file")
    events = [r.event for r in human_events(task.status, task)]
    if event in events:
        return Legal(task)
    names = ", ".join(events) or "none"
    return NotAllowed(f"{task_id} is in {task.status}; {label} not allowed. Legal events: {names}")


def retry_hint(cause: str | None) -> str | None:
    if cause == "budget":
        return ("hint: raise the budget cap in WORKFLOW.md first (max_turns, max_attempts or "
                "max_cost_usd_per_task), or the task will go straight back to stuck")
    if cause in ("dependency_discarded", "dependency_cycle"):
        return ("hint: edit depends_on in the task file first, or the dependency check will "
                "send it back to stuck")
    return None


FeedbackMode = Literal["none", "optional", "required"]


class ChangeState:
    def __init__(self, tasks: Tasks, machine: Machine, terminal: Terminal,
                 lock: Lock) -> None:
        self.tasks = tasks
        self.machine = machine
        self.terminal = terminal
        self.lock = lock

    def run(self, id: str, event: str, label: str, *, feedback: str | None = None,
            edit: bool = False, feedback_mode: FeedbackMode = "none",
            confirm_plan: str | None = None, yes: bool = False,
            hints: bool = False) -> Done | Refused:
        """`id` is the task id or unique prefix as typed. `confirm_plan` marks a dangerous
        command: it asks after the legality check, before the lock."""
        tasks = self.tasks
        task_id = find_task(tasks, id)
        if isinstance(task_id, Refused):
            return task_id
        first = check_legal(tasks, task_id, event, label)
        if isinstance(first, NotAllowed):
            return refused(first.message)
        notes: list[str] = []
        if feedback_mode != "none" and edit:  # before the lock: editing can take long
            edited = self.terminal.edit("")
            if edited.text is None:
                return refused(edited.error or "editor failed")
            feedback = edited.text
        feedback = (feedback or "").strip()
        if not feedback and feedback_mode == "optional":
            notes.append("warning: rejecting without feedback")
        if not feedback and feedback_mode == "required":
            return usage(f"{label} needs text (argument or --edit); nothing changed")
        if confirm_plan is not None:
            declined = confirm(self.terminal, confirm_plan.format(id=task_id), label, yes)
            if declined is not None:
                return Refused(declined.kind, (*notes, *declined.messages))

        with self.lock.acquire() as held:
            if not held:
                return Refused("refused", (*notes, f"samba: {LOCK_BUSY}"))
            again = check_legal(tasks, task_id, event, label)  # a hand move may have raced in
            if isinstance(again, NotAllowed):
                return Refused("refused", (*notes, f"samba: {again.message}"))
            current = again.task
            cause = current.blocked_cause  # the row clears it
            message = ""
            if feedback:
                message = f"feedback round {current.add_feedback(feedback)}"
                tasks.save(current)  # written before the move, as the spec says
            if not self.machine.fire(task_id, event, message=message):
                note = "; the feedback was already written" if feedback else ""
                return Refused("refused", (*notes,
                                           f"samba: {event} did not apply to {task_id}{note}"))
        hint = retry_hint(cause) if hints else None
        if hint:
            notes.append(hint)
        location = tasks.location(task_id) if tasks.get(task_id) is not None else None
        return Done(location, tuple(notes))
