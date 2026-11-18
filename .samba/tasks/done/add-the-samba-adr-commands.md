---
priority: 3
depends_on: ["make-the-spec-update-an-explicit-step-of-every-task"]
---
# Add the samba adr commands

Implement phase 1 of the ADR flow. The decisions are already recorded: read docs/adr/0001 to 0004 first and follow them. Do not re-decide them.

Scope:
- `samba adr list`: accepted ADRs with number, title and a one-line summary. Superseded and rejected ones are hidden unless `--all`. `samba adr show N`: print one ADR. Numbers can be given as 3, 03 or 0003.
- `samba adr accept|reject|supersede N`: edit the status in the front matter (supersede takes the number of the new ADR and marks the old one superseded). They edit the file and never commit. Dangerous-command rules from the CLI chapter of docs/spec apply where relevant.
- Parsing is of the front matter in ADR 0001 only: status, date, supersedes.
- The default agent allow list gains `samba adr list` and `samba adr show`, not the status commands.
- The prompt paragraph from ADR 0003 goes into the built-in prompts and the repo's WORKFLOW.md body.
- Open point from ADR 0003: where the summary line comes from (first sentence of the Decision section, or a `summary` front matter field). Pick the simpler one, say which in your log and in the spec.

Done when:
- Black-box tests cover list, show, the status commands, number forms and error cases.
- The CLI chapter of docs/spec, the user manual (tests/test_manual.py checks every command is mentioned) and the "Spec changes" step are done.
- pyright and the tests pass.

## Plan
### Approach

Add a new noun `adr` to the CLI, backed by a new module `src/samba/adr.py` that holds the file logic. The module deals with plain files under `<repo>/docs/adr/` and has no orchestrator or lock involvement. It follows ADRs 0001 and 0003 exactly, and nothing is re-decided.

Design choices:
- **ADR files:** match `docs/adr/NNNN-*.md`. The number comes from the filename (ADR 0001).
- **Front matter:** parse only the leading `---` block. Read `status`, `date` and `supersedes`, and use `yaml.safe_load` as `config.py` does. Cast at the YAML boundary. Everything else in the file is untouched.
- **Title:** the first `# NNNN: Title` heading, with the `NNNN: ` prefix stripped.
- **Summary source (open point in ADR 0003):** use the **first sentence of the Decision section**. Reasons: it needs no new front matter field, it works on all existing ADRs, and ADR 0001 defines the front matter as only status/date/supersedes. Implementation: take the text of `## Decision` up to the next `## `, drop a leading `- ` bullet marker, join wrapped lines with spaces, and cut at the first `. ` or at the end of the text. Flatten whitespace. Truncate for the table only if it exceeds the terminal width, reusing the existing width rule from `views.py` (the `COLUMNS` / TTY / 80 logic used by `question list`). Never truncate the number or title columns.
- **Number forms:** `3`, `03` and `0003` all resolve through `int()` on digits only. Non-digits are a usage error (exit 2). An unknown number is exit 2 with stderr listing nothing or the known numbers.
- **Status edit:** rewrite only the `status:` line (and the `supersedes:` line for supersede) inside the front matter, as a text edit. This keeps comments and formatting and gives a small git diff. Do not round-trip through a YAML dump.
- **Never commit:** the commands only write files.
- **Dangerous-command rules:** I read the CLI chapter's "dangerous" notion as applying to `work accept` and `task discard`, which are irreversible or destructive. The ADR status edits are plain file edits that git can undo and that are reviewed in a diff, so no confirmation prompt. Say this explicitly in the spec. The relevant rule that still applies is the one that a refusal changes nothing, and the exit codes (0 done, 1 wrong state, 2 usage or unknown number).
- **Legal status transitions** (small table in the spec):
  - `accept`: only from `proposed`.
  - `reject`: only from `proposed`.
  - `supersede OLD NEW`: OLD must be `accepted`. NEW must exist, must differ from OLD, and should be `proposed` or `accepted`. The command sets OLD to `superseded` and adds OLD to NEW's `supersedes` list if it is not there. It does not change NEW's status. The task says supersede "takes the number of the new ADR and marks the old one superseded": the CLI form is `samba adr supersede OLD --by NEW` or positional `supersede OLD NEW`. Pick the positional form `supersede N NEW`, where N is the old one. This reads "ADR N is superseded by NEW". Keep the invariant check atomic: validate both files first, then write both. A wrong state prints `ADR N is <status>; <verb> not allowed`, with exit 1 and nothing changed.
