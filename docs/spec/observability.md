# Observability

- `samba.log`: one line per event, `key=value` style, always with `task=<id>`. Logs dispatch,
  turn start/end, outcome, validation result, state moves, failures, cost.
- `runs/`: raw event streams and validation outputs for debugging.
- Task `## Log`: the human-readable summary, one line per worker exit.
- `samba task list` (no filter, cli) prints a table from folders and sidecars: id, state, attempts, turns, cost,
  last outcome, last error. The STATE column is the folder name (`plan-running` or `work-running` says which stage a running task is in); for `question` and `stuck` it is
  followed by the `blocked_cause` in parentheses, for example `stuck (budget)`. A task waiting for a
  retry delay shows `(retry in Ns)` in the last-outcome column. A task in a todo folder held only
  by dependencies (orchestrator, Dependencies; not in a retry delay) shows `waiting on <id>[, <id>...]` there instead.

