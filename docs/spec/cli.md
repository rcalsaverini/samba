# CLI

```
samba run      [--repo PATH] [--exit-when-idle]
                  # start the loop (foreground; Ctrl-C stops agents and exits).
                  # --exit-when-idle: exit once nothing is running and plan-todo/ and
                  # work-todo/ hold no task that can run (plan-review/ and work-review/ are the
                  # human's and do not keep it alive). Tasks held only by dependencies
                  # (orchestrator, Dependencies) do not count, so a dependency waiting for a human
                  # cannot hang the run. A dependency that is itself runnable in a todo folder does
                  # keep it alive. Exits 1 with an `mv` recipe if old-layout folders still hold tasks
                  # (orchestrator, Startup).
samba task new [TITLE] [--body TEXT] [--depends-on ID[,ID...]] [--priority N]
                  [--skip-plan] [--repo PATH]
                  # create plan-todo/<slug>.md (work-todo/<slug>.md with --skip-plan)
samba task list [STATE...] [--repo PATH]
samba task show ID         [--repo PATH]
samba dev transitions
                  # print the transition table (states, States) as Markdown; needs no repo.
samba plan accept ID [--repo PATH]
samba plan reject ID [--feedback TEXT | --edit] [--repo PATH]
samba work reject ID [--feedback TEXT | --edit] [--fresh] [--repo PATH]
samba work accept ID [--no-merge] [--no-validate] [--yes] [--dry-run] [--repo PATH]
samba question list [--repo PATH]
samba question show TASK[/QID] [--repo PATH]
samba question answer TASK[/QID] (TEXT | --edit) [--repo PATH]
samba adr list [--all] [--repo PATH]
samba adr show N [--repo PATH]
samba adr accept N [--repo PATH]
samba adr reject N [--repo PATH]
samba adr supersede N NEW [--repo PATH]
samba task retry ID   [--repo PATH]
samba task stop ID    [--repo PATH]
samba task discard ID [--yes] [--repo PATH]
samba explore [TOPIC] [--repo PATH]
                  # interactive claude session to explore a topic and write ADRs.
```

Every command is `run`, `explore` or `<noun> <verb>`, with nouns `task`, `plan`, `work`, `question`,
`adr` and `dev`. There are no top-level `new`, `list`, `show`, `status` or `transitions`, and no
aliases: they are usage errors (exit 2). `samba --help` lists `run`, `task`, `plan`, `work`,
`question`, `adr` and `explore`, then
`dev` apart under "development commands" (its help says it is for working on Samba itself).
`dev transitions` accepts `--repo` and ignores it; it loads no config.

**`task new`** creates the whole task, so the file need not be opened afterwards. It does not take
the repo lock: it only writes one new file.

- Fields: `TITLE`, `--body TEXT`, `--depends-on` (task ids or unique prefixes, comma separated,
  empty parts ignored), `--priority N` (default 3), `--skip-plan`.
- With a TITLE and no TTY, missing fields take defaults: empty body, no dependencies, priority 3,
  planning on. On a TTY (stdin and stdout), each field the flags did not give is prompted on
  stdin, in this order: `Title:` (required, re-asked while empty), `Description (end with an empty
  line):` (read until the first empty line), `Depends on (ids or prefixes, comma separated, empty
  for none):`, `Plan first? [Y/n]` (empty or `y` plans; `n` skips). Priority is never prompted.
  End of input while prompting is exit 1, nothing created.
- Dependencies use the task id resolver below and are written as full ids. An unknown or ambiguous
  id is re-asked at the prompt, and is exit 2 (nothing created) when given by flag.
- No TITLE and no TTY is exit 2 with a usage message, nothing created.
- The file is front matter (`priority` always, `depends_on` as a list when non-empty), `# Title`, a
  blank line, then the body. Destination: `plan-todo/`, or `work-todo/` with `--skip-plan`. The id
  is the title's slug, with `-2`, `-3`... when taken. stdout is only the new file's path.

