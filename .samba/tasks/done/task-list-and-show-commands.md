---
priority: 1
---
# Task list and show commands

Phase 2, first command task. Add the read-only commands and the shared helpers the later command
tasks reuse.

Read first: `docs/command-ideas.md` sections 2.2, 5.1, 5.2 and 6.1; SPEC §4.1 (table), §10, §11,
§15; `src/symphony/cli.py` (`status`), `transitions.py`, `deps.py`.

Decisions already made by the human:

- Noun-verb grammar (`symphony <noun> <verb>`). The canonical forms are `symphony task list` and
  `symphony task show`; top-level `symphony list` and `symphony show` are aliases.
- Commands work without a running orchestrator and never require one.

Scope:

- `task list [STATE...]`: one row per task, like `status`, filtered to the given states. A state
  argument accepts a unique prefix (`list work` matches `work-todo`, `work-running`,
  `work-review`; `list q` matches `question`). Same columns as `status`, including
  `waiting on ...` for dependency-held tasks. Consider whether `status` becomes `task list` with
  no filter (keep `status` working either way).
- `task show <id>`: the task's title, state, `blocked_cause`, attempts, turns, cost, last
  outcome and error, `depends_on` with each dependency's state, branch, worktree path, session ids,
  and the **legal human events** for its current state, read from the transition table (for
  example, a task in `plan-review` lists `plan.accept`, `plan.reject`, `task.discard`).
- A shared **task id resolver**: exact id, or a unique prefix; ambiguous prefix or unknown id is
  exit code 2 with the candidates listed. Later command tasks reuse it.
- A shared table printer if `status` and `task list` duplicate code.
- `--repo` like the other commands.

Out of scope: any command that changes state.

Acceptance criteria:

- Black-box tests: filtering by full name and by prefix, several states, unknown or ambiguous
  state prefix, `show` on tasks in several states (including the legal events, which must come
  from the table, not a second hand-written list), the id resolver (exact, prefix, ambiguous,
  unknown), aliases behave like the canonical forms.
- SPEC §11 documents the commands; `CLAUDE.md` map updated if new modules appear.
- `uv run pyright` reports 0 errors and `uv run pytest -q` passes.

## Plan
### Approach

Keep `cli.py` thin and put the reusable pieces in a new module `src/symphony/views.py`, so the later command tasks (accept, reject, answer, retry, discard, ...) import them. Nothing here changes state: no `Machine.fire`, no sidecar saves, no orchestrator needed.

Design decisions (settle them in SPEC §11):
- Grammar: `symphony task list [STATE...]` and `symphony task show ID` are canonical. Top-level `symphony list` and `symphony show` are aliases that run the same handlers. `symphony status` stays and is exactly `task list` with no filter (same code path).
- `argparse` layout: a `task` subparser with its own `dest="task_command"` sub-subparsers (`list`, `show`). Alias parsers `list` and `show` get the same arguments from one helper that adds them, so the two forms cannot drift. Every leaf parser takes `--repo`. The test helper `sb.run(*args)` appends `--repo` after the args, so `--repo` must be accepted after the positionals on each leaf.
- State argument matching (`resolve_states`): the argument is an exact state name or a unique-prefix match over `STATES`. Exact match wins (so `plan-review` is exact, never ambiguous). A prefix matching several states is a valid group, and the spec says `list work` expands to `work-todo`, `work-running` and `work-review`, and `q` is `question`. So "ambiguous" here means a prefix that matches no state, which is an error. Do NOT treat multi-match as an error for states. Unknown prefix: exit 2, message lists all valid states. Several arguments: union, output in canonical `STATES` order. Document this in §11. The task text says "unknown or ambiguous state prefix"; the only ambiguity-like case is `d`, which matches `done` and `discarded`. Under the group rule `d` expands to both. Record this reading in SPEC and the task Log. It is an open question for the human (see Questions), but the plan proceeds with the group rule.
- Task id resolver (`resolve_task_id(store, text) -> str`, raising `ResolveError` carrying candidates): exact id (via `TaskStore.state_of`) wins even if it is also a prefix of other ids. Otherwise a unique prefix over ids across all `STATES` folders. Unknown or ambiguous: the CLI prints `symphony: ...` to stderr, lists the candidates (ambiguous) or says unknown, and returns exit 2. Build the id list with `TaskStore.list(state)` over `STATES`. Note that `list` skips invalid file names, which is fine.
- Table printer: extract the body of `cmd_status` into `task_rows(tasks, sidecars, states) -> list[list[str]]` plus `print_table(rows)` in `views.py`. `cmd_status` and `cmd_task_list` both call them. Keep the columns identical (ID, STATE, ATTEMPTS, TURNS, COST, LAST, ERROR), the `question (cause)` / `stuck (cause)` display, the `retry in Ns` text and `waiting on ...` text. Existing status tests must pass unchanged. A list with no matching tasks prints just the header row, as `status` does today (check what `status` does for an empty repo and match it).
- `task show ID` output: plain `key: value` lines, stable and greppable. Fields:
  - `id`, `title` (`Task.title`), `state` (folder, with `(blocked_cause)` suffix or a separate `blocked_cause:` line, use a separate line, `-` when unset), `priority`
  - `attempts`, `turns`, `cost` (`$x.xx`), `last_outcome`, `last_error` (full, not truncated to 60)
  - `depends_on`: one line per dependency as `  <id> (<state or unknown>)` using `store.state_of`. Also print the `deps.evaluate` kind when it is not `ready` for a todo task (waiting, discarded, cycle).
  - `branch`, `worktree` (`Sidecar.workspace`), `session_id`, `plan_session_id`, `not_before` as a retry hint if in the future. `-` for unset.
  - `events:` the legal human events for the current state, computed by a new helper in `transitions.py`: `human_events(src: State, side: Sidecar) -> list[Transition]` = rows with `actor == "human"` and `src == state`, filtered with the existing `_own_guards_ok` (`last_stage` guards) and de-duplicated by event name in table order. Print `event -> dst`, for example `plan.accept -> work-todo`. For `question` and `stuck` the table has `last_stage=plan|work|unset` variants; with the guard filter only the matching row shows, and `unset` sidecars show the todo target the unset row gives. Make the helper public (rename or wrap `_own_guards_ok` rather than duplicating logic) so `next` and the transition commands can reuse it later. Terminal states (`done`, `discarded`) show `events: (none)`.
  - Do NOT hand-write an event list anywhere. The test must compare against the table (see tests).
