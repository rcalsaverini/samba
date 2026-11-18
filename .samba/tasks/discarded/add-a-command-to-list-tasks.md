# Add a command to list tasks

I should be able to: list tasks by status.

> symphony list plan
should give a table with planned tasks

## Plan
### What changed after feedback

The human said this task conflicts with a broader command-creation effort and should be merged and refined with it. I read the siblings (I cannot edit them, so this plan is made merge-friendly instead):

- `explore-ideas-on-commands` (plan): feedback asks for clearer names than `approve`/`accept` (`approve-plan`, `accept-review`), proposes command trees (`symphony plan new|accept|reject --feedback|discard`, `symphony review accept|reject`), `edit` instead of `open`, and asks whether this is a state machine.
- `new-command-for-approving-tasks` (plan-review): flat `symphony approve <id>`, which the feedback above says is too ambiguous.
- `add-a-feedback-command-for-plans-reviews` (plan-review): `symphony feedback <id> --short S [--long L]`, a transition-free write. It plans to reuse `_print_table`, state resolution and the `--repo` loop from this task.

Conclusion for `list`: it is a **read-only query, not a transition**, so it is unaffected by the flat-vs-tree and state-machine debate. Transition commands (approve-plan, accept-review, reject, answer, retry) mutate state; `list` and `show` only observe it. Keeping that split is itself the answer to "are we modelling this as a state machine": queries on one side, transitions (one table of allowed `src -> dst` moves) on the other. I do not touch that design here.

