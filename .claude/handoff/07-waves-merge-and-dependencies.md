# 07: Waves, merge levels and dependencies

Status: DEFERRED. The owner said the design is getting too involved and asked to stall it. Only the
diagrams (`docs/diagrams/refinement.mmd`, `implementation.mmd`) hold the target design. Nothing is
decided as an ADR. Do not start building this until the cheap parts (file 02, 04) have run.

## The problem

Dependencies (`depends_on`) gate work until a human accepts each task, so a chain of tasks stalls at
every hop. The owner asked: "can I feed enough work so that it is continuously working and not waiting
for me?"

## Ideas discussed (not decided)

- Wave: a set of topologically sorted tasks (a topological layer), possibly grouping consecutive
  layers into one review checkpoint. The Designer chooses the grouping and records the reason on the
  Epic. The Reviewer checks the grouping and the dependency edges (a wrong `depends_on` gives wrong
  waves).
- Risk first: the Refiner (the Designer's second job) orders layers so the riskiest or most foundational
  assumption lands in wave 1, so the first checkpoint validates the TEP while rejecting is cheap.
- Rolling wave: only the next wave is written in full; later waves are outlines, detailed once their
  dependencies are merged into the epic branch, so they see the code that landed.
- Two merge levels, like a stack of PRs. Task into the epic branch: gated by validation and the Reviewer,
  no owner. Epic branch into main: gated by the owner, once every wave in the stack is approved.
  Approving a wave is only a sign-off; nothing reaches main until the whole stack is approved. A bugfix
  skips the epic branch.
- Asynchronous checkpoints: the owner reviews a wave while the next one builds. The system stays at most
  one wave ahead. An Epic may opt into "wait for approval" for risky work.
- Rejecting a wave means the later waves built on it are reworked (like rebasing a PR stack).

## Dependency options (ranked by the earlier discussion)

1. Plan ahead, work later: planning proceeds against the dependency's approved plan; only work waits; on
   merge, a cheap Reviewer revalidation of the dependent plan.
2. Gate on "approved", not "merged": defer. Needs known rejection rates first.
3. Conflict detection from the plan's file list: tasks with disjoint file sets run concurrently. Needs
   `max_concurrent` above 1 to matter. Keep `depends_on` for real logical dependencies only.
4. Cheaper human review of goldfish-approved work. Do not auto-merge yet.

## Metric the owner cares about

His idle time, not machine idle time. Occasional rework is cheap by comparison.

## Measure before deciding

Nobody has measured how much of the current slowness is dependency stalls versus review latency. The
task logs and sidecar timestamps can show how long tasks sat in `plan-review` and `work-review` with the
queue empty. Pull those numbers before committing to any option.

## Open with the owner

- Whether approving a wave is a sign-off only (decided: yes, sign-off only, merge at the end).
- Whether a Task with no Epic (a bugfix) is reviewed alone against main (decided: yes).
- The wave grouping rule: who decides, and whether the Reviewer may refuse a grouping.
