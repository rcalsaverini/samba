"""`MarkdownTasks`: the `Tasks` port over markdown files in state folders (spec: task-files, states).

Layout: `<tasks>/<status>/<id>.md` holds the task (front matter, body, `## Plan`, `## Assumptions`,
`## Questions`, `## Feedback`, `## Log`) and `<state>/<id>.json` holds the orchestrator fields
(the sidecar). Nothing outside this module needs to know that.

Stale saves (spec: architecture, Ports and task-files, Write discipline): `get` and `list` keep a
deep-copied snapshot of what they returned, keyed by the object. `save` re-reads the stored record,
diffs the aggregate against its snapshot and writes only what the aggregate changed, so a human's
`task stop`, an answered question or the agent's own edit of its file are not reverted by a worker
that has been holding the object for minutes.

`body` is the whole markdown text after the front matter, sections included, as the prompt shows
it. A `Tasks.create` writes `# title`, a blank line and `body` instead. Nothing writes `body` after
that; if an aggregate changes it, the text is replaced as a whole and the sections are applied on top.

Not yet used by the orchestrator and the CLI: they still use `samba.tasks` (a later part of the
refactor moves them over).
"""

from __future__ import annotations

import copy
import json
import os
import re
import time
import weakref
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, cast

import yaml

from samba.domain.questions import Question, QuestionStatus, merge_questions
from samba.domain.states import (
    BLOCKED_CAUSES,
    LAST_OUTCOMES,
    STATES,
    Stage,
    State,
)
from samba.domain.task import FeedbackRound, ObservedMove, Task
from samba.domain.task_id import TaskId
from samba.ports import Clock, StoreError, TaskExists

# Folders of the pre-stage layout (spec: orchestrator, Startup, refuses to start while they hold task files).
LEGACY_STATES: tuple[str, ...] = ("plan", "todo", "running", "review", "blocked")
LEGACY_MOVES: dict[str, str] = {
    "plan": "plan-todo",
    "todo": "work-todo",
    "running": "work-todo   (plan-todo for tasks that were being planned)",
    "review": "work-review",
    "blocked": "question    (stuck for tasks that failed or hit the budget)",
}

# Test-only knob (spec: implementation-notes): seconds a status-changing save sleeps between the rename and the sidecar write.
DEBUG_FIRE_DELAY = float(os.environ.get("SAMBA_DEBUG_FIRE_DELAY") or 0)

# Aggregate fields kept in the sidecar JSON, merged one by one on save.
SIDE_SCALARS: tuple[str, ...] = (
    "session_id", "last_stage", "blocked_cause", "plan_session_id", "plan_approved", "attempts",
    "not_before", "last_error", "last_outcome", "turns_total", "cost_usd_total",
    "input_tokens_total", "output_tokens_total", "branch", "workspace", "first_dispatched_at",
    "queued_at",
)


# ---- front matter and sections --------------------------------------------------------------

class FrontMatterError(Exception):
    pass


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Split `---` YAML front matter from a markdown body. Missing front matter gives {}."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            raw = "".join(lines[1:i])
            body = "".join(lines[i + 1:])
            try:
                data: Any = yaml.safe_load(raw) if raw.strip() else {}
            except yaml.YAMLError as e:
                raise FrontMatterError(f"invalid YAML front matter: {e}") from e
            if data is None:
                data = {}
            if not isinstance(data, dict):
                raise FrontMatterError("front matter must be a YAML map")
            return cast(dict[str, Any], data), body
    raise FrontMatterError("front matter starts with --- but has no closing ---")


def _demote(content: str) -> str:
    """Turn `#` and `##` headings into `###` so they cannot be mistaken for task sections."""
    out: list[str] = []
    for ln in content.strip().splitlines():
        if ln.startswith("# ") or ln.startswith("## "):
            ln = "### " + ln.split(" ", 1)[1]
        out.append(ln)
    return "\n".join(out)


