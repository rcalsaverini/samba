# Architecture principles

This chapter states the principles behind Samba's layering, in the vocabulary of domain-driven
design and hexagonal architecture, so that a design question ("may this depend on that", "where
does this go") has an answer before it becomes a decision. The ADRs record the decisions that
apply these principles; the `architecture` chapter says where each piece lives and how the rules
are enforced. This chapter is normative: the code follows it, and a change that cannot follow a
principle is a decision for an ADR, not an exception.

## Vocabulary

Samba uses these words with these meanings.

- **Domain.** The rules and data of the problem: a task and its lifecycle, the states and the
  transition table, questions, the dependencies between tasks, the retry and budget policy, and
  the decision of what to do after an agent turn. Pure: no I/O, no clock, no ids, no log. The
  domain is data and functions over data.
- **Aggregate.** A record the domain loads, changes and saves as a whole, with the invariants that
  must hold at every save. `Task` was the first aggregate, and not necessarily the last (DDD: aggregate root).
- **Value.** An immutable fact with no identity of its own: an id, a state, an instant, a question
  record, an agent report, a validation result. Values are compared by content and passed freely.
- **Use case.** One operation a person or the orchestrator can perform, named for what the person
  does: change a task's state, answer a question, accept work, run a tick, run a turn. A use case
  orchestrates the domain and talks to the outside through ports (DDD: application service;
  hexagonal: the inside, together with the domain).
- **Port.** An interface the inside declares so that the outside can be plugged in, written over
  the inside's own types and holding no implementation. A driven port is something the inside
  needs: the task store, the clock, the agent, git, validation, the journal, the terminal, the
  lock. A driving port is how the outside calls in: the use cases themselves are that contract.
- **Adapter.** An implementation of a port for one technology (markdown folders, the system clock,
  the `claude` command, git worktrees, a shell command, a file lock, a log file, a terminal), or a
  driving adapter that turns an outside event into a use case call (the command line driven by a
  person, the orchestrator loop driven by time).
- **Composition root.** The one place that builds adapters and hands them to use cases.
- **Inside and outside.** The inside is the domain and the use cases. Everything else, including
  the entry points, the adapters, the operating system and the person, is outside. Ports are the
  edge of the inside.

## Design approach: strategic design first, then tactical

Domain-driven design has two halves, and the order matters. Strategic design decides what the
problem is, where its boundaries are and what the words mean. Tactical design builds the model
inside one boundary. A design that starts from states, tables, folders or classes skips the first
half and usually has to be redone. Anyone adding a concept to Samba, person or agent, works in this
order: the language and the boundary, then the model, then the ports the model needs, then the
adapters. The principles below are what the result must satisfy.

### Strategic design: the words, the boundaries, the relationships

- **Ubiquitous language.** One vocabulary shared by the person, the spec, the ADRs, the prompts, the
  tests and the code. A word has one meaning in a context. When two meanings appear, one is renamed,
  and the code follows the language: a concept gets a name before it gets a type. The project
  glossary holds the definitions. A term that is not in it is agreed with the person, who is the
  domain expert, and added.
- **Subdomains.** Not every part of the problem deserves the same care. The core is what makes Samba
  what it is, how agent work is organized, reviewed and approved under human control, and it gets
  the richest model. Supporting parts are needed but not distinctive. Generic parts (git, the shell,
  files, a lock, a terminal, a log) are solved problems: keep them thin, behind an adapter, and keep
  their words out of the model.
- **Bounded context.** A boundary inside which a model is consistent and each term has one meaning.
  The same word may mean different things in two contexts. Two meanings inside one context is the
  defect. Contexts relate in stated ways: one is upstream of the other, and the downstream either
  conforms to the upstream's model or protects itself with an anti-corruption layer, an adapter that
  translates a foreign model into ours (the `claude` runner, which turns a stream of JSON into an
  agent report, is one). What crosses a boundary is a published language, here the use-case results
  and the scenario data. A context map draws these relationships. Samba's contexts and their map are
  decided in ADRs, not assumed here.
- **Discovery.** The model is found in conversation with the domain expert, not derived from
  storage. A good tool is event storming: list the facts that happen in the problem, in the past
  tense and in the expert's words (an item was promoted, a plan was approved), then find the rules
  that react to them and the things they happen to. Aggregates, states and policies come out of
  that, not before it.

### Tactical design: the building blocks inside one context

- **Entity and value.** An entity has an identity that persists through change (a task). A value has
  none and is compared by content (a state, an instant, a question record). Prefer a value when
  identity is not needed.
- **Aggregate.** Entities and values changed together under one root, with invariants that hold at
  every save. Keep aggregates small. Refer to another aggregate by its id, never by holding it. One
  operation changes one aggregate: a rule that spans several is a use case, or a value derived from
  them (principle 5).
- **Domain service and policy.** A rule that belongs to no single entity is a pure function: the
  decision after an agent turn, dependency evaluation, the retry policy. A policy is a rule of the
  form "whenever this happens, do that".
- **Domain event.** A fact in the past tense, named in the language. Samba uses events to model and
  to name transitions. It has no event bus (ADR 0011), so a reaction is either derived from state or
  done by a use case.
- **Repository and factory.** A repository is the port through which a use case loads and saves an
  aggregate (the task store). A factory is where creation with invariants lives.
- **Application service** is what Samba calls a use case.

Heuristics that keep a model good:

- Put behavior next to the data it protects. A use case full of rules about one record means the
  rules belong to the domain (the anemic model smell).
- Make illegal states unrepresentable: closed sets of values, types over strings, a transition
  table over flags.
- Name things for what they mean in the problem, not for how they are stored or run.
- The model serves the use cases, not the screens or the files.

## Principles

### 1. Dependencies point inward

Entry points depend on the composition root, the use cases and the domain. Adapters depend on the
ports and the domain. Use cases depend on the domain and on the ports they declare. The domain
depends on the standard library and on itself. Nothing inside imports the composition root or an
entry point, and nothing but the composition root imports an adapter.

Why: the rules of Samba can then be tested without a clock, a disk, a process or a network, and
rewritten without untangling them from storage and processes (ADR 0010, ADR 0011).

### 2. The inside declares the ports, the outside implements them

A port is created by the code that will receive the adapter and call it, in that code's own
vocabulary. The adapter adapts to the port, never the reverse: a use case receives an agent report
in Samba's terms, not the agent's raw output, and the store port speaks of tasks and states, not
of folders and files.

Importing a port is importing a type the inside declared, and breaks no rule. Importing an adapter
from the inside is the breach. The distinction that matters is port against adapter, not interface
against class.

A port lives with the layer that declares it. Because of principle 3 the domain declares none, so
every port belongs to the use-case layer (ADR 0018).

Ports are added only where they buy a fast test or a seam for the rewrite. There is no dependency
injection framework, no event bus and no interface for its own sake (ADR 0011).

### 3. The domain takes values, never capabilities

A domain function receives the results of I/O as arguments and performs none, not even through a
port it could declare. Time arrives as a value built by the use case once per recorded step (each
transition, each answer, each log entry, each question round), so every timestamp of one step is
the same instant (ADR 0017). A step, not a whole use-case run: a turn loop that runs for an hour
builds a new instant for each entry it records.

When a rule seems to need a capability during its computation, the boundary between inside and
outside is drawn in the wrong place. Redraw it, trying these in order:

1. Pass the values: a fixed number of them, known before the rule runs.
2. Pass a seed, or a pure generator built from one (a seeded PRNG, a quasi-random sequence), and
   keep the rule deterministic. The test is simple: if pulling from it performs I/O, it is a
   capability and the rule does not take it.
3. Make the rule a step function or a generator and let the use case run the loop against the
   port, as the decision after an agent turn and the turn loop already do for the agent.

If none fits, the operation is not a domain rule but a use case, and only its pure part stays in
the domain.

Why: a function of its arguments is deterministic, replayable from a record of its inputs and
testable with literals, and an aggregate method that performs no I/O cannot fail halfway through
and leave the aggregate half-changed (principle 5).

### 4. The domain owns the vocabulary, the use cases own the needs

The types every layer speaks in (the task, its id, its state, an instant, a question, an agent
request and report, a validation result, a launch) are domain values. Ports are written over them
but declared by the use cases. Being written in the domain's vocabulary is not the same as being
declared by the domain.

The domain knows no folder, path, sidecar, process, branch, worktree or agent output format. Those
words belong to adapters, and the architecture test rejects them inside (ADR 0005, ADR 0006).

### 5. An aggregate is a consistency boundary

An aggregate (today the task) is loaded, changed and saved as a whole, and its invariants hold at every save. A state
change goes through the one path that applies a transition row and saves. Concurrency between a
running worker and a command is the store's business, resolved by merging a stale save field by
field (architecture, The Tasks port and stale saves); the domain carries no version field and no
retry loop.

### 6. Every operation is one use case, and interfaces are thin

Each thing a person or the orchestrator can do is one use case that takes plain values and returns
one of a closed set of results. Input rules, such as resolving a task id from a prefix, live in the
use case. An entry point parses its own input, makes one call and renders the result; it holds no
rule, and no entry point calls another (ADR 0013, ADR 0014). The use cases are the contract a
second interface, such as a web page or an MCP server, would call.

Entry points are driving adapters: the command line is driven by a person, the orchestrator loop
by the clock. The orchestrator is named parts with one reason to change each, plus a loop that
holds no rule (ADR 0015).

### 7. Adapters translate and hold no rule

An adapter turns a port's calls into one technology and the technology's answers back into the
port's types. It decides how, never whether: the markdown store decides how to merge a stale save
and how to detect a hand move, never whether a move is legal; the agent runner builds a command
line and parses a stream, never what an outcome means.

Every port has an in-memory fake for the tests of the inside. A fake with behavior of its own is
kept honest by a port contract: one set of cases run against the fake and the real adapter
(ADR 0016).

### 8. One composition root, and nothing inside knows what it was given

Only the composition root builds adapters and wires them into use cases. Constructors take their
ports, with no defaults. A use case cannot tell a fake from the real thing, which is what makes a
component test mean something.

### 9. The behavior contract lives outside the code

Samba is written to be rewritten (ADR 0010). The contract of a rewrite is the spec, the scenario
data that states the rules of the core, and the small end-to-end suite that drives the real command
(ADR 0012, ADR 0016). Unit, component and integration tests protect this implementation and go
with it. A new behavior gets a test at the lowest level that can show it.

### 10. One word, one meaning

Each term of the domain is defined once, in the project glossary, and means the same in the spec,
the ADRs, the prompts, the tests and the names in the code. A word with two meanings, or two words
for one meaning, is a defect, and it is fixed by renaming in the change that finds it. A new
concept is named with the person before it is typed in code or written in an ADR.

Why: people and agents read the same words, and a vocabulary that drifts produces models that
drift.

## Where a piece goes

Ask these in order and stop at the first yes.

| Question | Where it goes |
|---|---|
| Is it a fact or a rule about tasks that needs nothing from outside? | The domain: a value, a method of the aggregate, or a pure function. |
| Does it need something from outside (the store, time, the agent, git, the person) to do its job? | A use case, which declares the port it needs and hands the domain the values it fetched. |
| Does it speak to one technology (files, processes, git, a terminal, a log)? | An adapter of the port that names the need. |
| Does it parse what a person or a timer gives, or render what a use case returns? | An entry point. |
| Does it need to know which adapter is in use? | The composition root, and nowhere else. |

A rule found in an adapter or an entry point moves inward. A technology word found inside moves
outward. A capability found in the domain is redrawn with the list in principle 3.

## How the principles are enforced

- The architecture test reads the sources and checks the import rules of principles 1, 2 and 4,
  the module lists of each layer, the absence of storage and process vocabulary inside, and that
  only the composition root builds adapters (architecture, The architecture test).
- Pyright in strict mode checks, wherever an adapter or a fake is handed to a use case, that it
  satisfies the port, and that no `Any` reaches a public signature.
- Port contracts keep the fakes honest (principle 7); scenario files and the end-to-end suite keep
  the behavior contract (principle 9).
- A change that cannot follow a principle is a decision for an ADR, not an exception.

## Decisions that apply them

| Principle | ADRs |
|---|---|
| 1. Dependencies point inward | 0011 |
| 2. The inside declares the ports | 0011, 0018 |
| 3. Values, never capabilities | 0017 |
| 4. Vocabulary and needs | 0005, 0006, 0011 |
| 5. The aggregate | 0005 |
| 6. One use case per operation | 0013, 0014, 0015 |
| 7. Adapters hold no rule | 0006, 0007, 0008, 0016 |
| 8. One composition root | 0011 |
| 9. The contract outside the code | 0009, 0010, 0012, 0016 |
| 10. One word, one meaning | none yet (this chapter) |