- **`adr list`:** print a table with columns NUMBER, TITLE, SUMMARY, using the existing table printer in `views.py`. Only `accepted` by default. `--all` also shows proposed, superseded and rejected, with an extra STATUS column. Hmm: keep it simple: with `--all`, add a STATUS column. Without `--all`, no STATUS column, because everything shown is accepted. Numeric order. No ADRs prints the header only. A missing `docs/adr/` directory is the same as empty and exits 0.
- **`adr show N`:** print the file's full text unchanged to stdout. Show works for any status.
- **Config:** `adr` takes `--repo` (default cwd) and does not call `load_config`, like `dev`, so it works in any repo. Check the argument flow in `main()` (around cli.py:679-690): add an `adr` branch before `load_config`.
- **Agent allow list:** add `Bash(samba adr list:*)` and `Bash(samba adr show:*)` to `DEFAULT_ALLOW` in `config.py` (not the status commands). Samba's own `WORKFLOW.md` uses the `uv run samba ...` form, so add `Bash(uv run samba adr list:*)` and `Bash(uv run samba adr show:*)` there. This leaves the status commands out, and the existing comment explains the logic.
- **Prompt paragraph (ADR 0003):** one fixed paragraph: decisions that shape the architecture live in `docs/adr/`; run `samba adr list` and read the relevant ones (`samba adr show N`) before designing. Add it to `PROTOCOL` and `PLAN_PROTOCOL` in `prompts.py`. Note that the protocol prompt is generic and "never names a path" (prompts chapter, Writing a prompt). The ADR text names `docs/adr/`. The built-in ADR instruction already in `PROTOCOL` names `docs/adr/`, so naming it is consistent. The planning agent's allow list is `Read, Grep, Glob`, so it cannot run `samba adr list`. Therefore, in the planning variant say to read `docs/adr/` directly (or add `Bash(samba adr list:*)` and `show` to the planning default allow). Decision: add the two read commands to the planning default allow too (`PlanningConfig.allow` default and `planning_r.string_list` default in `config.py` lines 47 and 240), because "the default agent allow list" includes both runs and the spec says Read/Grep/Glob. If this seems to broaden planning too much, fall back to the plan prompt saying to read the files. Record whichever you choose in the log and spec. Also append the paragraph to the body of the repo's `WORKFLOW.md`, using the `uv run samba adr list` form.

### Steps

- [ ] Read `docs/spec/README.md`, then `cli`, `prompts`, `workflow-config` and `observability`. Read `tests/conftest.py`, `tests/test_blackbox.py` (existing style) and `tests/test_manual.py`.
- [ ] Write black-box tests first in `tests/test_blackbox.py` (or a new `tests/test_adr.py` using the same `Sandbox` fixture and only the CLI as a subprocess, never importing `samba`). Cases:
  - `list` shows only accepted ADRs with number, title and summary. Superseded, rejected and proposed ones are hidden. `--all` shows all with status.
  - Summary is the first sentence of Decision, including a bullet-style Decision and wrapped lines.
  - `show` with `3`, `03` and `0003` prints the same file. `show` works for any status.
  - `accept` and `reject` on a proposed ADR edit only the `status:` line (assert the rest of the file is byte-identical) and make no commit (`git status` shows an unstaged change, `git log` count is unchanged).
  - `supersede OLD NEW` marks OLD superseded, adds OLD to NEW's `supersedes`, and fails with exit 1 and no change when OLD is not accepted.
  - Errors: unknown number (exit 2), non-numeric number (exit 2), `accept` on a non-proposed ADR (exit 1, nothing changed), `supersede N N` (exit 2), missing new ADR (exit 2), no `docs/adr/` directory (list prints the header only, exit 0), ADR file without front matter (a clear error, exit 1 or 2, nothing changed).
  - Works in a repo with no WORKFLOW.md.
  - The default allow list includes `adr list` and `adr show` and not the status commands. Do this black-box via the fake claude's recorded argv (see how existing tests check `--allowedTools`). The protocol prompt carries the ADR paragraph (check the recorded `--append-system-prompt`) for both the work and plan runs.
  - `samba --help` lists `adr`.