State-changing commands (`plan accept`, `plan reject`, `work reject`, `work accept`,
`question answer`, `task retry`, `task stop`, `task discard`) follow one **command
pattern**: resolve the id, take the repo lock (task-files, Write discipline), check that the task's folder has a human row
for the event, do the **outside effect** (here: write the feedback into the task file), then
**fire** the event through `Machine.fire` (states, States). Table rows only change Samba's state, and no
command moves a task or writes the sidecar except through `fire`. Later commands reuse the pattern.

The pattern lives in the use cases of `app/`, not in `entrypoints/cli.py`: `ChangeState` (plan accept and
reject, work reject, task retry, stop, discard), `AnswerQuestion`, `AcceptWork` (async, over the `Vcs`
and `Validator` ports) and `CreateTask` (`task new`). The confirmation policy (`--yes`, no TTY, `[y/N]`) is
`app/confirm.py`, over the `Terminal` port. The use cases never print, read stdin or return exit
codes: they return result objects, and the CLI adapter prints their messages and maps the result
kind to the exit code. The adapters are built only by the composition root (`bootstrap.py`).

- Exit codes: 0 done; 1 wrong state, lock timeout, editor failure, failed preflight, merge or
  validation failure, declined prompt, or a `fire` that did not apply; 2 usage error, unknown or
  ambiguous id, config error, empty `question answer` text, or `work accept` or `task discard`
  without `--yes` and without a TTY. A refusal
  changes nothing.
- On success the command prints only the task file's new path on stdout. The `## Log` line names
  the event, with `feedback round N` when feedback was written.
- Wrong state: stderr says `<id> is in <state>; <event> not allowed. Legal events: a, b` (`none`
  when the state has no human event), listing the events of states, States for that state.
- `plan reject` and `work reject` take `--feedback TEXT` or `--edit` (both together is a usage
  error). `--edit` runs `$EDITOR` (else `$VISUAL`, else `vi`) on an empty temporary file and uses
  its content; an editor that exits non-zero aborts with exit 1 and no change. Feedback is appended
  to the task's `## Feedback` section under a new `### Round N` heading (N is one more than the
  highest existing round), creating the section before `## Log` if missing. Earlier text is never
  rewritten, and `#`/`##` headings inside the text are demoted to `###`. No feedback (or empty)
  is allowed: no round is added and `warning: rejecting without feedback` goes to stderr.
- `plan accept` fires `plan.accept` (states, Planning stage). `plan reject` fires `plan.reject` and leaves
  `plan_session_id` alone. `work reject` fires `work.reject`; with `--fresh` it fires
  `work.reject_fresh`, which also clears `session_id`.
- `question list` prints every open question of every task (tasks in `question/`) as a table with
  columns TASK, QID, STAGE, ASKED, QUESTION. QID is the full name `<task>/<qid>`, ready to paste
  into `question answer`. QUESTION is the text on one line and takes the width left over by the
  other columns, which are never cut. It is truncated with `...` only when it does not fit the
  terminal width (`COLUMNS`, else the TTY size, else 80), and is never narrower than 20
  characters. `task list` uses the same rule for its last column, ERROR (newlines flattened to
  spaces).
- `question show TASK[/QID]` prints the full text, context and answer of one question. Without
  `/QID` it prints every question of the task's latest round with its status. It changes nothing.
- A question is named `TASK/QID`; `TASK` takes a unique prefix as everywhere. An unknown task or
  question is exit 2.
