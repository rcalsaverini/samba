"""The agent protocol with the markdown store and git: the text moved, it was not reworded.

ADR 0020 moved the words about the task file and the branch from `domain/prompts.py` into the
`briefing` and `reference` of `MarkdownTasks` and `GitVcs`. This renders the prompts through the
real adapters and compares them with the templates as they were before the move, after the
listed sentence changes and nothing else (the whitespace is normalized: the lines were wrapped
differently). The words of the protocol itself are pinned over fakes in
`tests/component/test_rendered_prompts.py`.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from test_app_run_task import Clock, make_config

from samba.adapters.git_vcs import GitVcs, HookSettings
from samba.adapters.markdown_tasks import MarkdownTasks
from samba.adapters.locations import Locations
from samba.app.prompt_builder import PromptBuilder
from samba.domain.settings import DEFAULT_ALLOW, DEFAULT_PLANNING_ALLOW, ToolAccess
from samba.domain.task import Task
from samba.domain.task_id import TaskId
from samba.domain.template import render

OLD_PROTOCOL = """\
# Samba protocol

You are running unattended under Samba, a local task orchestrator. No human sees this
conversation. The human reads your task file and your branch. These rules take precedence over any
instruction to ask the user for confirmation before acting.

- Your task file is {{ task.path }}. Among the files in the tasks folder, edit only this one.
- Keep a `## Plan` section (checkbox steps) and a `## Log` section (decisions, progress) in your
  task file up to date. It is your memory across sessions; re-read it when resuming.
- Work only inside the current directory, on branch `{{ branch }}`. You are authorized to commit
  your work on this branch without asking; commit in small, coherent steps. Never push, merge,
  rebase onto other branches, or delete branches.
- If you need a decision from the human, report outcome `blocked` and put each question in
  `questions` of your final answer, as `text` and `context` (why it matters). Never write a
  `## Questions` section yourself: Samba owns it. Do not guess on important ambiguity.
- Tools you may use without being denied: {{ allowed_tools }}. Run allowed shell commands as plain,
  single commands: no pipes, `;`, `&&`, `||` or redirections, because the permission check matches
  the whole command line and a combined command is denied.
- If a tool call is denied, do not try to get around the denial. Note it in `## Log` and, if it
  stops you, report outcome `blocked`.
- {{ validate_note }}
- Spec step: before reporting `done`, make the edits to the project's spec that
  this task requires, on this branch, and say in `## Log` what changed in the spec (or why
  nothing did). The human reviews the spec diff next to the code diff.
- If the task made a real decision (a choice between alternatives with a lasting reason), also
  add a proposed ADR in `docs/adr/`: one decision per file, status `proposed`, in the format of
  ADR 0001 (front matter with `status`, `date` and `supersedes`, then Context, Decision,
  Consequences). Take the next number from the existing filenames.
- Decisions that shape the architecture live in `docs/adr/`. Before designing, run `samba adr list`
  and read the relevant ones with `samba adr show N`.
- Your final answer is structured output: `outcome` is `done` (work complete and committed),
  `blocked` (you need the human) or `continue` (more work remains), and `summary` is one or two
  sentences about what you did.
"""

OLD_APPROVED_PLAN_RULE = """\
- An approved plan is in the `## Plan` section of your task file. Follow it. If you must deviate,
  record what and why in `## Log`. Tick the plan's checkboxes as you complete steps. Its
  "Spec changes" section lists the spec edits you owe.
"""

OLD_PLAN_PROTOCOL = """\
# Samba protocol (planning)

You are planning unattended under Samba, a local task orchestrator. No human sees this
conversation. The human reads the plan you return. These rules take precedence over any
instruction to ask the user for confirmation before acting.

- Your task file is {{ task.path }}. You cannot edit files and must not try. Read whatever you
  need from the repository.
- Tools you may use without being denied: {{ allowed_tools }}. If a tool call is denied, do not
  try to get around the denial.
- Decisions that shape the architecture live in `docs/adr/`. Before designing, run `samba adr list`
  and read the relevant ones with `samba adr show N`.
