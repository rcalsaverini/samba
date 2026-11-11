"""In-memory `Tasks` for tests: the same stale-save rules as `MarkdownTasks`, no files.

Records are kept as private copies, so a `Task` handed out is a working copy, like a loaded one.
"""

from __future__ import annotations

import copy
import weakref
from dataclasses import fields

from samba.domain.questions import merge_questions
from samba.domain.states import STATES, State
from samba.domain.task import FeedbackRound, ObservedMove, Task
from samba.domain.task_id import TaskId
from samba.domain.ports import TaskExists

SCALARS = (
    "session_id", "last_stage", "blocked_cause", "plan_session_id", "plan_approved", "attempts",
    "not_before", "last_error", "last_outcome", "turns_total", "cost_usd_total",
    "input_tokens_total", "output_tokens_total", "branch", "workspace", "first_dispatched_at",
    "queued_at",
)


class FakeTasks:
    def __init__(self) -> None:
        self.records: dict[TaskId, Task] = {}
        self.recorded: dict[TaskId, State] = {}  # last known status, for hand moves
        self.rejected: dict[State, list[str]] = {}
        self._snapshots: weakref.WeakKeyDictionary[Task, Task] = weakref.WeakKeyDictionary()

    def _out(self, task: Task) -> Task:
        out = copy.deepcopy(task)
        self._snapshots[out] = copy.deepcopy(task)
        return out

    def hand_move(self, id: TaskId, dst: State) -> None:
        """Test helper: a human moves the file."""
        self.records[id].status = dst

    def prepare(self) -> None:
        pass

    def location(self, id: TaskId) -> str:
        return f"fake://{id}"

    def get(self, id: TaskId) -> Task | None:
        t = self.records.get(id)
        return self._out(t) if t is not None else None

    def list(self, status: State) -> list[Task]:
        return [self._out(t) for _, t in sorted(self.records.items()) if t.status == status]

    def ids(self, status: State | None = None) -> list[TaskId]:
        return [i for s in STATES if status in (None, s)
                for i, t in sorted(self.records.items()) if t.status == s]

    def rejected_names(self, status: State) -> list[str]:
        return list(self.rejected.get(status, []))

    def create(self, task: Task) -> None:
        if task.id in self.records:
            raise TaskExists(f"task {task.id} exists")
        self.records[task.id] = copy.deepcopy(task)
        self._snapshots[task] = copy.deepcopy(task)

    def save(self, task: Task) -> bool:
        cur = self.records.get(task.id)
        if cur is None:
            return False
        snap = self._snapshots.get(task)
        if snap is None:
            snap = Task(id=task.id, title=task.title, body=task.body, priority=task.priority,
                        depends_on=task.depends_on, status=task.status)
        status_changed = task.status != snap.status
        if status_changed and cur.status != snap.status:
            return False
        if status_changed:
            cur.status = task.status
            self.recorded[task.id] = task.status
        else:
            self.recorded.setdefault(task.id, cur.status)
        for f in SCALARS:
            if getattr(task, f) != getattr(snap, f):
                setattr(cur, f, getattr(task, f))
        cur.questions = merge_questions(snap.questions, task.questions, cur.questions)
        if task.body != snap.body:
            cur.body = task.body
        if task.plan != snap.plan:
            cur.plan = task.plan
        if task.assumptions != snap.assumptions:
            cur.assumptions = task.assumptions
        for fb in task.feedback[len(snap.feedback):]:  # numbered after the stored rounds
            cur.feedback += (FeedbackRound(max((f.number for f in cur.feedback), default=0) + 1,
                                           fb.text),)
        cur.log = cur.log + task.log[len(snap.log):]
        for f in fields(Task):
            setattr(task, f.name, copy.deepcopy(getattr(cur, f.name)))
        self._snapshots[task] = copy.deepcopy(task)
        return True

    def observe_moves(self) -> list[ObservedMove]:
        moves: list[ObservedMove] = []
        for tid, t in sorted(self.records.items()):
            rec = self.recorded.get(tid)
            if rec is None:
                self.recorded[tid] = t.status
            elif rec != t.status:
                moves.append(ObservedMove(tid, rec, t.status))
        return moves

    def accept_move(self, move: ObservedMove) -> None:
        self.recorded[move.task_id] = move.dst

    def revert_move(self, move: ObservedMove) -> bool:
        t = self.records.get(move.task_id)
        if t is None or t.status != move.dst:
            return False
        t.status = move.src
        return True
