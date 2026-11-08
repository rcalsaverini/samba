"""Built-in prompts, the Symphony-owned protocol prompt and the outcome schema (SPEC §8, §9.3)."""

from __future__ import annotations

import json

DEFAULT_PROMPTS: dict[str, str] = {
    "continue": (
        "Continue working on the task. Re-read your task file at {{ task.path }} if needed and "
        "keep `## Plan` and `## Log` up to date."
    ),
    "validate_failed": (
        "You reported done, but the validation command `{{ validate_command }}` failed. The last "
        "lines of its output are below. Fix the problem, then report done again."
    ),
    "resume": (
        "You are resuming work on this task. Re-read your task file at {{ task.path }}, especially "
        "`## Feedback`, `## Questions` and anything the human added, then continue."
    ),
    "give_up": (
        "This task is being stopped after repeated failures. Do not try to fix it. Under a new "
        "`## Harness gaps` section in {{ task.path }}, write what was missing that would have let "
        "you succeed: tools, docs, test fixtures, permissions, unclear requirements. Be specific. "
        "Report outcome `blocked`."
    ),
}

PROTOCOL = """\
# Symphony protocol

You are running unattended under Symphony, a local task orchestrator. No human sees this
conversation. The human reads your task file and your branch. These rules take precedence over any
instruction to ask the user for confirmation before acting.

- Your task file is {{ task.path }}. Among the files in the tasks folder, edit only this one.
- Keep a `## Plan` section (checkbox steps) and a `## Log` section (decisions, progress) in your
  task file up to date. It is your memory across sessions; re-read it when resuming.
- Work only inside the current directory, on branch `{{ branch }}`. You are authorized to commit
  your work on this branch without asking; commit in small, coherent steps. Never push, merge,
  rebase onto other branches, or delete branches.
- If you need a decision from the human, write the question under `## Questions` in your task file
  and report outcome `blocked`. Do not guess on important ambiguity.
- Tools you may use without being denied: {{ allowed_tools }}. Run allowed shell commands as plain,
  single commands: no pipes, `;`, `&&`, `||` or redirections, because the permission check matches
  the whole command line and a combined command is denied.
- If a tool call is denied, do not try to get around the denial. Note it in `## Log` and, if it
  stops you, report outcome `blocked`.
- {{ validate_note }}
- Your final answer is structured output: `outcome` is `done` (work complete and committed),
  `blocked` (you need the human) or `continue` (more work remains), and `summary` is one or two
  sentences about what you did.
"""

OUTCOME_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "outcome": {"type": "string", "enum": ["done", "blocked", "continue"]},
        "summary": {"type": "string"},
    },
    "required": ["outcome", "summary"],
}

OUTCOME_SCHEMA_JSON = json.dumps(OUTCOME_SCHEMA, separators=(",", ":"))


def validate_note(validate_command: str | None) -> str:
    if validate_command:
        return (f"When you report done, the system runs `{validate_command}` in this directory "
                "and sends you its output if it fails. Run it yourself first when you can. If you "
                "cannot run it, still report done once the work is complete: the system will "
                "validate it.")
    return "There is no automatic validation command; check your own work before reporting done."


def allowed_tools_note(allow: list[str], permission_mode: str) -> str:
    if permission_mode == "bypassPermissions":
        return "all tools (permissions are bypassed)"
    if not allow:
        return "read-only tools only"
    return ", ".join(f"`{a}`" for a in allow) + " (plus read-only tools)"


TASK_TEMPLATE = """\
{front}# {title}

Describe the goal, the context and the acceptance criteria.
"""