- Tasks in `done` or `discarded` still show fine. Show reads the task via `TaskStore.find(id)` after resolving.
- `--repo` and config: reuse the existing `load_config` error path (exit 2). Commands only need `config.symphony_dir`, so they must not start the orchestrator or touch locks. Check that `load_config` does not require anything a missing orchestrator would provide (it already works for `status`).

### Steps

- [ ] Read `tests/test_blackbox.py` around `test_status_command_lists_tasks` (line 415) and the `Sandbox` helpers in `tests/conftest.py` (`add_task`, `write_sidecar`, `run`) to copy their style. Also read `tasks.py` `TaskStore` (`list`, `find`, `state_of`) and `Sidecar`.
- [ ] Write black-box tests first (list below) in `tests/test_blackbox.py`. They must not import the `symphony` package. For the table-derived events test, call `sb.run("transitions")` and parse the Markdown rows (`| \`event\` | \`from\` | \`to\` | who |...`) in the test, then assert `show` output for a task in each state lists exactly the human events from that parsed table.
- [ ] Run the new tests and confirm they fail for the right reason.
- [ ] Add `human_events` (public, guard-aware) to `transitions.py`, reusing `_own_guards_ok`.
- [ ] Create `src/symphony/views.py` with `task_rows`, `print_table`, `resolve_states`, `resolve_task_id` (+ `ResolveError`), and `render_show`. Fully typed, strict pyright, no `Any`.
- [ ] Refactor `cli.py`: `cmd_status` calls `task_rows`/`print_table` with all states; add `cmd_task_list` and `cmd_task_show`; extend `main` with the `task` group and the `list`/`show` aliases; keep `--repo` on every leaf; map `ResolveError` and unknown states to exit 2 with a message on stderr. Update the module docstring to list the new commands.
- [ ] Update SPEC §11 (command usage block with `task list`, `task show`, aliases, state-prefix rule, id resolver rule, exit codes, no orchestrator needed; `status` is `task list` with no filter) and §10 (the `status` bullet points to the shared table; describe the `show` fields). Add a short note on the `d` prefix and group rule.
- [ ] Update the `CLAUDE.md` Map: add `views.py` and change the `cli.py` line to `run`, `status`, `new`, `task list|show` (and aliases).
- [ ] Add a `## Log` line to the task file saying SPEC §10/§11 settled the open details (state-prefix groups, resolver precedence, show format).
- [ ] Run `uv run pyright` (0 errors) and `uv run pytest -q` as separate plain commands.

### Files to change

- `src/symphony/views.py` (new): shared printer, state matcher, id resolver, show renderer.
- `src/symphony/transitions.py`: public `human_events` helper.
- `src/symphony/cli.py`: new commands, `status` refactor, parser layout.
- `tests/test_blackbox.py`: new tests (and `tests/conftest.py` only if a helper is needed, for example a `parse_table` helper; keep it stdlib-only).
- `SPEC.md` (§10, §11), `CLAUDE.md` (map).
- the task file `## Log` (Symphony-owned path, only append the note at the end).

### Tests (black-box, via the CLI)

