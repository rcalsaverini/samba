# Design principles: domain-driven design and hexagonal architecture

This page states the design rules this project follows. It is short on purpose: a rule earns its
place by changing a decision. Work inside the existing model needs none of the rituals below.

## Design order

Decide the language and the boundaries first, then the model, then the ports the model needs, then the
adapters. A design that starts from tables, folders, classes or database schemas skips the first two
steps and usually has to be redone.

## Strategic design: words and boundaries

- **Ubiquitous language.** One vocabulary shared by the people, the documents, the tests and the code.
  A word has one meaning inside a context. When two meanings collide, rename one and let the code follow.
  A concept gets a name before it gets a type.
- **Glossary.** Project terms are defined once, in the glossary. A term not in the glossary is agreed
  with the domain expert, then added.
- **Subdomains.** The core is what makes the product distinctive and gets the richest model. Supporting
  parts are needed but not distinctive. Generic parts (files, networks, logging, a clock) are solved
  problems: keep them thin, behind an adapter, and keep their words out of the model.
- **Bounded context.** A boundary inside which a model is consistent and each term has one meaning. The
  same word may mean different things in two contexts. Two meanings inside one context is the defect.
- **Context map.** Contexts relate in stated ways. One is upstream of another. A downstream context either
  conforms to the upstream model or protects itself with an anti-corruption layer: an adapter that
  translates a foreign model into its own. The contexts and their relations are written down, not assumed.
- **Discovery.** Find the model in conversation with the domain expert, not from the storage layout.
  Event storming works well: list the facts that happen, in the past tense and in the expert's words,
  then the rules that react to them. Aggregates and states come from that, not before it.

## Tactical design: building blocks inside one context

- **Entity and value.** An entity has an identity that persists through change. A value has none and is
  compared by content. Prefer a value when identity is not needed.
- **Aggregate.** Entities and values changed together under one root, with invariants that hold at every
  save. Keep aggregates small. Refer to another aggregate by its identifier, not by holding it. One
  operation changes one aggregate. A rule spanning several is a use case, or a value derived from them.
- **Domain service and policy.** A rule that belongs to no single entity is a pure function. A policy is
  a rule of the form "whenever this happens, do that".
- **Domain event.** A fact in the past tense, named in the language. It names transitions; it is not a
  message bus.
- **Repository and factory.** A repository is the port through which a use case loads and saves an
  aggregate. A factory is where creation with invariants lives.
- **Application service.** One operation a person or a process can perform. It loads, changes and saves
  through ports and returns a result.

## Architecture: layers and ports

1. **Dependencies point inward.** Entry points depend on the composition root, the use cases and the
   domain. Adapters depend on ports and the domain. Use cases depend on the domain and on the ports they
   declare. The domain depends on nothing outside itself. Only the composition root builds adapters.
2. **The inside declares the ports; the outside implements them.** A port is an interface written over
   the inside's own types, declared by the code that calls it. The adapter adapts to the port, never the
   reverse. Ports are added only where they buy a fast test or a seam for a replacement. No dependency
   injection framework, no event bus, no interface for its own sake.
3. **The domain takes values, never capabilities.** A domain function receives the results of I/O as
   arguments and performs none. Time arrives as a value built once per recorded step. When a rule seems
   to need a capability during its computation, redraw the boundary: pass the values it needs, or a
   seed for a deterministic generator, or make the rule a step function that the use case drives.
4. **Adapters hold no rule.** An adapter decides how something is done, never whether it is allowed. A
   rule found in an adapter or an entry point moves inward.
5. **Each port has a fake.** A fake with behavior of its own is kept honest by one set of contract cases
   that run against both the fake and the real adapter.
6. **Every operation is one use case, and interfaces are thin.** Each operation takes plain values and
   returns one of a closed set of results. An entry point parses its input, makes one call and renders
   the result. It holds no rule.

## Working rules

- **One word, one meaning.** A word with two meanings, or two words for one meaning, is a defect. Fix it
  by renaming in the change that finds it.
- **Triggers, not size, decide the rituals.** Glossary entries, event storming and context maps happen
  when a concept appears that is not in the glossary, when a word turns out to have two meanings, or when
  the work crosses an existing boundary or would create a new one. New contexts and glossary terms need
  the domain expert; an agent must not invent them.
- **The smallest model that expresses the rule in front of you.** Add a value object, an aggregate or a
  policy when a requirement fails without it, not because the pattern exists.
- **Behavior sits with the data it protects.** A use case full of rules about one record means the rules
  belong in the aggregate or a domain function.
- **Illegal states are hard to write.** Use closed sets, types over strings, and transition tables over
  flags.
- **Name things for what they mean in the problem,** not for how they are stored or run.

## Severity

Only violations of a machine-checkable rule, or of an explicit decision record, block a change. Smells
(an anemic model, a missing value object, a name that could be clearer) are advice. Record them; do not
block on them.

## Enforcement

The project writes its own architecture check: a test that reads the source and fails on a forbidden
import, such as a domain module importing an adapter or a database library. The check is language-specific,
so this page does not ship one. Its shape is: list the layers, list what each may import, and fail on
anything else. Until the project has such a check, reviewers apply these rules by reading.

## Proportion

These rules exist to keep the model honest and the code changeable. If applying one adds ceremony that
no requirement asks for, that is a sign to apply less of it, not more.