- `question answer TASK[/QID]` records one answer and fires `question.answer` only when it leaves
  no question of the latest round open. The answer is a positional TEXT or `--edit` (exactly one;
  both or neither is a usage error, and so is empty text, exit 2, nothing changed). `--edit` opens
  `$EDITOR` on a file that starts with the question and its context as `# ` comment lines; lines
  starting with `# ` (and bare `#`) are stripped. `/QID` may be left out only when exactly one
  question is open: with several, exit 2 and stderr lists the open `task/qid` names; with none,
  exit 1. Answering a question that is not open (answered or dismissed) is exit 1.
  Under the repo lock the command saves the answer in the sidecar, re-renders `## Questions` (task-files, Write discipline)
  and appends `question.answer: <task>/<qid> answered` to `## Log`; it writes nothing under
  `## Feedback`. When it fires the event, the usual transition line follows and the task goes to
  the todo folder of `last_stage`; with `last_stage` unset the table's first row applies, so it
  goes to `plan-todo/` (move by hand to choose `work-todo/`). stdout is the task file's path.
  When questions remain open, stderr lists them and the task stays in `question/`.
- `task retry` fires `task.retry` (`stuck` only), same destinations as `question answer`. After
  the move, a hint goes to stderr (stdout stays the path; exit 0) according to the
  `blocked_cause` it had: `budget` says to raise the cap in `WORKFLOW.md` first
  (`max_turns`, `max_attempts`, `max_cost_usd_per_task`) or the task goes straight back to
  `stuck`; `dependency_discarded` and `dependency_cycle` say to edit `depends_on` first. Other
  causes print nothing. The command never changes the config.
- `task stop` fires `task.stop` (only `plan-running` and `work-running`): the task goes to
  `stuck/` with `last_stage` set to the stage it was running and `blocked_cause=stopped`, no
  attempt increment. It is not dispatched again: it stays put until `task retry` sends it back to
  the todo folder of its stage (no hint is printed for `stopped`). With the orchestrator running,
  its next tick sees the task left its running folder and cancels the agent, as for a hand move.
  Without an orchestrator the file and sidecar are moved and nothing else happens. An agent
  process left behind by a crashed orchestrator is not killed.
- `task discard` fires `task.discard` (every state but `done` and `discarded`) and is dangerous:
  it uses the confirmation policy of `work accept` (after the legality check and before the lock;
  `--yes` skips it; prompt `Discard task <id>? [y/N]` on a TTY, with the resolved task id, not the prefix typed, anything but `y`/`yes` is exit 1;
  no TTY and no `--yes` is exit 2; nothing changes in either case). Discarding a running task
  moves it at once and the orchestrator then stops the agent; the worktree is removed afterwards
  and the branch is kept (orchestrator, Tick).

**`adr`** commands work on the ADR files `docs/adr/NNNN-title.md` of the repo (ADRs 0001 and
0003). They are plain file operations: no `WORKFLOW.md` (like `dev`), no repo lock, no orchestrator,
and they never commit. Only the front matter of ADR 0001 is parsed (`status`, `date`,
`supersedes`); the number is the filename's.

- **Number forms:** `N` is digits only, so `3`, `03` and `0003` are the same ADR. Anything else
  is exit 2, and so is a number with no file. A file without front matter or without `status` is
  exit 1 naming the file (it also stops `list`). A missing `docs/adr/` is the same as no ADRs.
- `adr list` prints a table with columns NUMBER (four digits), TITLE and SUMMARY, in number order.
  It shows only `accepted` ADRs; `--all` shows every status and adds a STATUS column after
  NUMBER. TITLE is the `# NNNN: Title` heading without the number. No ADR prints the header only.
  SUMMARY takes the width left over, with the truncation rule of `question list`.
- **Summary source** (the open point of ADR 0003, settled here): the first sentence of the
  Decision section, with no extra front matter field. Rule: take the first paragraph or bullet
  of `## Decision`, drop the bullet marker, join wrapped lines with spaces, and cut after the
  first `.` followed by whitespace and a capital letter or backtick, or at the end of that
  paragraph or bullet.