- list: no args equals `status` output; full state name filter (`plan-review`); prefix `work` returns tasks from `work-todo`, `work-running` and `work-review`; `q` returns `question`; several states (`plan-review stuck`) give the union in canonical order; unknown state (`zzz`) exits 2 and the stderr lists valid states; `waiting on ...`, `question (cause)`, and retry text still appear in the filtered output; `--repo` works; no orchestrator is running.
- show: tasks in at least `plan-review`, `work-review`, `question`, `stuck`, `work-todo` with a dependency, `done`. Check title, state, `blocked_cause`, attempts, turns, cost, last outcome, error, depends_on lines with each dependency's state (including an unknown dependency id), branch, worktree and session ids from a written sidecar, and the events block. `plan-review` lists `plan.accept`, `plan.reject`, `task.discard`. `stuck` with `last_stage` unset lists `task.retry` once. Events derived from `sb.run("transitions")` parsing, not a hand-written list in the test (the table is the single source).
- resolver: exact id, unique prefix, exact id that is also a prefix of another id, ambiguous prefix (exit 2, candidates listed), unknown id (exit 2).
- aliases: `list` and `show` give identical stdout and exit codes to `task list` and `task show`, including error cases; `status` equals `task list`.

### Risks

- The spec wording "ambiguous state prefix" conflicts with "`list work` matches the three work states". The plan treats multi-match as a group and only no-match as an error. If the human wants `d` to be an error, change `resolve_states` to require a unique match unless one exact name exists, but then `work` would fail, which contradicts the task. Flagged in Questions.
- argparse and `--repo` after positionals with `nargs="*"`: test with the `Sandbox.run` ordering (`task list work --repo X`).
- Alias parsers can drift from the canonical ones: build them from one function.
- Guard filtering: `_own_guards_ok` ignores non-`last_stage` guards (they belong to the machine at fire time), so `show` may list an event that `fire` would refuse, for example `dispatch` guards. That is acceptable because show only lists human events, whose only guards are `last_stage=*`. Add a comment.
- Output of `status` must remain byte-identical (existing tests parse it).
- CLAUDE.md says tests must never import `symphony`: keep the table parsing in the test on `symphony transitions` output.

### How to verify

- `uv run pyright` reports 0 errors.
- `uv run pytest -q` passes (about 25 s), including the new tests and all existing status tests.
- Manually in a scratch repo: `symphony task list work`, `symphony list q`, `symphony show <prefix>`, `symphony show nope` (exit 2), with no orchestrator running.
- `grep -n "—"` over changed docs and the new code for em-dashes (none allowed).

### Suggested subtasks

None needed; this fits one session. Optional follow-up for the later command tasks: reuse `resolve_task_id` and `human_events` (for the wrong-state error message and `next`).

## Questions
Ambiguous state prefix: the task says `list work` expands to work-todo/work-running/work-review (a multi-match group), yet also asks for tests on an "ambiguous state prefix". I planned it as: multi-match prefixes expand to all matching states (so `d` means done and discarded), and only a prefix that matches nothing is an error (exit 2). Is that right, or should some prefixes be rejected as ambiguous?

## Log
- 2026-11-07 01:16 symphony: dispatch_plan: plan-todo -> plan-running
- 2026-11-07 01:17 symphony: planned: plan-running -> plan-review: planned (turns 1, $0.20): Add a noun-verb `task` command group (`list`, `show`) with top-level `list`/`show` aliases, backed by a new `views.py` holding the shared table printer, state-prefix matcher and task id resolver. `status` becomes `task list` with no filter. Black-box tests come first, then SPEC §10 and §11 and the CLAUDE.md map are updated.
- 2026-11-07 01:26 symphony: plan.accept: plan-review -> work-todo: observed hand move
- 2026-11-07 01:26 symphony: dispatch_work: work-todo -> work-running
- Implemented task list/show, aliases, views.py, human_events. SPEC §10/§11 settled the open details: state-prefix groups (multi-match expands, only no-match is exit 2; `d` = done + discarded), resolver precedence (exact id wins, then unique prefix), and the show format. Proceeded with the plan's reading of the Questions item.
- 2026-11-07 01:30 symphony: permission denied: Bash (cat >> tests/test_blackbox.py <<'EOF'


# ---- task list / task show (SPEC §11) ----------------------------------------)
- 2026-11-07 01:31 symphony: done: work-running -> work-review: validation passed (turns 2, $0.70): I added `symphony task list [STATE...]` and `symphony task show ID`, with top-level `list`/`show` aliases. `status` now runs the same code as `task list` with no filter. The shared code is in a new `views.py` (table printer, state matcher, id resolver, show renderer), and `show` gets its legal events from the transition table through a new `human_events` in `transitions.py`. I committed the work. The final pyright run reported 0 errors. The full `uv run pytest -q` passed (160 tests) before the last pyright type-annotation fix, and I did not rerun it after that edit. I also updated SPEC §10 and §11, the `CLAUDE.md` map and the task `## Log`. I treated a state prefix as a group, so `work` expands to the three work states and `d` expands to `done` and `discarded`. Only a prefix that matches nothing exits 2. This is the open item under `## Questions`, and I went ahead with it. If you want `d` rejected as ambiguous, `resolve_states` is the place to change, but `work` would then fail too.
- 2026-11-07 01:34 symphony: work.accept: work-review -> done: observed hand move
