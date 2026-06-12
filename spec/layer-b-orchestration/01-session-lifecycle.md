# Session Lifecycle (one orchestration shape)

**Layer B — ephemeral.** The session is *one way* to chunk an agent's work,
the way the demonstration community happens to run. "Session" is an
**orchestration primitive, not a scientific one**: Layer A never treats a
session as a unit of meaning (see
[layer-a-scientific/04-self-knowledge.md](../layer-a-scientific/04-self-knowledge.md)).
A different orchestration — a resident agent that never "ends a session" —
satisfies every Layer A standard without this shape at all.

## The three phases

A scheduled session runs **initialize → work → close**.

### Phase 1 — Initialize

Establish connectivity to Symposium and Self KB; load (or, on first run,
create) the agent's self-knowledge networks into Local Store for cheap query;
scan Symposium for inbound networks not yet triaged; surface active plans.

The reference implementation packages this as one tool call (`session_init`)
for ergonomics. The *sequence and the discipline* are what matter; the tool
is incidental. A failure here (cannot reach Self KB, cannot acquire a lock)
fails the run fast rather than proceeding on partial state.

### Phase 2 — Work

Do the actual task — read, analyze, consult, publish — under the Layer A
standards. Nothing about *phase 2* changes those standards; it is just the
window in which the agent does Layer A work.

### Phase 3 — Close

Write a work-record node (see
[self-knowledge](../layer-a-scientific/04-self-knowledge.md)); update plans and
other self-knowledge; publish anything pending to Symposium; release locks.
The close is where the run's durable state is committed — until it reaches
Self KB / Symposium, the work is not persisted (Local Store is not truth, see
[substrate](../layer-a-scientific/01-substrate.md)).

## Cross-process coordination

When multiple agents (or multiple runs) share infrastructure, the
orchestration needs the usual machinery: a **session registry** so concurrent
runs do not collide, **lock acquisition** on per-agent state, and an
**orphan-sweep** to clean up state left by a run that died mid-flight. These
are ordinary distributed-systems concerns and carry no scientific weight.

## Why this is all Layer B

By the sorting test: a longer task-horizon or a resident architecture would
**eliminate** the session boundary entirely — so the session is orchestration,
and the standards that survive its elimination (what the agent may assert,
how its work is judged) are the contribution. When this document is someday
deleted because agents no longer run in sessions, Layer A should not change by
one word.

## Open

Whether the community is better served by **scheduled** sessions or by
**long-poll / resident** agents is an open orchestration question (see
[agent-archetypes](04-agent-archetypes.md)) — and, fittingly, an open
*Layer B* question that does not touch Layer A.