- `adr show N` prints the file unchanged, whatever its status.
- `adr accept N` and `adr reject N` are legal only from `proposed` and set `accepted` or
  `rejected`. `adr supersede N NEW` reads "N is superseded by NEW": N must be `accepted` and NEW
  must be another ADR, `proposed` or `accepted`. It sets N to `superseded` and adds N to the
  `supersedes` list of NEW if absent, leaving NEW's status alone. Both files are checked before
  either is written. An illegal status is exit 1 (`ADR 0003 is accepted; accept not allowed ...`)
  and changes nothing; `supersede N N` is exit 2.
- The edit rewrites only the `status:` line (and the `supersedes:` line, as `[1, 2]`, adding it
  when absent), so the diff is small and the rest of the file is byte-identical. stdout is the
  path of each file written.
- **No confirmation prompt:** unlike `work accept` and `task discard`, these are edits to tracked
  files that `git diff` shows and `git checkout` undoes, and the human reviews them as a diff.
- The default agent allow lists have `adr list` and `adr show` but not the status commands
  (workflow-config, Permissions): accepting is a human decision.

**`explore`** (phase 2 of the ADR flow, ADRs 0002 and 0004) starts an interactive `claude` session
in the repo, for the human to explore a question with the agent and write ADRs. Whether this should
be a command or only a skill (the open point of ADR 0002) is settled here: it is a command, because
it passes the allow list explicitly and is testable with the fake claude.

- The `StartExplore` use case builds a `LaunchSpec` (`domain/launch.py`, pure) and hands it to the
  `InteractiveSession` port. argv: `claude.command`, then `TOPIC` if given (the first prompt),
  `--append-system-prompt <guide>`, `--allowedTools <allow...>`, `--disallowedTools <deny...>`
  and `--model M` when `claude.model` is set. cwd is the repo. Nothing else: no `-p`, no
  `--permission-mode`, no `--setting-sources` or `--settings`. The session is not isolated from the
  user's own settings and CLAUDE.md (running-claude, Interactive explore session), and a tool that
  is neither allowed nor denied asks the human.
- Allow list (ADR 0004): `Bash(samba task new:*)`, `task list`, `task show`, `question list`,
  `question show`, `adr list`, `adr show` (same form), plus `Read`, `Grep`, `Glob`,
  `Edit(docs/adr/**)` and `Write(docs/adr/**)`. Deny list, a hard block even if the user's settings
  allow them: `samba plan`, `work`, `adr accept`, `adr reject`, `adr supersede`, `task discard`,
  `task stop`, `task retry` and `question answer`. The guide text is in prompts, Explore guide.
- Exit code: that of `claude`. `WORKFLOW.md` is read only for `claude.command` and `claude.model`:
  a missing or invalid one is exit 2 (`samba: config error: ...`) and nothing starts. If `claude`
  cannot be started the exit code is 1 with a `samba: cannot start ...` message.
- No repo lock, no journal, nothing is written under `.samba/`: the session's `samba task new`
  calls take the same locks as usual. Samba ignores SIGINT while the session runs, so Ctrl-C
  reaches `claude`.
- The allow and deny rule syntax and their precedence follow Claude Code's and have not been
  verified against a real `claude` by the tests (the fake cannot): check them in one real run.

**`work accept`** merges a reviewed task's branch and fires `work.accept` (`work-review -> done`).
It is the first dangerous command. Moving the file to `done/` by hand stays a plain observed
event and never merges.

- Order: resolve the id; check the state and preflight; `--dry-run` or confirmation; take the
  lock; re-check; merge; fire. The prompt is outside the lock so a slow human never blocks
  ticks. The lock is held while validation runs (up to `validate.timeout_s`), so ticks and other
  commands wait or fail with the lock-busy message meanwhile.
- Preflight, before any change (exit 1, nothing changed): the task is in `work-review`; the main
  checkout is on `base_branch`; it has no uncommitted changes to tracked files (untracked files
  are fine); branch `samba/<id>` exists. With `--no-merge` only the state is checked.
