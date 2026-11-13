"""The fully rendered protocol and default prompts, over the fakes of the task store and the VCS.

Pins the text of `PromptBuilder` with short deterministic briefings, so the protocol's own
words are tested without an adapter. The words the markdown store and git add are pinned in
`tests/integration/test_rendered_prompts_markdown_git.py` (ADR 0020).
"""

from __future__ import annotations

from fake_tasks import FakeTasks
from fake_vcs import FakeVcs
from test_app_run_task import Clock
from test_system_prompts import default_config, system_prompt

from samba.app.prompt_builder import PromptBuilder
from samba.domain.task import Task
from samba.domain.task_id import TaskId

WORK_PROTOCOL = """\
# Samba protocol

You are running unattended under Samba, a local task orchestrator. No human sees this
conversation. The human reads your task and your work. These rules take precedence over any
instruction to ask the user for confirmation before acting.

- BRIEFING(t1, writable)
- Keep your plan (checkbox steps) and your log (decisions, progress) up to date. They are your
  memory across sessions; re-read them when resuming.
- WORKSPACE(t1)
- If you need a decision from the human, report outcome `blocked` and put each question in
  `questions` of your final answer, as `text` and `context` (why it matters). Never record the
  questions yourself: Samba owns them. Do not guess on important ambiguity.
- Tools you may use without being denied: `Edit`, `Write`, `Bash(git add:*)`, `Bash(git commit:*)`, `Bash(git status:*)`, `Bash(git diff:*)`, `Bash(git log:*)`, `Bash(samba adr list:*)`, `Bash(samba adr show:*)` (plus read-only tools). Run allowed shell commands as plain,
  single commands: no pipes, `;`, `&&`, `||` or redirections, because the permission check matches
  the whole command line and a combined command is denied.
- If a tool call is denied, do not try to get around the denial. Note it in your log and, if it
  stops you, report outcome `blocked`.
- There is no automatic validation command; check your own work before reporting done.
- Spec step: before reporting `done`, make the edits to the project's spec that
  this task requires, in your workspace, and say in your log what changed in the spec (or why
  nothing did). The human reviews the spec diff next to the code diff.
- If the task made a real decision (a choice between alternatives with a lasting reason), also
  add a proposed ADR in `docs/adr/`: one decision per file, status `proposed`, in the format of
  the project's first ADR (`samba adr show 1`). Take the next number from the existing
  filenames.
- Decisions that shape the architecture live in `docs/adr/`. Before designing, run `samba adr list`
  and read the relevant ones with `samba adr show N`.
- Your final answer is structured output: `outcome` is `done` (work complete and committed),
  `blocked` (you need the human) or `continue` (more work remains), and `summary` is one or two
  sentences about what you did.
"""

PLAN_PROTOCOL = """\
# Samba protocol (planning)

You are planning unattended under Samba, a local task orchestrator. No human sees this
conversation. The human reads the plan you return. These rules take precedence over any
instruction to ask the user for confirmation before acting.

- BRIEFING(t1, read-only) Read whatever you need from the repository.
- Tools you may use without being denied: `Read`, `Grep`, `Glob`, `Bash(samba adr list:*)`, `Bash(samba adr show:*)` (plus read-only tools). If a tool call is denied, do not
  try to get around the denial.
- Decisions that shape the architecture live in `docs/adr/`. Before designing, run `samba adr list`
  and read the relevant ones with `samba adr show N`.
- Return the plan in `plan` as Markdown with the sections Approach, Steps (checkboxes), Files to
  change, Spec changes, Risks and How to verify, and, if useful, Suggested subtasks. Spec changes
  lists the parts of the project's spec the task will change with one line of intent each, or says
  "none, because ..." and gives the reason. Make the plan stand on its
  own: execution starts in a fresh session that only sees the plan and the task.
- Put assumptions you made, which the human can check during plan review, in `assumptions`. They
  do not block. Use outcome `blocked` only when the plan cannot be written without answers from
  the human, and then put each question in `questions` as `text` and `context` (why it matters).
  Otherwise use outcome `planned`.
- Your final answer is structured output: `outcome` is `planned` or `blocked`, `plan` is the
  Markdown plan, and `summary` is one or two sentences.
"""

DEFAULT_PROMPTS = {
    'continue': (
        'Continue working on the task. Re-read the fake task t1 if needed and keep your plan and log up to date.'
    ),
    'validate_failed': (
        'You reported done, but the validation command `` failed. The last lines of its output are below. Fix the problem, then report done again.'
    ),
    'resume': (
        'You are resuming work on this task. Re-read the fake task t1, especially your feedback and anything the human added, then continue.\n\nQ1: A1'
    ),
    'plan_revise': (
        'The human reviewed your plan and left feedback in the fake task t1 (see your feedback). Re-read it and return a revised plan.\n\nQ1: A1'
    ),
    'give_up': (
        'This task is being stopped after repeated failures. Do not try to fix it. In the fake task t1, add a new section titled "Harness gaps" and write what was missing that would have let you succeed: tools, docs, test fixtures, permissions, unclear requirements. Be specific. Report outcome `blocked` (no `questions` needed).'
    ),
}


def test_the_work_protocol_is_pinned() -> None:
    assert system_prompt("work-running") == WORK_PROTOCOL


def test_the_planning_protocol_is_pinned() -> None:
    assert system_prompt("plan-running") == PLAN_PROTOCOL


def test_the_default_prompts_are_pinned() -> None:
    tasks = FakeTasks()
    task = Task.new(TaskId("t1"), "feature", "", None, (), "work-running", Clock().now())
    tasks.create(task)
    builder = PromptBuilder(default_config(), tasks, FakeVcs())
    variables = {**builder.variables(task, "/ws/t1"), "questions": "Q1: A1"}
    assert {k: builder.prompt(k, variables) for k in DEFAULT_PROMPTS} == DEFAULT_PROMPTS


def test_the_adapters_briefings_reach_the_protocol_and_the_prompts() -> None:
    tasks = FakeTasks()
    task = Task.new(TaskId("t1"), "feature", "", None, (), "work-running", Clock().now())
    tasks.create(task)
    builder = PromptBuilder(default_config(), tasks, FakeVcs())
    variables = builder.variables(task, "/ws/t1")
    assert variables["task_briefing"] == tasks.briefing(task.id, True)
    assert variables["workspace_briefing"] == FakeVcs().briefing(task.id)
    assert variables["task.ref"] == tasks.reference(task.id)
    assert builder.variables(task, "/ws/t1", writable=False)["task_briefing"] == \
        tasks.briefing(task.id, False)
    assert "BRIEFING(t1, read-only)" in builder.setup(task, "/ws/t1", "plan").system_prompt


def test_the_protocol_text_of_the_domain_names_neither_storage_nor_workspace() -> None:
    for text in (WORK_PROTOCOL, PLAN_PROTOCOL, *DEFAULT_PROMPTS.values()):
        for word in ("task file", "tasks folder", "branch", "worktree", "## "):
            assert word not in text, (word, text)
