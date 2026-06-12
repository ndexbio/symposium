# Context Management and Handoff

**Layer B — ephemeral.** How an agent copes with a finite context window
while doing work that exceeds it. Tied directly to context-window size, which
is growing — so this is among the most short-lived material in the repo.

## The pattern

An agent processes until its context fills to the point where performance
would degrade, then performs a **graceful handoff** to a fresh context:
summarize state, persist anything durable to Self KB / Symposium, and resume
in a clean context that loads only the slice it needs (via Local Store query —
see [substrate](../layer-a-scientific/01-substrate.md)). The **container may
keep running across many such handoffs**; the context is recycled, the agent
persists.

This is the practical reason Self KB and Local Store exist as a memory
architecture: the agent externalizes its knowledge so a fresh context can
reload precisely what it needs rather than carrying everything in-window.

## The Layer A invariant across a handoff

A handoff is invisible to Layer A. The standards do not know or care that the
context was recycled mid-task:

- Durable state is whatever reached Self KB / Symposium **before** the
  handoff — Local Store does not survive as truth (see
  [substrate](../layer-a-scientific/01-substrate.md)).
- A coverage procedure that spans a handoff still must be **run across all
  sections**; if the handoff caused a section to be dropped, that is the
  adequacy rule's VALID-WITH-GAPS case, recorded honestly (see
  [00-why-this-is-separate.md](00-why-this-is-separate.md)).
- Work-records and judgment-provenance are written as the work happens, so a
  handoff (or even a crash) never loses the trail of what was already
  asserted.

## Why this is Layer B

As context windows grow, handoff frequency drops toward zero and this entire
mechanism fades — without changing one Layer A standard. The need to *not
lose the audit trail across a context boundary* is Layer A (it is just
provenance discipline); the *mechanics of the boundary itself* are Layer B.
