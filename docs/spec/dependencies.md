# Task dependencies

Front matter `depends_on: [task-id, ...]` (optional, human-owned, task-files, Format) names tasks that must be
finished first. It is a guard on the dispatch rows, not a state: a waiting task stays in its
`plan-todo/` or `work-todo/` folder and no folder is added.

- **Guard `deps_met`** (on `dispatch_plan`, `dispatch_work` and `route_to_plan`): every listed id is
  in `done/`. `done` means merged, so the worktree of the dependent task, branched from the base
  branch at dispatch, already contains the dependency's work. `discarded/` does not count. The
  guard gates planning as well as execution.
- **Waiting:** while any id is in another folder (including `plan-todo/`, `work-todo/`, a review
  folder, `question/`, `stuck/`) the task is simply not a dispatch candidate. It does not count
  toward `max_concurrent`.
- **Unknown id** (no task file in any folder): treated as unmet, and a warning
  `event=unknown_dependency task=<id> dependency=<id>` goes to `samba.log` once per pair. A typo
  never unblocks a task.
- **A dependency in `discarded/`:** the dependent task fires `dependency_discarded` and goes to
  `stuck/` with `blocked_cause = dependency_discarded` (its `## Log` names the ids). Sending it back
  by hand (`task.retry`) checks the dependencies again.
- **A dependency cycle** (a task that can reach itself through `depends_on` edges of tasks that are
  not `done`, a self-dependency included): every task in the cycle fires `dependency_cycle` and
  goes to `stuck/` with `blocked_cause = dependency_cycle`. A task that only depends on a cycle
  keeps waiting.
- **`samba task list`** shows `waiting on <id>[, <id>...]` in the last-outcome column for a task in
  a todo folder held only by dependencies (not in a retry delay), listing the ids not yet `done`.
- **`--exit-when-idle`** (cli): a todo task held only by dependencies does not keep the run alive,
  so a dependency waiting for a human cannot hang it. A dependency that is itself runnable in a todo
  folder does.
- A `depends_on` that is not a list of strings is ignored (task-files, Format).
