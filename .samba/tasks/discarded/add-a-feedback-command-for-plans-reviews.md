# Add a feedback command for plans-reviews

I whould be able to run:

> symphony feedback <task-id> --short <short-description> [--long <optional-longer-body>]

And this should add to the feedback section in the plan:

```md
### feedback

- <short-description>:
  <optional-longer-body>
```

## Plan
### What changed after feedback

The human said this task conflicts with a broader command-creation effort and should be merged and refined with it. I read the sibling tasks:

- `explore-ideas-on-commands` (plan): its feedback proposes command trees (`symphony plan accept|reject --feedback|discard`, `symphony review accept|reject`), clearer names than `approve`/`accept`, `edit` instead of `open`, and asks whether this is a state machine.
- `new-command-for-approving-tasks` (plan-review): a flat `symphony approve <id>` (plan-review to todo, review to done with merge).
- `add-a-command-to-list-tasks` (plan): `symphony list [STATE]`.

I cannot edit those files, so this plan makes the feedback task merge-friendly instead. It splits the work into a command-agnostic core (needed by every variant of the naming) and a thin CLI surface whose names are settled by the umbrella decision.

### Approach

1. **Core primitive (independent of naming):** a pure function `append_feedback(text, short, long) -> str` and `TaskStore.add_feedback(task_id, short, long)` in `tasks.py`. Entry format:
   ```
   - <short>:
     <long line 1>
     <long line 2>
   ```
   (only `- <short>` when no long body). Appended at the end of the existing `## Feedback` section (SPEC 3.2, 8.3, 14.5 use `## Feedback`; the `### feedback` in the task text is read as that section, no new heading). The section is created before `## Log` if missing. Lines of `--long` are indented so `#`/`##` lines cannot split sections. This is the same primitive the future `plan reject --feedback` and `review reject` commands need, so the merged work reuses it unchanged.