def replace_section(text: str, heading: str, content: str) -> str:
    """Replace the `## <heading>` section with `content` (never duplicates it).

    A missing section is created before `## Log` if present, else at the end.
    """
    lines = text.splitlines()
    block = [f"## {heading}", *_demote(content).splitlines(), ""]
    start = next((i for i, ln in enumerate(lines) if ln.strip() == f"## {heading}"), None)
    if start is not None:
        end = len(lines)
        for i in range(start + 1, len(lines)):
            if lines[i].startswith("## "):
                end = i
                break
        lines[start:end] = block
    else:
        log_at = next((i for i, ln in enumerate(lines) if ln.strip() == "## Log"), None)
        if log_at is None:
            while lines and not lines[-1].strip():
                lines.pop()
            lines += ["", *block]
        else:
            lines[log_at:log_at] = block
    return "\n".join(lines).rstrip("\n") + "\n"


ROUND_RE = re.compile(r"^### Round (\d+)\s*$")


def append_to_feedback_section(text: str, feedback: str) -> tuple[str, int]:
    """Append `feedback` under a new `### Round N` heading at the end of `## Feedback`, creating
    the section (before `## Log`) if missing. Earlier rounds and prose are never rewritten.
    Returns the new text and N (one more than the highest existing round)."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip() == "## Feedback"), None)
    if start is None:
        return replace_section(text, "Feedback", f"### Round 1\n\n{_demote(feedback)}"), 1
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    rounds = [int(m.group(1)) for ln in lines[start + 1:end] if (m := ROUND_RE.match(ln))]
    n = max(rounds, default=0) + 1
    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    block = ["", f"### Round {n}", "", *_demote(feedback).splitlines()]
    if end < len(lines):
        block.append("")
    lines[insert_at:end] = block
    return "\n".join(lines).rstrip("\n") + "\n", n


def append_to_log_section(text: str, line: str) -> str:
    """Append `line` at the end of the `## Log` section, creating the section if missing."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip() == "## Log"), None)
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", "## Log", line]
        return "\n".join(lines) + "\n"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines.insert(insert_at, line)
    following = insert_at + 1
    if following < len(lines) and lines[following].startswith("## "):
        lines.insert(following, "")
    return "\n".join(lines) + "\n"


def render_questions(questions: tuple[Question, ...]) -> str:
    """The `## Questions` content: a view of the records (spec: task-files, Write discipline)."""
    blocks: list[str] = []
    for q in questions:
        parts = [f"### {q.id} (round {q.round}, {q.status})", q.text.strip()]
        if q.context.strip():
            parts.append("Context: " + q.context.strip())
        if q.status == "answered":
            parts.append("Answer: " + (q.answer or "").strip())
        blocks.append("\n\n".join(parts))
    return "\n\n".join(blocks)


def _section_lines(text: str, heading: str) -> list[str] | None:
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip() == f"## {heading}"), None)
    if start is None:
        return None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    return lines[start + 1:end]


def _section_text(text: str, heading: str) -> str:
    return "\n".join(_section_lines(text, heading) or []).strip()


def _log_lines(text: str) -> tuple[str, ...]:
    return tuple(ln for ln in (_section_lines(text, "Log") or []) if ln.strip())


def _feedback_rounds(text: str) -> tuple[FeedbackRound, ...]:
    rounds: list[FeedbackRound] = []
    number: int | None = None
    chunk: list[str] = []

    def flush() -> None:
        if number is not None:
            rounds.append(FeedbackRound(number, "\n".join(chunk).strip()))

    for ln in _section_lines(text, "Feedback") or []:
        m = ROUND_RE.match(ln)
        if m:
            flush()
            number, chunk = int(m.group(1)), []
        else:
            chunk.append(ln)
    flush()
    return tuple(rounds)


# ---- lenient sidecar coercion ---------------------------------------------------------------

def _str(v: object) -> str | None:
    return v if isinstance(v, str) else None


