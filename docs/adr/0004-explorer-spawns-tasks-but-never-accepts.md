---
status: accepted
date: 2026-11-08
supersedes: []
---

# 0004: The explorer can spawn tasks but never accept anything

## Context

During an exploration the agent may want background work: research that should survive the chat, or
implementation tasks once an ADR is accepted. At the same time, every human gate in Samba (plan
accept, work accept, answering questions, discarding) exists so that agents propose and humans decide.

## Decision

- The explore session is allowed `samba task new`, `samba task list|show`, `samba question list|show`
  and `samba adr list|show`.
- It is not allowed `plan accept|reject`, `work accept|reject`, `task discard|stop|retry`,
  `question answer` or `adr accept|reject|supersede`. `samba explore` passes this allow list to
  `claude` explicitly, so it does not depend on the user's global settings.
- A spawned task starts in `plan-todo` and still waits at plan review, so the worst case is a few
  wasted planning runs.
- Research results are scaffolding. The explorer reads a finished research task through
  `samba task show` and nothing is merged. Findings worth keeping go into an ADR.
- The explorer tells the human what it spawned and why.

## Consequences

- Spend is bounded by existing settings (`max_concurrent`, `max_cost_usd_per_task`) plus the human
  gates.
- Research findings live in `.samba/`, which is not versioned. This is intended: the ADR is the
  durable record.
- Retrieving a research task's result relies on `task show` exposing its summary and log. If that
  proves too thin, a future ADR can add a research output convention.
