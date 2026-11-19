# 02: The artifact model (backlog, ADR, spec, Epic, TEP, task, bugfix)

Status: proposed, on main, in `docs/adr/`:
- 0021 `work-is-organized-as-backlog-epic-tep-task.md`: the artifacts and the chain between them.
- 0023 `each-artifact-kind-is-an-aggregate-with-its-own-state-machine.md`: per-kind states and derived
  cross-artifact rules.

## Vocabulary (agreed with the owner, with reservations)

- Backlog item: an intent, one or two lines: what, why, where it came from. States: open, promoted,
  dropped. No plan, no worktree. Sources: exploration, Reviewer nits, ADR candidates, the owner.
- ADR: a rule about how the software is built. It constrains designs and plans. It is NOT a goal and
  NOT a spec and NOT an RFC. The owner was firm on this: "they are the rules".
- Spec: what the software does today (`docs/spec/`).
- Epic: a goal larger than one task. The owner approves it. Says what, why, what is out of scope, and
  which paths were rejected. The owner suggested Epic over "Goal" (which collides with the deferred
  long-term goals).
- TEP (technical execution plan): how to reach an Epic. Fixes interfaces, order and invariants across
  tasks. A reference for tasks, NOT the body of a task. Chosen over "each task has a TEP" because
  huge TEPs were the con the owner accepted; the Implementer reads only the TEP section a task points
  at. The name "TEP" is weak; open.
- Task: one unit with one purpose, small, self-contained, independent. One PR of 1 to 5 commits and a
  small diff. Main stays green after it. It carries its own concrete steps and file list.
- Bugfix: a task created straight from a backlog item, with no Epic and no TEP. The fast path for
  one-line fixes.

Words the owner has not yet fixed: TEP vs something else; whether an Epic is one file or a folder
with its TEP and tasks inside; what "wave" means (file 07).

## Aggregates (ADR 0023)

- Each artifact kind is an aggregate with its own id, states and transition table, as plain data like
  today's table. The owner objected to "Task is the one aggregate" and it was corrected: `Task` "was
  the first aggregate, and not necessarily the last". Some future aggregate may have no states at all.
- A rule that spans artifacts is either a use case that changes at most one aggregate, or it is
  DERIVED on each tick as a pure function of values (for example: a task is held while its TEP is in
  `amend`; a wave is in review when its tasks are merged; an Epic is done when its waves are approved).
  Derived results are never written into the other artifacts. This replaces the earlier fan-out write
  ("set every task of the TEP to blocked"), which could leave half-written state after a crash.
- Store ports: one repository shape per kind (`get`, `list`, `create`, `save`), and a separate port
  for what is not repository work (hand-move observation, readiness, file location). ADR 0018 already
  says the current `Tasks` port mixes these. That split is being done (the owner said so), so do not
  redo it without checking the current `app/ports.py`.
- Open: one generic `Machine` parameterized by a kind's table, or one `Machine` per kind. Decide in the
  task that adds the second kind.
- Adoption order: the backlog item first (no worktree, no agent, few states). It is the cheapest test
  of the generalization.

## Open with the owner

- Whether "approval" is a first-class concept (who approved what, with what authority) or just a
  policy over the approver of each kind. Raised, not answered.
- Samba today mixes intent, plan, execution record, conversation and delivery details in one task file.
  Splitting those is implied by the model; the owner has not said how far to go.

## Not on main

Nothing here is implemented. The current code has one aggregate (`Task`), one table
(`src/samba/domain/transitions.py`) and `Tick` hardcodes `plan-todo`/`work-todo`. Those are the places
the generalization will touch.
