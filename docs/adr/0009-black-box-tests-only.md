---
status: superseded
date: 2026-11-07
supersedes: []
---

# 0009: The main test suite is black-box and never imports Samba

Recorded retroactively on 2026-11-08.

## Context

Samba is expected to be rewritten later, probably in Rust (ADR 0010). Tests that call Python
functions are thrown away with the Python. We also want agents to change internals freely while
the tests keep saying whether behavior is preserved.

## Decision

- `tests/test_blackbox.py` and the other behavior tests run the `samba` command as a subprocess and
  assert only on files and on the calls a scripted fake `claude` recorded. They never import the
  `samba` package. `tests/test_manual.py` and `tests/test_spec_docs.py` follow the same rule: they
  read files and run `--help`.
- The `SAMBA_CMD` environment variable replaces the command under test, so the same suite runs
  against another implementation unchanged.
- `tests/fake_claude.py` is the fake, written with the standard library only.
- New behavior gets a black-box test first.

## Consequences

- The suite is the portable contract for the rewrite, together with the spec.
- Tests are slower (the suite takes a couple of minutes because each one starts processes), and
  failures point at behavior, not at a function.
- Timing-dependent tests need care, because the processes under test are real. The flaky transition
  test is an example.
- Internal helpers get no unit tests of their own unless a behavior test exposes them. Pyright in
  strict mode covers type errors.