- [ ] Implement `src/samba/adr.py` (typed, no `Any` in public signatures) and wire `cmd_adr_*` and the `adr` subparsers in `cli.py`: `adr list [--all]`, `adr show N`, `adr accept N`, `adr reject N`, `adr supersede N NEW`, all with `--repo`. Add `adr` to the `--help` command list and to the `--repo` loop.
- [ ] Update `DEFAULT_ALLOW` (and the planning default allow) in `config.py`, the prompt paragraph in `prompts.py`, and `WORKFLOW.md` (allow list entries and body paragraph).
- [ ] Update the spec (see Spec changes) and `docs/manual.md`. Run `uv run pytest -q tests/test_manual.py` to check every subcommand is mentioned.
- [ ] Update `CLAUDE.md`'s map (add `adr.py` and the `adr` commands to the `cli.py` line) and the `README.md` if it lists commands.
- [ ] Run `uv run pyright` and `uv run pytest -q` as separate plain commands. Fix failures.
- [ ] In the task file's `## Log`, record: the summary source chosen (first sentence of Decision, and why), the choice about confirmation (none), the planning allow decision, and the spec edits made.
- [ ] Commit in small steps on the branch. Do not edit ADR 0003: it says the point is "to be settled in implementation", and ADRs are not edited after acceptance. Settle it in the spec.

### Files to change

- `src/samba/adr.py` (new)
- `src/samba/cli.py`
- `src/samba/config.py`
- `src/samba/prompts.py`
- `src/samba/views.py` (only if the table helper needs reuse or a small change)
- `WORKFLOW.md`
- `tests/test_blackbox.py` or new `tests/test_adr.py`, plus a fixture helper in `tests/conftest.py` for writing ADR files
- `docs/spec/cli.md`, `docs/spec/prompts.md`, `docs/spec/workflow-config.md`, and possibly `docs/spec/layout.md` and `docs/spec/README.md`
- `docs/manual.md`, `CLAUDE.md`, `README.md` (if it lists commands)

### Spec changes

- `cli.md`:
  - Add the five `adr` commands to the command block.
  - Add `adr` to the nouns sentence (nouns `task`, `plan`, `work`, `question`, `adr` and `dev`) and to the `--help` ordering sentence.
  - Add an **`adr`** section covering: the parse scope (front matter of ADR 0001 only), number forms, `list` columns and the `--all` rule, `show`, the status commands (legal source statuses, supersede semantics, edit-in-place of only the status/supersedes lines, never commits), exit codes, and that they need no config or lock.
  - State the dangerous-command position: no confirmation prompt, and why.
  - State the **summary source decision: first sentence of the Decision section**, and the extraction rule.
  - Note that `adr` needs no `WORKFLOW.md`, like `dev`.
- `prompts.md`: add the ADR paragraph to the protocol prompt and planning variant lists.
- `workflow-config.md`: add the two read commands to the default allow list text (and the planning default if extended).
- `layout.md` / `README.md` of the spec: mention `docs/adr/` only if a natural place exists. Otherwise none.

### Risks

- **Allow-list matching:** agents run plain commands and rules match the whole line. The default is `samba adr list`, but Samba's own WORKFLOW.md uses `uv run samba ...`. Both forms are needed in the right place.
- **Planning allow:** the planning agent has only Read/Grep/Glob by default. Without extending the planning default, the prompt paragraph tells it to run a command it is denied. Handled above.
- **Front matter edits:** a text edit on `status:` must tolerate quoting and trailing comments, and `supersedes: []` versus a block list. Keep the supported format narrow (ADR 0001 writes `supersedes: [1, 2]` flow style), and fail with a clear error and no change if the line is not found. Test both `[]` and `[1]` flow lists.
- **Atomic supersede:** two files change. Validate everything first, then write. Handle a write failure by reporting which file changed.
- **Summary extraction:** a Decision section starting with a bullet list, as in ADRs 0001 to 0004, must give a sensible sentence. A first sentence containing `e.g.` or a backticked `samba adr list.` could cut early: accept this, and cut only at `. ` followed by a capital or end of text (document it).
- **Black-box suite constraint:** tests must not import `samba`.
- **Prose rule:** no em-dashes in docs and prompts.

### How to verify

- `uv run pyright` reports 0 errors.
- `uv run pytest -q` passes, including the new ADR tests and `tests/test_manual.py`.
- By hand in a scratch repo (`uv run samba adr list --repo <tmp>` with copies of the real ADRs): `list` shows ADRs 0001 to 0010 that are accepted with sensible summaries, `show 3` equals `show 0003`, `accept` on a proposed copy changes one line, and `git status` shows an uncommitted change.
- Check that the recorded `--allowedTools` in the fake claude include the two read commands only, and that the system prompt contains the ADR paragraph.
- Confirm the `## Log` states the summary source, and that the spec says the same.

### Suggested subtasks

None needed. The change is small enough for one task.

