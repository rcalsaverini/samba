# Method packs and `samba init`

A **method pack** is a directory of plain files that mirrors a project tree, shipped inside Samba as
package data (`src/samba/packs/<name>/`). `samba init` writes one into a repository so a new
project can start using Samba. Read this chapter when changing what `init` writes, the packs, or
the markers inside them. The command line is in the `cli` chapter (init).

## What a pack is

- A pack has a name (its directory name). A file of the pack is at its relative path in the
  project: `WORKFLOW.md`, `CLAUDE.md`, `docs/adr/0000-record-architecture-decisions.md`.
- Files are text (UTF-8) and are copied verbatim, except for the two markers below. In particular
  `{{ task.title }}` and the other `{{ ... }}` of Samba's own prompt rendering pass through
  untouched.
- The known packs are those under `packs/`. Today there is one: `base`. The default method is
  `base` (one constant, `DEFAULT_METHOD`, in `app/init_project.py`).

## Overlay

The files of the chosen method overlay those of `base`: the result has every path of both, and
where both define a path the method's file wins. With `--method base` (or by default) there is
nothing to overlay. The overlay is a rule of the use case (`InitProject`), not of the adapter that
reads the packs.

## Never overwrites

A file that already exists in the repository is skipped, left as it is, and reported as
`skip PATH (exists)`. `init` never commits, creates parent directories as needed, and refuses a
path that is absolute, contains `..` or resolves outside the repository (exit 1; nothing outside
the repository is ever touched). It does not create `.samba/`: the commands that need it create it
when they first run.

## Markers

Two fixed markers are filled by a pure function (`domain/pack_markers.py`). Nothing else is
templated.

- `@@DATE@@`, anywhere in a file, becomes today's date as `YYYY-MM-DD` (from the clock's `Now`).
- `@@VALIDATE@@`, alone on its own line (used in `WORKFLOW.md`), becomes either these two lines,
  when a validation command is given (the command is quoted with `json.dumps`, which is valid
  YAML for any text):

  ```
  validate:
    command: "make check"
  ```

  or, when it is not, two comment lines:

  ```
  # validate:
  #   command: set your validation command here
  ```

## The validation command

`--validate COMMAND` gives it up front. Without the flag, on an interactive terminal `init` asks
once (`Validation command (empty to skip): `); an empty answer or the end of input means skip.
Without a terminal and without the flag it skips silently. Skipped means the commented form above.
`--dry-run` asks nothing. While `validate.command` is unset, Samba warns (workflow-config,
Validation warning).

## What `base` creates

- `WORKFLOW.md`: `max_turns: 15`, `claude.model: sonnet`, the `@@VALIDATE@@` line, no `allow` list
  (Samba's defaults apply), and a generic protocol as its body: the task, read `CLAUDE.md` and
  `docs/spec/README.md` first, tests first, update the spec in the same change and log it, propose
  an ADR when a real decision is made, run `samba adr list` and `samba adr show N` before
  designing. It loads through the normal config loader.
- `CLAUDE.md`: a skeleton with a Map (spec and ADRs), a Checks section and a Conventions section,
  the last two with placeholders to fill in.
- `docs/adr/0000-record-architecture-decisions.md`: ADR 0, accepted, dated by `@@DATE@@`, in the
  format `samba adr` reads.
- `docs/spec/README.md`: the title, one sentence about the spec, and an empty index with a comment
  to add chapters.