Naming decision for this task: keep **top-level `symphony list [STATE]`**. Under a tree design, `list` stays a top-level query (`symphony list plan` reads naturally and is the user's explicit request); a tree could later add per-group aliases such as `symphony plan list` calling the same function, without changing the core. State names in the CLI are always the folder names, which both naming schemes share.

### Approach

`symphony list [STATE] [--repo PATH]` prints a table of tasks in one state (all states when STATE is omitted).

Settled details (record in SPEC §10 and §11 and in the task `## Log`):
- **State matching**: exact state name wins (`plan` means only the `plan` folder, never `plan-review`). Else a unique prefix (`rev` -> `review`, `plan-r` -> `plan-review`). Unknown or ambiguous: exit 2, stderr lists valid states. The state-matching function is generic so sibling commands (transitions, `show`) can reuse it.
- **Columns**: ID, STATE, PRIORITY, TITLE; running tasks show `running (plan|execute)` in STATE, as `status` does (SPEC §14.8). Header always printed, even when empty.
- **Order**: by state in `STATES` order, within a state by (priority None last, then id). Reuse a dispatch sort helper from `orchestrator.py` only if one exists and is cheap to import; else inline.
- Read-only: no directory creation, no log writes, no orchestrator needed.
- `status` stays as is (cost/attempts view); `list` is the lightweight "what is in this folder" view. Out of scope: `--json`, `--needs-me`, `show` (belong to the umbrella task).

Merge-friendliness:
- Put shared helpers in `cli.py` as small module-level functions: `_print_table(rows)` (extracted from `cmd_status`, output unchanged) and `resolve_state(arg) -> State | None`.
- Register the command with minimal edits to `main()`: one subparser, one dispatch branch. If a sibling lands first and made dispatch table-driven, follow that and rebase.
- Tests go in a new `tests/test_list.py` so they do not conflict with edits to `tests/test_blackbox.py` by siblings.

### Steps
- [ ] Coordination first: check `git log` and `src/symphony/cli.py` for already-merged sibling work (`feedback`, `approve*`, `docs/command-ideas.md`). If it exists, rebase onto it, reuse its helpers and naming, and mention in `## Log` what was reused.
- [ ] Read SPEC §10, §11, §14.8; `tests/conftest.py` (`Sandbox.add_task(id, state=, priority=, title=)`, `run`, `write_sidecar`).
- [ ] Write black-box tests first in `tests/test_list.py` (subprocess only, never import `symphony`; import the `sb` fixture the way `test_blackbox.py` gets it, via conftest):
  - `list plan` shows ids and titles of `plan/` tasks and not those in `plan-review/` or `todo/`.
  - `list todo` with priorities 1, 3, none and tie-breaking by id: order of rows.
  - `list` with no argument: tasks from several states with a state column, in `STATES` order.
  - Empty state: exit 0, header only.
  - `list rev` resolves to `review`; `list p` (ambiguous) and `list bogus`: exit 2, stderr names valid states.
  - `list running` with a sidecar `{"phase": "plan"}` shows `running (plan)`.
  - `--repo` is respected and `list` creates no directories (check the tasks dir listing is unchanged).
- [ ] Run `uv run pytest -q tests/test_list.py` and confirm failure for the right reason (unknown subcommand).
- [ ] Implement in `src/symphony/cli.py`: `_print_table`, `resolve_state`, `cmd_list(config, state_arg)`, `list` subparser (`state` with `nargs="?"`), add to the `--repo` loop, dispatch, docstring (`run | status | list | new`). Strict pyright; import `State`, `STATES` from `symphony.tasks`; no `Any`.
- [ ] Update SPEC.md §10 (list bullet) and §11 (synopsis plus matching, columns, ordering, exit codes; state explicitly that `list plan` means the `plan` folder only). No em-dashes. Update the CLAUDE.md `cli.py` map line.
- [ ] Append a `## Log` line to the task file naming the settled spec details and which sibling code (if any) was reused.
- [ ] Run `uv run pyright`, then `uv run pytest -q`, as separate plain commands. Do not commit without asking the user.

### Files to change
- `tests/test_list.py` (new)
- `src/symphony/cli.py` (helpers, command, wiring)
- `SPEC.md` (§10, §11), `CLAUDE.md` (map line)
- Task file `## Log`
- No change expected in `tasks.py`, `conftest.py`, `fake_claude.py`.

### Risks
- Merge conflicts in `cli.py` `main()` with the `feedback`, `approve*` and explore-derived tasks. Mitigation: minimal footprint (one subparser, one branch, two helpers), new test file, rebase on whichever lands first.
- Helper duplication: the feedback plan expects `_print_table`/state resolution from here. If it lands first, reuse instead of redefining.
- Naming churn: if a command tree wins, `list` may gain aliases; the core function is unaffected.
- Ambiguity of "planned tasks": chosen as the `plan` folder only; the question below asks the human to confirm.
- Refactoring `cmd_status` could change its output; the helper must keep per-line `.rstrip()` so `test_status_command_lists_tasks` still passes.

### How to verify
- `uv run pytest -q tests/test_list.py` (seen failing first), then `uv run pytest -q` and `uv run pyright` clean.
- Manual: `symphony new "A" --plan`, `symphony list plan` shows A; `symphony list todo` shows header only; `symphony list nope` exits 2.

### Suggested subtasks
If the human merges the command tasks into an umbrella "Human command surface", this task is its query slice: (1) naming and state-machine decision, (2) feedback primitive, (3) transition commands, (4) `list` (this plan, ready as is), then `show` and `status` improvements. `list` can ship first because it does not depend on (1) to (3).

## Questions
1. Do you want these command tasks merged into one umbrella task? This plan keeps `list` independent so it can ship before or after that decision. 2. Is top-level `symphony list [STATE]` acceptable if the umbrella adopts command trees (with `symphony plan list` possible later as an alias)? 3. Confirm `symphony list plan` means the `plan` folder only, not `plan-review`.

## Log
- 2026-11-06 23:03 symphony: planned, moved to plan-review (turns 1, $0.12): Add `symphony list [STATE]` (with unique-prefix matching so `list plan` shows the `plan` state), reusing the status table code, with black-box tests first and a SPEC update.
- 2026-11-06 23:17 symphony: planned, moved to plan-review (turns 2, $0.35): Revised plan: `symphony list [STATE]` is now a self-contained, read-only query that fits any naming outcome of the umbrella command effort (flat or tree). It ships shared helpers the sibling tasks reuse, with tests in its own file to avoid merge conflicts. Merging with the sibling tasks is left to the human.
- 2026-11-07 01:16 symphony: task.discard: stuck -> discarded: observed hand move
