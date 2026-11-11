"""One thin use case per human command, named for what the person does (spec: cli, architecture).

Each takes plain values (the task id as typed, text, flags) and runs `ChangeState` with the event,
label and feedback mode of its command. A non-interactive caller passes `yes` or the text up front.
"""

from __future__ import annotations

from samba.app.change_state import ChangeState
from samba.app.results import Done, Refused


class AcceptPlan:
    def __init__(self, change_state: ChangeState) -> None:
        self.change_state = change_state

    def run(self, id: str) -> Done | Refused:
        return self.change_state.run(id, "plan.accept", "plan.accept")


class RejectPlan:
    def __init__(self, change_state: ChangeState) -> None:
        self.change_state = change_state

    def run(self, id: str, feedback: str | None = None, edit: bool = False) -> Done | Refused:
        return self.change_state.run(id, "plan.reject", "plan.reject", feedback=feedback,
                                     edit=edit, feedback_mode="optional")


class RejectWork:
    def __init__(self, change_state: ChangeState) -> None:
        self.change_state = change_state

    def run(self, id: str, feedback: str | None = None, edit: bool = False,
            fresh: bool = False) -> Done | Refused:
        """`fresh` also clears the session so the rework starts a new conversation."""
        event = "work.reject_fresh" if fresh else "work.reject"
        return self.change_state.run(id, event, "work.reject", feedback=feedback, edit=edit,
                                     feedback_mode="optional")


class RetryTask:
    def __init__(self, change_state: ChangeState) -> None:
        self.change_state = change_state

    def run(self, id: str) -> Done | Refused:
        return self.change_state.run(id, "task.retry", "task.retry", hints=True)


class StopTask:
    def __init__(self, change_state: ChangeState) -> None:
        self.change_state = change_state

    def run(self, id: str) -> Done | Refused:
        return self.change_state.run(id, "task.stop", "task.stop")


class DiscardTask:
    def __init__(self, change_state: ChangeState) -> None:
        self.change_state = change_state

    def run(self, id: str, yes: bool = False) -> Done | Refused:
        return self.change_state.run(id, "task.discard", "task.discard",
                                     confirm_plan="Discard task {id}", yes=yes)