- Return the plan in `plan` as Markdown with the sections Approach, Steps (checkboxes), Files to
  change, Spec changes, Risks and How to verify, and, if useful, Suggested subtasks. Spec changes
  lists the parts of the project's spec the task will change with one line of intent each, or says
  "none, because ..." and gives the reason. Make the plan stand on its
  own: execution starts in a fresh session that only sees the plan and the task file.
- Put assumptions you made, which the human can check during plan review, in `assumptions`. They
  do not block. Use outcome `blocked` only when the plan cannot be written without answers from
  the human, and then put each question in `questions` as `text` and `context` (why it matters).
  Otherwise use outcome `planned`.
- Your final answer is structured output: `outcome` is `planned` or `blocked`, `plan` is the
  Markdown plan, and `summary` is one or two sentences.
"""

OLD_DEFAULT_PROMPTS = {
    'continue': (
        'Continue working on the task. Re-read your task file at {{ task.path }} if '
        'needed and keep `## Plan` and `## Log` up to date.'
    ),
    'validate_failed': (
        'You reported done, but the validation command `{{ validate_command }}` '
        'failed. The last lines of its output are below. Fix the problem, then '
        'report done again.'
    ),
    'resume': (
        'You are resuming work on this task. Re-read your task file at {{ task.path '
        '}}, especially `## Feedback` and anything the human added, then '
        'continue.\n\n{{ questions }}'
    ),
    'plan': (
        'Do not implement anything yet. Produce a plan for this task.'
    ),
    'plan_revise': (
        'The human reviewed your plan and left feedback in your task file at {{ '
        'task.path }} (see `## Feedback`). Re-read it and return a revised plan.\n\n{{ '
        'questions }}'
    ),
    'give_up': (
        'This task is being stopped after repeated failures. Do not try to fix it. '
        'Under a new `## Harness gaps` section in {{ task.path }}, write what was '
        'missing that would have let you succeed: tools, docs, test fixtures, '
        'permissions, unclear requirements. Be specific. Report outcome `blocked` '
        '(no `questions` needed).'
    ),
}


# What changed in the sentences the agent reads: (before, after), on whitespace-normalized text.
CHANGES = [
    ("The human reads your task file and your branch.", "The human reads your task and your work."),
    ("edit only this one.",
     "edit only this one. Your plan is its `## Plan` section and your log its `## Log` section. "
     "The human's feedback on your plan or your work is in `## Feedback`. Samba owns the "
     "`## Questions` section: never write it yourself."),
    ("Keep a `## Plan` section (checkbox steps) and a `## Log` section (decisions, progress) in "
     "your task file up to date. It is your memory across sessions; re-read it when resuming.",
     "Keep your plan (checkbox steps) and your log (decisions, progress) up to date. They are "
     "your memory across sessions; re-read them when resuming."),
    ("Never write a `## Questions` section yourself: Samba owns it.",
     "Never record the questions yourself: Samba owns them."),
    ("Note it in `## Log` and,", "Note it in your log and,"),
    ("on this branch, and say in `## Log` what changed",
     "in your workspace, and say in your log what changed"),
    ("in the format of ADR 0001 (front matter with `status`, `date` and `supersedes`, then "
     "Context, Decision, Consequences).", "in the format of the project's first ADR "
     "(`samba adr show 1`)."),
    ("An approved plan is in the `## Plan` section of your task file. Follow it. If you must "
     "deviate, record what and why in `## Log`.",
     "You have an approved plan. Follow it. If you must deviate, record what and why in your log."),
    ("only sees the plan and the task file.", "only sees the plan and the task."),
    ("keep `## Plan` and `## Log` up to date.", "keep your plan and log up to date."),
    ("especially `## Feedback` and", "especially your feedback and"),
    ("(see `## Feedback`)", "(see your feedback)"),
    ("Under a new `## Harness gaps` section in {path}, write what was missing",
     "In your task file at {path}, add a new section titled \"Harness gaps\" and write what was "
     "missing"),
]


def normal(text: str) -> str:
    return " ".join(text.split())


def changed(old: str, path: str) -> str:
    text = normal(old)
    for before, after in CHANGES:
        text = text.replace(before.format(path=path) if "{path}" in before else before,
                            after.format(path=path) if "{path}" in after else after)
    return text


def rig(tmp_path: Path, plan_approved: bool = False) -> tuple[PromptBuilder, Task, str, str]:
    root = (tmp_path / "repo").resolve()
    root.mkdir()
    tasks = MarkdownTasks(tmp_path / "tasks", tmp_path / "state", Clock())
    tasks.prepare()
    task = Task.new(TaskId("t1"), "feature", "body", None, (), "work-running", Clock().now())
    task.plan_approved = plan_approved
    tasks.create(task)
    vcs = GitVcs(Locations(repo=root, samba_dir=root / ".samba",
                           workspaces_root=tmp_path / "ws"), "main",
                 HookSettings(None, 60.0, ("bash", "-c")))
    config = make_config()
    config = replace(config, work_tools=ToolAccess(tuple(DEFAULT_ALLOW), False),
                     planning_tools=ToolAccess(tuple(DEFAULT_PLANNING_ALLOW), False))
    return PromptBuilder(config, tasks, vcs), task, tasks.location(task.id), vcs.branch_name(task.id)


def old_variables(builder: PromptBuilder, task: Task, path: str, branch: str) -> dict[str, str]:
    stage = "plan" if task.status.startswith("plan") else "work"
    variables = {**builder.variables(task, "/ws/t1"), "task.path": path, "branch": branch}
    from samba.domain.prompts import allowed_tools_note, validate_note
    config = builder.config
    tools = config.planning_tools if stage == "plan" else config.work_tools
    return {**variables, "validate_note": validate_note(config.validate_command),
            "allowed_tools": allowed_tools_note(tools)}


def test_the_work_protocol_changes_only_the_listed_sentences(tmp_path: Path) -> None:
    builder, task, path, branch = rig(tmp_path)
    variables = old_variables(builder, task, path, branch)
    new = builder.setup(task, "/ws/t1", "work").system_prompt
    assert normal(new) == changed(render(OLD_PROTOCOL, variables), path)


def test_the_protocol_with_an_approved_plan_changes_only_the_listed_sentences(
        tmp_path: Path) -> None:
    builder, task, path, branch = rig(tmp_path, plan_approved=True)
    variables = old_variables(builder, task, path, branch)
    new = builder.setup(task, "/ws/t1", "work").system_prompt
    assert normal(new) == changed(render(OLD_PROTOCOL, variables) + OLD_APPROVED_PLAN_RULE, path)


def test_the_planning_protocol_changes_only_the_listed_sentences(tmp_path: Path) -> None:
    builder, task, path, branch = rig(tmp_path)
    task.status = "plan-running"
    variables = old_variables(builder, task, path, branch)
    new = builder.setup(task, "/ws/t1", "plan").system_prompt
    assert normal(new) == changed(render(OLD_PLAN_PROTOCOL, variables), path)


def test_the_default_prompts_change_only_the_listed_sentences(tmp_path: Path) -> None:
    builder, task, path, branch = rig(tmp_path)
    variables = {**old_variables(builder, task, path, branch), "questions": "Q1: A1"}
    for key, old in OLD_DEFAULT_PROMPTS.items():
        new = builder.prompt(key, variables)
        assert normal(new) == changed(render(old, variables), path), key


def test_the_markdown_and_git_briefings_carry_the_task_and_workspace_words(
        tmp_path: Path) -> None:
    builder, task, path, branch = rig(tmp_path)
    v = builder.variables(task, "/ws/t1")
    assert v["task.ref"] == f"your task file at {path}"
    assert v["task_briefing"].startswith(f"Your task file is {path}. Among the files in the tasks "
                                         "folder, edit only this one.")
    assert "`## Plan`" in v["task_briefing"] and "`## Questions`" in v["task_briefing"]
    assert v["workspace_briefing"].startswith(
        f"Work only inside the current directory, on branch `{branch}`.")
    assert v["workspace_briefing"].endswith("or delete branches.")
    planning = builder.variables(task, "/ws/t1", writable=False)["task_briefing"]
    assert planning == f"Your task file is {path}. You cannot edit files and must not try."
