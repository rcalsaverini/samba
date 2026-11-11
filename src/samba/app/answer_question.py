"""`AnswerQuestion`: records an answer at once; fires `question.answer` only when no question of
the round is still open (spec: cli, question answer)."""

from __future__ import annotations

from samba.app.change_state import NotAllowed, check_legal
from samba.app.machine import Machine
from samba.app.resolve import find_task, split_target
from samba.app.results import LOCK_BUSY, Done, Refused, refused, usage
from samba.domain.questions import Question, open_questions, round_questions
from samba.domain.task_id import TaskId
from samba.domain.transitions import log_line
from samba.domain.ports import Clock, Lock, Tasks, Terminal

EVENT = "question.answer"


def editor_text(q: Question) -> str:
    """The question quoted as `# ` comment lines, above the room for the answer."""
    shown = f"{q.id}: {q.text}"
    if q.context:
        shown += f"\n\nContext: {q.context}"
    head = "\n".join(f"# {ln}" if ln else "#" for ln in shown.splitlines())
    return head + "\n\n"


def strip_comments(text: str) -> str:
    kept = [ln for ln in text.splitlines() if ln != "#" and not ln.startswith("# ")]
    return "\n".join(kept).strip()


class AnswerQuestion:
    def __init__(self, tasks: Tasks, machine: Machine, terminal: Terminal, lock: Lock,
                 clock: Clock) -> None:
        self.tasks = tasks
        self.machine = machine
        self.terminal = terminal
        self.lock = lock
        self.clock = clock

    def _check(self, task_id: TaskId, qid: str | None) -> Question | Refused:
        """The question to answer, or why not."""
        legal = check_legal(self.tasks, task_id, EVENT, EVENT)
        if isinstance(legal, NotAllowed):
            return refused(legal.message)
        task = legal.task
        open_qs = open_questions(task.questions)
        if qid is None:
            if len(open_qs) == 1:
                return open_qs[0]
            if not open_qs:
                return refused(f"{task_id} has no open question; nothing changed")
            return usage(f"{task_id} has {len(open_qs)} open questions; name one as "
                         f"{task_id}/QID. Open:\n" + "\n".join(f"  {task_id}/{q.id}"
                                                               for q in open_qs))
        found = next((q for q in task.questions if q.id == qid), None)
        if found is None:
            return usage(f"unknown question {task_id}/{qid}")
        if found.status != "open":
            return refused(f"{task_id}/{qid} is {found.status}, not open; nothing changed")
        return found

    def run(self, target: str, text: str | None, edit: bool) -> Done | Refused:
        """`target` is `TASK[/QID]` as typed; the task part may be a unique prefix."""
        name, qid = split_target(target)
        task_id = find_task(self.tasks, name)
        if isinstance(task_id, Refused):
            return task_id
        q = self._check(task_id, qid)
        if isinstance(q, Refused):
            return q
        answer = text
        if edit:  # before the lock: editing can take long
            edited = self.terminal.edit(editor_text(q))
            if edited.text is None:
                return refused(edited.error or "editor failed")
            answer = strip_comments(edited.text)
        answer = (answer or "").strip()
        if not answer:
            return usage("question answer needs text (argument or --edit); nothing changed")

        tasks = self.tasks
        with self.lock.acquire() as held:
            if not held:
                return refused(LOCK_BUSY)
            q = self._check(task_id, qid)  # re-check: a hand move or another answer may have raced
            if isinstance(q, Refused):
                return q
            task = tasks.get(task_id)
            assert task is not None  # _check just found it, under the same lock
            task.answer_question(q.id, answer, self.clock)
            task.add_log(log_line(f"{EVENT}: {task_id}/{q.id} answered", self.clock))
            tasks.save(task)
            left = open_questions(round_questions(task.questions))
            if not left and not self.machine.fire(task_id, EVENT):
                return refused(f"{EVENT} did not apply to {task_id}; the answer was recorded")
        notes: tuple[str, ...] = ()
        if left:
            notes = (f"samba: {len(left)} question(s) still open: " + ", ".join(
                f"{task_id}/{r.id}" for r in left),)
        location = tasks.location(task_id) if tasks.get(task_id) is not None else None
        return Done(location, notes)
