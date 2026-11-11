---
status: accepted
date: 2026-11-11
supersedes: []
---

# 0013: Every command is one use case, and user interfaces are thin

## Context

The use cases of ADR 0011 print nothing and return results, but the command line still carries
work that any other interface would have to copy: `cli.py` resolves task ids in three places,
repeats the printing of a result (location, notes, refusal) per command, and chooses the use case
with a chain of string comparisons on the command name. A web page or an MCP server would
reimplement all of it, and could drift from the command line.

## Decision

- Every command a person can give is one use case in `app/`, named for what the person does. It
  takes plain values (strings, numbers, booleans), never a parsed argument object, and returns one
  of a small closed set of results: done (with a location and notes), a table, text, written files,
  or a refusal with a kind.
- Resolving a task id or a unique prefix, and any other input rule, happens inside the use case.
  An interface passes what the person typed.
- `bootstrap` returns one object that exposes these use cases (today's `Services`). The use cases
  are the contract with the outside. There is no interface or base class for "a UI".
- What a use case needs from the person while it runs (a confirmation, a text to write) is a port
  the interface provides (today `Terminal`). A non-interactive interface passes the answer up
  front instead, for example with `yes`.
- An entry point only turns its own input into a use case call and the result into its own
  output. It holds no rule, and no entry point calls another.

## Consequences

- `cli.py` shrinks to parsing, one call and rendering, and a web or MCP interface becomes a small adapter over the same use cases. Which second interface comes first is not decided here.
- The result types become a stable contract. That also helps the rewrite of ADR 0010: it has to
  reproduce them, not the Python code around them.
- `run` and `explore` are not covered: `run` is a long-lived loop (ADR 0015) and `explore` hands
  the terminal to another program (the `InteractiveSession` port).
- Use case tests gain the id-resolution cases that were only reachable through the command line.
