---
status: accepted
date: 2026-11-13
supersedes: []
---

# 0020: The agent protocol names the task, and the adapters say where it lives

## Context

Principle 4 of the `principles` chapter says the domain knows no folder, path, sidecar, process,
branch or worktree. ADR 0011 makes the same point for the task store: replacing the markdown
folders with a database or a tracker must change only an adapter. The protocol the agent follows
does not honor it.

`domain/prompts.py` holds the text the agent is told. About fifteen of its lines name the storage
or the workspace instead of the task:

- `PROTOCOL` says "Your task file is {{ task.path }}. Among the files in the tasks folder, edit
  only this one", that `## Plan` and `## Log` are sections of "your task file", that `## Questions`
  is a section Samba owns, and "Work only inside the current directory, on branch
  `{{ branch }}`", with the authorization to commit on it and the ban on push, merge, rebase and
  branch deletion.
- `PLAN_PROTOCOL` says "Your task file is {{ task.path }}. You cannot edit files", and that
  execution "only sees the plan and the task file".
- `APPROVED_PLAN_RULE` says the plan is in the `## Plan` section of "your task file".
- Four of the `DEFAULT_PROMPTS` (`continue`, `resume`, `plan_revise`, `give_up`) say "your task file
  at {{ task.path }}", point at `## Feedback`, and ask for a `## Harness gaps` section.

If the task lived in a database or a tracker, the agent would be told to open a file that does not
exist. The semantics are not the problem: that the agent keeps a plan and a log, that it reports
`done`, `blocked` or `continue`, that questions go in the structured answer, that nothing is
guessed. The wording of where and how is.

The architecture test does not catch this. `test_domain_and_app_code_has_no_storage_vocabulary`
exempts `domain/prompts.py` with the comment that it talks about "the task file's front matter".
The pattern it applies (`Path|mtime|sidecar|front matter`) matches nothing of the above. Its one
hit in that file is the wording about the format of an ADR (`front matter with status ...` in
`EXPLORE_GUIDE` and in `PROTOCOL`), which is not the task store at all. So the exemption hides
words the check could catch only by accident, and "task file", "tasks folder" and "branch" are in
no pattern.

What exists to build on. `Tasks.location(id)` in `app/ports.py` is documented as opaque ("where the
agent finds its task") and feeds the `task.path` variable. `Vcs.branch_name(task_id)` feeds
`branch`. `PromptBuilder.variables` in `app/prompt_builder.py` renders both, with `workspace`, into
the protocol and into the user-authored prompts: the `WORKFLOW.md` body, and the `prompts.*`
overrides. A repository's body may already say `{{ task.path }}` or `{{ branch }}`; that text is the
user's and a decision of theirs.

## Decision

- The agent protocol is written in the vocabulary of the domain: it speaks of "your task" and "your
  workspace", and the adapters say where they are and how to work with them.
- The semantics of the protocol stay in `domain/prompts.py`: the outcome schema and its outcomes
  (`done`, `blocked`, `continue`, and `planned` for a plan), what they mean, that questions go in
  the structured answer and the agent never writes the `Questions` record itself, that the agent
  keeps a plan and a log as its memory across sessions, the denial rule, the spec step, the ADR
  step, and the approved-plan rule. The text says "your plan", "your log", "your feedback" and
  "your task", never a file, a heading or a folder.
- The task store contributes the instructions specific to its technology through the `Tasks` port.
  `briefing(id, writable) -> str` returns a short block in the agent's language: how to find the
  task, whether and how to edit it, what belongs to Samba, and how the plan, the log and the
  feedback are written in this store. `reference(id) -> str` returns a short phrase that names the
  task for a sentence ("your task file at /abs/path"). `writable` is false for a planning run. The
  markdown store returns what the protocol says today: the path, "edit only this one among the files
  in the tasks folder", and the `## Plan`, `## Log`, `## Feedback` and `## Questions` sections.
  `location(id)` stays, opaque, for the result of `task new` and for the use cases that print it.
- The VCS adapter contributes the workspace instructions through the `Vcs` port.
  `briefing(task_id) -> str` says which branch the work lives on, that the agent may commit there
  without asking and in small steps, and what it must never do (push, merge, rebase onto other
  branches, delete branches). `GitVcs` returns what the protocol says today.
- `PromptBuilder` splices the two blocks into the protocol through two template variables of the
  Samba-owned protocol (`task_briefing` and `workspace_briefing`), and `reference` into the default
  prompts through a `task.ref` variable. The adapters are asked once per run, when the setup is
  built. The existing variables (`task.id`, `task.title`, `task.body`, `task.path`, `workspace`,
  `branch`, `base_branch` and the others) stay as they are, with the same values, for the
  `WORKFLOW.md` body and the overrides. A body that names `{{ task.path }}` ties itself to the
  store it was written for, and that is the user's choice. The built-in prompts no longer do.
- The text about the format of an ADR points at the project's first ADR (`samba adr show 1`) and
  names no storage word, because it is read by the adapter-neutral protocol.
- The exemption of `domain/prompts.py` is removed from
  `test_domain_and_app_code_has_no_storage_vocabulary`.
  The check also learns words the pattern lacked, in two scopes. For the domain and the use-case
  modules, `task file` and `tasks folder` join the pattern, as code outside comments. For the
  prose of the domain's prompts only (the string literals of `domain/prompts.py`, not its
  identifiers), `branch` and `worktree` are added too. They are not added to the whole domain:
  `Task` has the opaque fields `branch` and `workspace`, and the use cases speak of branches
  (`AcceptWork`, `Vcs.branch_name`, `Workspace`) legitimately. A test shows each scope catches its
  words and spares the others.
