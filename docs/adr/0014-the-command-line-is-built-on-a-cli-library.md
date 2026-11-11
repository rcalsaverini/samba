---
status: accepted
date: 2026-11-11
supersedes: []
---

# 0014: The command line is built on a CLI library, with shell completion

## Context

`cli.py` builds its parser by hand with `argparse`: about 100 lines of `add_argument` calls, a
second pass to add `--repo` to every sub-parser, and a dispatch by string comparison. It is long for
what it does, the help is plain, and there is no shell completion, which matters for a tool whose
commands take task ids. With ADR 0013 the command line becomes a thin adapter, so replacing the
parsing layer is now cheap and local.

## Decision

- The command line adapter is written on Typer (built on Click). Each command is a function whose
  signature declares its arguments and options, and the generated help replaces the hand-written
  help.
- Shell completion is a requirement. It covers command names and options, and it completes task
  ids, question ids and ADR numbers by reading them through the use cases, so
  `samba plan accept <TAB>` offers the tasks that can be accepted.
- The command surface does not change: the same commands, arguments, options, exit codes (2 for a
  usage error) and output on stdout and stderr. Only the shape of the `--help` text may change.
- Output stays plain text when stdout is not a terminal, so scripts and the black-box suite
  (ADR 0009) read the same thing as before. Colors and boxes are allowed on a terminal only.
- Considered and not chosen: Click directly (one fewer dependency, but more code per command and
  a weaker completion setup), and staying on `argparse` with `argcomplete` (no new dependency,
  but the parser code stays as long as it is).

## Consequences

- Samba goes from one runtime dependency (`pyyaml`) to a few more. The cost is accepted for the
  smaller adapter and for completion, and the plan checks the real dependency footprint before
  relying on it.
- `tests/test_cli_surface.py` and `tests/test_manual.py` read the `--help` output and are adjusted
  once. The manual gains a section on installing completion.
- The adapter must go through `bootstrap` for every command, as in ADR 0013, so the library never
  reaches into the domain or the adapters.
- Depends on ADR 0013: without thin use cases the library would only move the same duplication.
