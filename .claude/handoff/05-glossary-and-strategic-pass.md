# 05: Glossary and strategic pass for Samba (plan step 2)

Status: NOT STARTED. Needs the owner. Blocks principle 10 ("One word, one meaning") from being
enforced, since that principle points at a glossary that does not exist.

## Why

We built many words ad hoc. The owner asked for a proper strategic and tactical DDD pass "not ad hoc".
Several words collide or have drifted. Findings so far (to confirm with the owner, not to decide alone):

- Plan: a stage of a task today, the text inside a task file, the `plan-review` state, and also the TEP.
- Task: request + plan + execution record today. In the new model it is one small slice.
- Review: a `plan-review` state, the Reviewer role, the owner's review of a wave, the owner's final
  review.
- Approve vs accept: the ADR commands say `accept` (human only); the Reviewer "approves"; the owner
  "approves" a wave.
- Wave: a rolling-detail window, a topological layer, and a review checkpoint. Three ideas, one word.
- Spec: `docs/spec/` is behavior as it is; "an Epic's spec" was also used.
- Backlog: the `backlog` chapter (unbuilt ideas for Samba) vs the new backlog artifact (a unit of
  intent). Different things, same word.
- Phase / stage / state: diagram phases, task stages (plan/work), task states.
- Names the assistant introduced and the owner adopted without much debate: Designer (replacing
  "Technical Designer" and "Refiner"), Implementer, pre-review, checkpoint, outline, amend, advisory
  mode. The owner's own: Epic, TEP, Task, Explorer, Reviewer, Owner, wave.

## Strategic questions to ask the owner (not yet asked properly)

- What is the core domain? The working answer: "how agent work is organized, reviewed and approved
  under human control". Confirm or replace.
- The bounded contexts seen so far: work management (backlog, Epics, tasks, dependencies); agent
  execution (turns, sessions, budgets, roles); delivery (workspaces, merge, validation); decisions and
  spec (the ADR lifecycle is NOT the task lifecycle). Confirm, merge or split. The adapters already act
  as anti-corruption layers (the `claude` runner turns stream JSON into an `AgentReport`).
- Which words are the owner's and must not change, and which are assistant inventions that may go.

## Output

`docs/glossary.md` in the repo (project instance, ADR 0024 kind), one meaning per word, with the
owner's approval marked. Then revise ADRs 0021 to 0023 and the diagrams against it.

## Method

Short event storming with the owner as domain expert: list the facts that happen, in the past tense and
in his words; find the rules that react and the things they happen to; aggregates and states come out of
that, not before it. Proportionality: Samba is small. A short session plus the glossary is enough; no
full DDD ceremony.