- Confirmation: `--yes` skips it. On a TTY (stdin and stdout) it prints
  `Merge samba/<id> into <base> (N commits)? [y/N]` (naming the validate command when one will
  run; `Mark <id> done without merging` for `--no-merge`); anything but `y`/`yes` is exit 1.
  With no TTY and no `--yes`: exit 2, nothing changed. `--dry-run` runs after preflight, prints
  branch, base, commit count, merge, validate (command or `skipped`) and final state, never runs
  validation, needs no confirmation, exits 0.
- Merge: `git merge --no-ff --no-commit -m "Merge samba/<id>: <title>"`. If
  `validate.command` is set and `--no-validate` is absent, it runs in the main checkout with the
  workspaces, Validation shell and timeout, on the merged but uncommitted result; only a pass runs
  `git commit --no-edit`. This catches a branch that passes alone but fails after merging a main
  that moved on. No `validate.command`: a note on stderr, the merge is committed unvalidated.
  Git identity comes from the user's git config. Full validation output goes to
  `runs/<id>/accept-validate.log`. The branch is kept (deleting branches is a later command);
  the orchestrator's cleanup removes the worktree.
- Conflict: `git merge --abort`, the task stays in `work-review`, exit 1 with the conflicting
  files on stderr, `## Log` line `work.accept: merge failed (conflicts: a, b)`. Other merge or
  commit failures are handled the same way with git's message in the line.
- Validation failure or timeout: merge aborted (`git reset --hard` to the pre-merge HEAD if abort
  fails, safe because preflight proved the tracked tree clean), task stays in `work-review`, exit
  1, `## Log` line `work.accept: validation failed after merge: <last lines joined with " | ">`
  (at most 10 lines, plus `(timed out after Ns)` on timeout). Untracked files left by the command
  are not removed, and tracked edits it makes after a pass stay uncommitted.
- `--no-merge` fires the event without merging or validating (the human already merged);
  `--no-validate` skips validation only. The `## Log` message is `merged <sha>` with
  `, validated` or `, validation skipped`, `no merge`, or `already merged` when the branch has
  nothing to merge (git reports up to date): that is a success, noted on stderr.
- If the commit succeeds but `fire` does not apply, exit 1 with a message that the merge is
  already in the base branch.

Read-only commands (`task list`, `task show`) read folders and sidecars only. They never
need a running orchestrator and change nothing.

- **State arguments** of `task list`: each is an exact state name or a prefix. A prefix expands to
  every state it matches, so `work` is `work-todo`, `work-running` and `work-review`, `q` is
  `question`, and `d` is `done` and `discarded`. An exact name always means just that state. A
  prefix that matches no state is an error: exit 2, the valid states listed on stderr. Several
  arguments give the union, printed in the canonical state order (layout). Columns and cell texts are
  those of `task list` (observability). No matching task prints the header row only.
- **Task id resolver** (shared by every command that takes a task id): an exact id wins, even when
  it is also a prefix of other ids; otherwise a unique prefix over the ids in all state folders.
  An unknown id, or a prefix matching several ids, is exit 2 with a message on stderr (the
  candidates listed when ambiguous).
- **`task show ID`** prints `key: value` lines, `-` for unset values: `id`, `title`, `state`,
  `blocked_cause`, `priority`, `attempts`, `turns`, `cost`, `last_outcome`, `last_error` (full
  text), `retry_in` (only while in a retry delay), `depends_on` (`-`, or one `  <id> (<state>)`
  line each, `unknown` for an id with no task file) and, for a held todo task,
  `dependency_status`, then `branch`, `worktree`, `session_id`, `plan_session_id`, and `events:`:
  the human events legal in the task's state, one `  <event> -> <state>` line each, computed
  from the transition table (states, States) with the `last_stage` guards applied to the sidecar, or
  `events: (none)` (`done`, `discarded`).

On Ctrl-C: kill all agent processes, move their tasks back to the todo folder of their stage
(`plan-todo/` or `work-todo/`, no attempt increment), exit.

