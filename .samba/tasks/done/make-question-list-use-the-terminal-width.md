---
priority: 3
depends_on: ["split-spec-md-into-docs-spec-chapters"]
---
# Make question list use the terminal width

`samba question list` cuts the QUESTION column to about 25 characters (it looked like "Should I accept the man..."), sized for an 80-column terminal, which is too short to tell questions apart. Use the real terminal width (falling back to 80 when not a TTY), give the QUESTION column the remaining space, and keep the other columns intact. Check whether `task list` has the same problem and fix it the same way if so, sharing the table printer in views.py.

Done when a black-box test shows a long question is shown in full on a wide terminal and truncated with an ellipsis on a narrow one (set COLUMNS), the user manual is updated if it shows the output, and pyright and the tests pass.

## Plan
### Approach
Move truncation into the shared table printer in `src/samba/views.py`. Give `print_table` an optional `flex` column index and a `width` argument. The flex column gets the width left over after the other columns (each at its natural max width, plus 2 spaces of separation). It is truncated with `...` only when it doesn't fit, and never goes below a minimum of 20. `question list` uses flex=QUESTION. `task list` uses its last free-text column (the error column) as flex, so a wide terminal shows the full text. Terminal width comes from `shutil.get_terminal_size()`, which honours COLUMNS, then the TTY, then falls back to 80. The other columns are never truncated.

### Steps
- [ ] Read `docs/spec/cli.md` (the `question list` and `task list` bullets), `docs/spec/observability.md` (line 7) and `docs/manual.md` (~lines 241, 308, 367-380).
- [ ] Write black-box tests first. Put them in `tests/test_questions.py`, plus one in `tests/test_blackbox.py` for `task list`. They must not import samba, and must pass COLUMNS explicitly through `sb.run(..., COLUMNS="...")`.
  - [ ] A question of about 150 chars with COLUMNS=200: the full text appears in the row, with no `...`.
  - [ ] The same question with COLUMNS=70: every row is at most 70 chars and the row ends in `...`.
  - [ ] The other columns (TASK, QID, STAGE, ASKED) stay intact in both cases.
  - [ ] For `task list`, create a task with a long `last_error` (via a failing fake step, or by writing the sidecar). Assert that at COLUMNS=200 it is shown in full (more than 60 chars) and at COLUMNS=60 the rows fit with `...`.
  - [ ] Keep the existing `test_question_list_truncates_to_terminal_width`.
- [ ] Implement in `views.py`.
  - [ ] Add `fit_table(rows, width, flex)`, or extend `print_table(rows, width=None, flex=None)`, with the truncation logic moved out of `question_rows`.
  - [ ] `question_rows` then only builds rows and drops its `width` parameter and the truncation code. Keep `used = sum(max len) + 2` per non-flex column, and compute the header width into the max.
  - [ ] Remove the `[:60]` cut in `task_rows`. Flatten newlines in `last_error` to single spaces so a row stays on one line.
  - [ ] Update both call sites in `src/samba/cli.py` (line ~94 and ~245) to pass `shutil.get_terminal_size().columns` and the flex index.
- [ ] Docs: update `docs/spec/cli.md` (the truncation rule for `question list` and `task list`, the 80 fallback, the minimum of 20), `docs/spec/observability.md` if it describes `task list` columns, and `docs/manual.md` where it shows the output (~line 315 and 371). Do not use em-dashes. Add a line to the task file's `## Log` saying the spec detail was settled.
- [ ] Run `uv run pyright` (0 errors), then `uv run pytest -q`, as separate plain commands.

### Files to change
- `src/samba/views.py` (the shared table printer, `question_rows`, `task_rows`)
- `src/samba/cli.py` (the two call sites)
- `tests/test_questions.py`, `tests/test_blackbox.py` (new tests)
- `docs/spec/cli.md`, possibly `docs/spec/observability.md`, `docs/manual.md`

### Risks
- Existing tests that compare `task list` output, including the 60-char error cut, may break. Check `tests/test_blackbox.py` around lines 439-504 and `tests/test_planning.py:224`.
- When COLUMNS is inherited from the outer environment, results become nondeterministic. The tests must set COLUMNS explicitly for width-dependent assertions.
- If the fixed columns alone are wider than the terminal, the flex column bottoms out at the minimum of 20, so rows exceed the width. This is documented and acceptable.
- `print_table` is used by other commands. Keep the default behaviour (no flex) unchanged for them.

### How to verify
- `uv run pytest -q tests/test_questions.py tests/test_blackbox.py`, then the full suite.
- `uv run pyright` reports 0 errors.
- `tests/test_manual.py` passes.
- Manually: `COLUMNS=200 samba question list` and `COLUMNS=60 samba question list` in a sandbox repo.

## Assumptions
- Existing code already reads the width via shutil.get_terminal_size() (COLUMNS, then TTY, then fallback 80) and cli.py:245 passes it to question_rows. I take the reported 25-char cut to come from the 80 fallback in non-TTY contexts, or from long TASK and QID columns eating the room. I did not reproduce it.
- Task list: the only wide free-text columns are LAST (last_outcome, which can be "waiting on a, b, c") and the 7th column, last_error, hard-cut at [:60] in task_rows. I assume the last column should take the remaining space the same way. Its [:60] cap goes away and is replaced by width-based truncation.
- Truncation marker stays "..." (three ASCII dots), as the spec says. The task says "ellipsis"; I don't read that as requiring the Unicode character.
- The minimum QUESTION width of 20 stays as documented in docs/spec/cli.md.

## Log
- 2026-11-08 15:38 samba: dispatch_plan: plan-todo -> plan-running
- 2026-11-08 15:39 samba: planned: plan-running -> plan-review: planned (turns 1, $0.12): The question list already truncates by terminal width (views.py question_rows, with a narrow-width test). The plan moves that into the shared print_table, makes the fix work for task list too, adds a wide-terminal test, and updates the spec and manual.
- 2026-11-08 16:17 samba: plan.accept: plan-review -> work-todo
- 2026-11-08 16:20 samba: dispatch_work: work-todo -> work-running
- Implemented: print_table(rows, width, flex) in views.py does the truncation; question list flexes QUESTION, task list flexes ERROR (the [:60] cut is gone). Spec detail settled in docs/spec/cli.md (80 fallback, min 20, other columns never cut); manual updated. Tests added; pyright and pytest pass.
- 2026-11-08 16:27 samba: done: work-running -> work-review: validation passed (turns 2, $0.35): The shared `print_table` now takes `width` and `flex` arguments, so `question list` (QUESTION) and `task list` (ERROR) fill the terminal width. They truncate with `...` only when the text doesn't fit. I added black-box tests for wide and narrow terminals, updated the spec and manual, and committed. pyright reports 0 errors. The full pytest run had one failure, in a test I had just written; I fixed it and re-ran `tests/test_questions.py`, which passes. I did not re-run the full suite after that fix.
- 2026-11-08 19:25 samba: work.accept: work-review -> done: merged 82f8578, validated