- Considered and not chosen:
  - Keeping the exemption. It is the status quo: the swap of the store stays impossible without
    editing the domain, and the exemption hides more than the check could ever find.
  - Moving all the prompts, protocol included, to the adapters. The outcome format, what `blocked`
    means and the plan and log duties are Samba's behavior, not the store's, and two adapters
    would each have to repeat them. A rewrite would also lose the one place that states them.
  - Making the protocol pure configuration, in `WORKFLOW.md`. The rules in it are ones that
    Samba's own logic depends on (ADR 0006), they must not be overridable by the workflow, and
    the repository would have to repeat them for each store.
  - One port method that returns the whole protocol text. It makes the adapter own rules, against
    principle 7, and it splits the text into pieces the adapter cannot test without the domain.
  - Dropping `location` for the new methods. The use cases still need an opaque place to print or
    pass on, for example the result of `task new`.

## Consequences

- Swapping the task store, or the VCS, changes the adapter that is swapped and no domain text. A new
  store writes its own `briefing`; the protocol's semantics reach the agent unchanged.
- The text the agent sees with the markdown store and git is meant to stay the same, word for word
  where it can. A component test pins the rendered protocol, the plan variant and the four default
  prompts for those two adapters, so the move is a refactor and not a rewording. Where the sentence
  changes (for example "your task file at ..." through `reference`) the test says so.
- The end-to-end tests do not change: they assert on files and on the calls the fake claude records,
  and none of them asserts on the protocol text. They could: the recorded argv includes the
  prompt passed with `-p`. The rule is that the end-to-end level asserts on files and recorded
  calls, never on prompt wording, which the component test of the rendered protocol owns. The
  fakes of the ports gain the two methods; the
  port contracts of `Tasks` and `Vcs` get cases for them.
- The `prompts` chapter changes: its protocol section is described in terms of "task" and
  "workspace" with a table of what each adapter contributes, the variable list gains `task.ref`,
  `task_briefing` and `workspace_briefing`, and the default prompts are quoted with `task.ref`. The
  `architecture` chapter (the `Tasks` and `Vcs` rows, the architecture test), the `task-files`
  chapter (where the briefing wording lives) and the `CLAUDE.md` map change with it.
- Cost: the protocol is now assembled from three places, so reading it takes more than one file.
  The component test that renders the whole thing is the answer.
- Independent of ADR 0019 but run after it: both change `prompt_builder.py` and `bootstrap.py`. This
  ADR applies principle 4 and ADR 0011 to the prompts, and supersedes nothing.