2. **Pure feedback, no transition:** the command only writes the entry and prints the task path. It never moves the file. Transitions (plan-review to plan, review/blocked to todo) belong to the transition commands from the umbrella task, which can call `add_feedback` and then `TaskStore.move`. This keeps `feedback` safe and composable, and answers the state-machine concern: writing feedback and changing state are two separate operations.
3. **CLI surface, final name pending the umbrella decision:** ship `symphony feedback <id> --short S [--long L]` as requested (it is the user's explicit spec and is unambiguous, not clashing with `approve`/`accept`). If the tree design wins, register the same function as an alias or sub-action (for example `symphony plan reject --feedback`), without touching the core. Keep the dispatch in `cli.py` table-driven (one function per command, shared `--repo` option loop) so the sibling tasks add commands without merge conflicts in `main`.
4. **Safety:** refuse when the task is in `running` (an agent may be editing the file, SPEC 3.3), exit 1 with a clear message. All other states are allowed. Unknown or invalid id (`is_valid_id`) exits 1, empty or whitespace `--short` exits 2, `--short` with newlines is collapsed to one line.

### Steps

- [ ] Coordination: check which sibling tasks are already implemented (`git log`, `cli.py`). Rebase on them if so. Reuse their shared helpers (`_print_table`, state resolution, `--repo` loop) and do not duplicate them. If an umbrella design note exists (for example `docs/command-ideas.md` from the explore task), follow its naming and mention the choice in `## Log`.
- [ ] Read SPEC 3.2, 3.3, 4.1, 11, 14.2, `tests/conftest.py` (`Sandbox.run`, `add_task`, `task_text`, `state_of`), and `TASK_TEMPLATE` in `prompts.py` for the Feedback placeholder.
- [ ] Black-box tests first, in `tests/test_feedback.py` (subprocess only, never import `symphony`):
  - [ ] short only: exit 0, one `## Feedback` section with `- <short>`.
  - [ ] short + multi-line long: `- <short>:` then each body line indented 2 spaces.
  - [ ] second call appends after the first, in order, one section.
  - [ ] missing section is created before `## Log`; `## Plan` and `## Log` content untouched.
  - [ ] existing `## Feedback` content is kept.
  - [ ] works in `plan-review`, `review`, `blocked`, `todo`, `plan`; the task stays in its folder.
  - [ ] `running`: non-zero exit, file unchanged.
  - [ ] unknown id, invalid id (`../x`), missing or empty `--short`: non-zero, no file changes.
  - [ ] `--long` containing `## ` lines does not create a second section.
  - [ ] end to end: feedback on a `plan-review` task, move it to `plan`, run idle with the scripted fake, and check the revise prompt run saw the feedback in the task file.
- [ ] Run the new tests and confirm they fail for the right reason.
- [ ] Implement `append_feedback` and `TaskStore.add_feedback` in `tasks.py` (model on `append_to_log_section`; stop the section at the next `## ` line only), then `cmd_feedback` and the `feedback` subparser in `cli.py` (positional `task_id`, required `--short`, optional `--long`, `--repo`). Update the module docstring. Strict pyright, no `Any`.
- [ ] Update SPEC.md: section 11 (synopsis), 3.2/3.3 (entry format; the CLI is a human-initiated write and is refused while `running`), 14.2 (feedback may be written with the command, the human still moves the file). Update the CLAUDE.md map line for `cli.py`. No em-dashes.
- [ ] Add a `## Log` line naming the settled details (entry format, no auto-move, `running` refusal, coordination with sibling command tasks).
- [ ] Run `uv run pyright` then `uv run pytest -q`, as separate plain commands. Do not commit without asking the user.

### Files to change

- `tests/test_feedback.py` (new)
- `src/symphony/tasks.py` (`append_feedback`, `TaskStore.add_feedback`)
- `src/symphony/cli.py` (subcommand and dispatch)
- `SPEC.md` (3.2, 3.3, 11, 14.2), `CLAUDE.md` (map line)
- task file `## Log`

### Risks

- Merge conflicts in `cli.py` `main()` with the `list`, `approve` and explore-derived tasks. Mitigation: keep my change to one subparser plus one function, and rebase on whichever lands first.
- Naming churn: if the command tree wins, `feedback` becomes an alias or moves. The core in `tasks.py` is unaffected, and the CLI name is the only thing that changes.
- Section parsing must not be fooled by `##` text in feedback (indent or demote it).
- Writing while an agent runs (mitigated by refusing in `running`).
- Placeholder text under `## Feedback` from the template mixing with entries (check `TASK_TEMPLATE`).

### How to verify

- `uv run pytest -q tests/test_feedback.py` passes (seen failing first), then `uv run pytest -q` and `uv run pyright` are clean.
- Manual: `symphony new "x" --plan`, then `symphony feedback x --short "use sqlite" --long "a\nb"`, then check the `## Feedback` block.

### Suggested subtasks

If the human prefers to do the merge now: one umbrella task "Human command surface" with ordered subtasks: (1) naming and state-machine decision (tree vs flat, `plan-*`/`review-*` names, `edit` not `open`), (2) this feedback primitive plus command, (3) transition commands built on `add_feedback` and `TaskStore.move` (approve-plan, accept-review, reject, answer, retry), (4) `list`/`show`/`status` improvements.

## Questions
1. Do you want these tasks merged into one umbrella ("Human command surface") now? If so, which naming wins: the flat `symphony feedback`/`approve-plan`/`accept-review`, or the tree (`symphony plan reject --feedback`, `symphony review accept`)? This plan ships the flat `feedback` command and keeps the core reusable either way.
2. Should `feedback` stay transition-free (my plan), with state moves left to the transition commands?
3. Refuse writing feedback for a `running` task (my plan), or write anyway?

## Log
- 2026-11-06 23:04 symphony: planned, moved to plan-review (turns 1, $0.14): Add `symphony feedback <task-id> --short ... [--long ...]`, which appends a bullet entry to the task's `## Feedback` section. It reuses the section helpers in `tasks.py`, is tested black-box first, and the spec is updated to match.
- 2026-11-06 23:17 symphony: planned, moved to plan-review (turns 2, $0.40): Revised the plan so the feedback task's core (`add_feedback` in `tasks.py`, plus a thin `feedback` command) is independent of command naming. It is designed to merge with the sibling command tasks (list, approve, explore commands), and it adds a suggested umbrella task split.
- 2026-11-07 01:16 symphony: task.discard: stuck -> discarded: observed hand move