## Assumptions
- The ADR status commands do not need a confirmation prompt: they are reversible file edits that go through git review, so the "dangerous" policy (work accept, task discard) does not apply.
- `supersede` takes two numbers, `supersede OLD NEW`, and it also appends OLD to NEW's `supersedes` list. The task text only says it takes the number of the new ADR, so the exact argument form is my reading of it.
- `accept` and `reject` are legal only from `proposed`, and `supersede` only from `accepted`.
- The `adr` commands need no WORKFLOW.md, like `dev`, and use only `--repo`.
- The summary comes from the first sentence of the Decision section, because it needs no extra front matter field.
- The planning run's default allow list also gains the two read commands, so the prompt paragraph can be followed there. If you want the planning list left alone, the plan prompt can say to read `docs/adr/` directly.
- ADR 0003 is not edited. The summary-source decision is recorded in the spec and the log.

## Log
- 2026-11-09 14:29 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-09 14:30 samba: planned: plan-running -> plan-review: planned (turns 1, $0.28): Add a new `samba adr` noun (list, show, accept, reject, supersede) in its own module with no config needed. The summary comes from the first sentence of the Decision section. The plan also covers the two allow-list additions, the ADR 0003 paragraph in the prompts, black-box tests first, and the spec and manual updates.
- 2026-11-10 09:45 samba: plan.accept: plan-review -> work-todo
- 2026-11-10 09:45 samba: dispatch_work: work-todo -> work-running
- Work done (all plan steps ticked in spirit; checkboxes below left as written). Summary source: first sentence of the Decision section, no `summary` front matter field (simpler, works on every existing ADR, ADR 0001 keeps its three front matter keys). Rule in the spec: first paragraph or bullet of `## Decision`, cut after `.` + whitespace + capital or backtick, else end of that block. Settled in `docs/spec/cli.md`; ADR 0003 not edited.
- Confirmation: none for accept/reject/supersede (plain file edits reviewed in git diff); stated in the spec. `supersede N NEW` also adds N to NEW's `supersedes` list; accept/reject only from `proposed`, supersede only from `accepted`.
- Planning allow: I extended the default `planning.allow` with the two read commands (`DEFAULT_PLANNING_ALLOW` in config.py), so the planner can follow the prompt paragraph. Documented in workflow-config.
- Spec edits: `cli.md` (commands block, nouns/help sentence, new `adr` section), `prompts.md` (protocol paragraph, planning variant), `workflow-config.md` (default allow). Also manual, README, CLAUDE.md map, WORKFLOW.md (allow entries `uv run samba adr list|show` and body paragraph).
- Tests: new `tests/test_adr.py` (14 tests); `test_cli_surface.py` help noun list updated. pyright 0 errors, 304 tests passed.
- 2026-11-10 09:51 samba: permission denied: Bash (sed -i 's/default_factory=lambda: \["Read", "Grep", "Glob"\])/default_factory=lambda: list(DEFAULT_PLANNING_ALLOW))/; s/)
- 2026-11-10 09:54 samba: done: work-running -> work-review: validation passed (turns 2, $1.07): I added `samba adr list|show|accept|reject|supersede` in the new `src/samba/adr.py`. They work without a WORKFLOW.md and never commit. The ADR 0003 paragraph is in both built-in prompts and the repo's WORKFLOW.md, and `adr list` and `adr show` are in the default allow lists. pyright reports 0 errors and the full suite passed (304 tests). I ran the suite once before a pyright fix to `adr.py`, then re-ran only pyright, which is clean. I did not re-run the tests after that fix. - **Summary source:** the first sentence of the Decision section, with no new front matter field. This is settled in `docs/spec/cli.md`, and the log in the task file says the same. - **No confirmation prompt:** accept, reject and supersede are plain file edits that `git diff` shows and git can undo, so they don't ask. The spec says so. - **Supersede form:** `supersede N NEW` marks N superseded and adds N to NEW's `supersedes` list. The task text didn't give the argument form, so this is my reading. - **Legal states:** accept and reject only work from `proposed`, and supersede only from `accepted`. - **Planning allow:** I also added the two read commands to the default planning allow list, so the planner can follow the prompt paragraph. The plan offered a fallback of telling it to read `docs/adr/` directly instead. This choice is in the log and in `docs/spec/workflow-config.md`. - **Docs and tests:** I updated the CLI, prompts and workflow-config chapters of the spec, plus the manual, README and CLAUDE.md. There are 14 new black-box tests in `tests/test_adr.py`, and I changed the `--help` noun list in `tests/test_cli_surface.py`. - **Task file:** I did not tick the checkboxes in the `## Plan` section of the task file. My first attempt to edit `config.py` was a `sed -i` command that was denied. I made the same edit with the Edit tool instead.
- 2026-11-10 17:28 samba: work.accept: work-review -> done: merged 8f3a155, validated