def _int(v: object) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _question(raw: object) -> Question | None:
    if not isinstance(raw, dict):
        return None
    d = cast(dict[str, object], raw)
    qid = _str(d.get("id"))
    if not qid:
        return None
    stage: Stage = "plan" if d.get("stage") == "plan" else "work"
    status_raw = d.get("status")
    status: QuestionStatus = (status_raw
                              if status_raw in ("open", "answered", "dismissed") else "dismissed")
    return Question(id=qid, round=_int(d.get("round")), stage=stage, status=status,
                    text=_str(d.get("text")) or "", context=_str(d.get("context")) or "",
                    asked_at=_str(d.get("asked_at")) or "", answer=_str(d.get("answer")),
                    answered_at=_str(d.get("answered_at")))


def _blank(task: Task) -> Task:
    """What a task that was never loaded is compared to: every non-default field counts as changed."""
    return Task(id=task.id, title=task.title, body=task.body, priority=task.priority,
                depends_on=task.depends_on, status=task.status)


class MarkdownTasks:
    def __init__(self, tasks_dir: Path, state_dir: Path, clock: Clock) -> None:
        self.root = tasks_dir
        self.state_dir = state_dir
        self.clock = clock
        self._snapshots: weakref.WeakKeyDictionary[Task, Task] = weakref.WeakKeyDictionary()

    # ---- paths --------------------------------------------------------------------------

    def _md(self, id: str, status: State) -> Path:
        return self.root / status / f"{id}.md"

    def _json(self, id: str) -> Path:
        return self.state_dir / f"{id}.json"

    def _locate(self, id: str) -> State | None:
        for s in STATES:
            if self._md(id, s).exists():
                return s
        return None

    # ---- port: lifecycle ----------------------------------------------------------------

    def prepare(self) -> None:
        old = [s for s in LEGACY_STATES
               if (self.root / s).is_dir() and any((self.root / s).glob("*.md"))]
        if old:
            lines = [f"old task folders still hold tasks: {', '.join(old)}. Move them to the new "
                     "layout (spec: layout), then start again:", f"  mkdir -p {self.root}/work-todo "
                     f"{self.root}/plan-todo {self.root}/work-review {self.root}/question "
                     f"{self.root}/stuck"]
            for folder in old:
                lines.append(f"  mv {self.root}/{folder}/*.md {self.root}/{LEGACY_MOVES[folder]}")
            raise StoreError("\n".join(lines))
        for s in STATES:
            (self.root / s).mkdir(parents=True, exist_ok=True)

    def location(self, id: TaskId) -> str:
        status = self._locate(id)
        return str(self._md(id, status or "work-todo"))

    # ---- port: reading ------------------------------------------------------------------

    def _read_side(self, id: str) -> dict[str, object]:
        try:
            raw: Any = json.loads(self._json(id).read_text())
        except (OSError, ValueError):
            return {}
        return cast(dict[str, object], raw) if isinstance(raw, dict) else {}

    def _read(self, id: TaskId) -> Task | None:
        status = self._locate(id)
        if status is None:
            return None
        p = self._md(id, status)
        try:
            text = p.read_text()
            mtime = p.stat().st_mtime
        except OSError:
            return None  # moved or deleted meanwhile
        return self._build(id, status, text, mtime, self._read_side(id))

    def _build(self, id: TaskId, status: State, text: str, mtime: float,
               side: dict[str, object]) -> Task:
        try:
            front, body = split_front_matter(text)
        except FrontMatterError:
            front, body = {}, text
        prio = front.get("priority")
        priority = prio if isinstance(prio, int) and not isinstance(prio, bool) else None
        deps_raw = front.get("depends_on")
        depends_on: tuple[TaskId, ...] = ()
        if isinstance(deps_raw, list):
            items = cast(list[object], deps_raw)
            if all(isinstance(d, str) and TaskId.is_valid(d) for d in items):
                depends_on = tuple(TaskId(cast(str, d)) for d in items)
        title = str(id)
        for line in body.splitlines():
            if line.startswith("# "):
                title = line[2:].strip() or str(id)
                break
        cause = side.get("blocked_cause")
        outcome = side.get("last_outcome")
        stage = side.get("last_stage")
        qraw = side.get("questions")
        questions = tuple(q for q in (_question(r) for r in cast(list[object], qraw))
                          if q is not None) if isinstance(qraw, list) else ()
        queued = _num(side.get("queued_at"))
        return Task(
            id=id, title=title, body=body.strip(), priority=priority, depends_on=depends_on,
            status=status,
            attempts=_int(side.get("attempts")), turns_total=_int(side.get("turns_total")),
            cost_usd_total=_num(side.get("cost_usd_total")) or 0.0,
            input_tokens_total=_int(side.get("input_tokens_total")),
            output_tokens_total=_int(side.get("output_tokens_total")),
            session_id=_str(side.get("session_id")),
            plan_session_id=_str(side.get("plan_session_id")),
            plan_approved=side.get("plan_approved") is True,
            last_stage=stage if stage in ("plan", "work") else None,
            blocked_cause=cause if cause in BLOCKED_CAUSES else None,
            last_outcome=outcome if outcome in LAST_OUTCOMES else None,
            last_error=_str(side.get("last_error")), not_before=_num(side.get("not_before")),
            first_dispatched_at=_num(side.get("first_dispatched_at")),
            queued_at=queued if queued is not None else mtime,
            branch=_str(side.get("branch")), workspace=_str(side.get("workspace")),
            plan=_section_text(text, "Plan"), assumptions=_section_text(text, "Assumptions"),
            feedback=_feedback_rounds(text), log=_log_lines(text), questions=questions)

    def _remember(self, task: Task) -> Task:
        self._snapshots[task] = copy.deepcopy(task)
        return task

    def get(self, id: TaskId) -> Task | None:
        task = self._read(id)
        return self._remember(task) if task is not None else None

    def list(self, status: State) -> list[Task]:
        out: list[Task] = []
        for tid in self.ids(status):
            task = self._read(tid)
            if task is not None and task.status == status:
                out.append(self._remember(task))
        return out

    def ids(self, status: State | None = None) -> list[TaskId]:
        out: list[TaskId] = []
        for s in ([status] if status is not None else STATES):
            d = self.root / s
            if d.is_dir():
                out.extend(TaskId(p.stem) for p in sorted(d.glob("*.md")) if TaskId.is_valid(p.stem))
        return out

    def rejected_names(self, status: State) -> list[str]:
        d = self.root / status
        return [p.name for p in d.glob("*.md") if not TaskId.is_valid(p.stem)] if d.is_dir() else []

    # ---- port: create -------------------------------------------------------------------

    def create(self, task: Task) -> None:
        if self._locate(task.id) is not None:
            raise TaskExists(f"task {task.id} exists")
        front: dict[str, object] = {"priority": task.priority}
        if task.depends_on:
            front["depends_on"] = list(task.depends_on)
        text = "---\n" + "".join(f"{k}: {json.dumps(v)}\n" for k, v in front.items()) + "---\n"
        text += f"# {task.title}\n\n"
        if task.body.strip():
            text += task.body.rstrip("\n") + "\n"
        (self.root / task.status).mkdir(parents=True, exist_ok=True)
        self._md(task.id, task.status).write_text(text)
        blank = _blank(task)
        if any(getattr(task, f) != getattr(blank, f) for f in SIDE_SCALARS if f != "queued_at") \
                or task.questions:
            self._write_side(task.id, task, task.questions, state=None)
        self._remember(task)

    # ---- port: save ---------------------------------------------------------------------

    def _write_side(self, id: str, merged: Task, questions: tuple[Question, ...],
                    state: str | None) -> None:
        data: dict[str, object] = {
            "state": state, "session_id": merged.session_id, "last_stage": merged.last_stage,
            "blocked_cause": merged.blocked_cause, "plan_session_id": merged.plan_session_id,
            "plan_approved": merged.plan_approved, "attempts": merged.attempts,
            "not_before": merged.not_before, "last_error": merged.last_error,
            "last_outcome": merged.last_outcome, "turns_total": merged.turns_total,
            "cost_usd_total": merged.cost_usd_total, "input_tokens_total": merged.input_tokens_total,
            "output_tokens_total": merged.output_tokens_total, "branch": merged.branch,
            "workspace": merged.workspace, "first_dispatched_at": merged.first_dispatched_at,
            "updated_at": self.clock.time(), "questions": [asdict(q) for q in questions],
            "queued_at": merged.queued_at,
        }
        self.state_dir.mkdir(parents=True, exist_ok=True)
        p = self._json(id)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        os.replace(tmp, p)

    def save(self, task: Task) -> bool:
        cur = self._read(task.id)
        if cur is None:
            return False
        snap = self._snapshots.get(task) or _blank(task)
        status_changed = task.status != snap.status
        if status_changed and cur.status != snap.status:
            return False  # lost the race: someone else moved the task
        side = self._read_side(task.id)
        recorded = _str(side.get("state"))
        folder = cur.status
        if status_changed:
            try:
                os.rename(self._md(task.id, cur.status), self._md(task.id, task.status))
            except FileNotFoundError:
                return False
            folder = task.status
            recorded = task.status
            if DEBUG_FIRE_DELAY:
                time.sleep(DEBUG_FIRE_DELAY)  # test-only: widens the window the repo lock covers
        elif recorded is None:
            recorded = folder  # first sight

        # Sidecar: only the fields the aggregate changed, the rest keeps the stored value.
        merged = copy.copy(cur)
        for f in SIDE_SCALARS:
            if getattr(task, f) != getattr(snap, f):
                setattr(merged, f, getattr(task, f))
        questions = merge_questions(snap.questions, task.questions, cur.questions)
        self._write_side(task.id, merged, questions, recorded)

        # Markdown: only when a field it owns changed (the task file is written while no agent runs).
        path = self._md(task.id, folder)
        md_dirty = (task.body != snap.body or task.plan != snap.plan
                    or task.assumptions != snap.assumptions or questions != cur.questions
                    or len(task.feedback) > len(snap.feedback) or len(task.log) > len(snap.log))
        if md_dirty:
            text = path.read_text()
            if task.body != snap.body:
                _, body = split_front_matter(text)
                text = text[:len(text) - len(body)] + task.body.rstrip("\n") + "\n"
            if task.plan != snap.plan and task.plan.strip():
                text = replace_section(text, "Plan", task.plan)
            if task.assumptions != snap.assumptions and task.assumptions.strip():
                text = replace_section(text, "Assumptions", task.assumptions)
            if questions != cur.questions and questions:
                text = replace_section(text, "Questions", render_questions(questions))
            for fb in task.feedback[len(snap.feedback):]:
                text, _ = append_to_feedback_section(text, fb.text)
            for line in task.log[len(snap.log):]:
                text = append_to_log_section(text, line)
            path.write_text(text)

        # Refresh the aggregate from what is stored now, and renew its snapshot.
        fresh = self._read(task.id)
        if fresh is not None:
            for f in fields(Task):
                setattr(task, f.name, getattr(fresh, f.name))
            self._remember(task)
        return True

    # ---- port: hand moves ---------------------------------------------------------------

    def observe_moves(self) -> list[ObservedMove]:
        moves: list[ObservedMove] = []
        for status in STATES:
            for tid in self.ids(status):
                side = self._read_side(tid)
                recorded = _str(side.get("state"))
                if recorded not in STATES:
                    task = self._read(tid)  # first sight: record, report nothing
                    if task is not None:
                        self._write_side(tid, task, task.questions, state=status)
                    continue
                if recorded != status:
                    moves.append(ObservedMove(tid, recorded, status))
        return moves

    def accept_move(self, move: ObservedMove) -> None:
        task = self._read(move.task_id)
        if task is not None:
            self._write_side(move.task_id, task, task.questions, state=move.dst)

    def revert_move(self, move: ObservedMove) -> bool:
        if self._md(move.task_id, move.src).exists():
            return False
        try:
            os.rename(self._md(move.task_id, move.dst), self._md(move.task_id, move.src))
        except FileNotFoundError:
            return False
        return True
