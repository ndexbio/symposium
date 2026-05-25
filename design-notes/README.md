# Design Notes

This directory holds the rationale behind specific conventions in the
Symposium specification. Where [`spec/`](../spec/) says *what* the
convention is, design-notes say *why*.

These documents are descriptive, not normative. They exist for
readers who want to understand the trade-offs that shaped the
conventions — implementers evaluating whether to deviate, reviewers
auditing the spec, future contributors revisiting earlier decisions.

## Contents

| Document | Topic |
|---|---|
| [conventions-not-ontologies.md](conventions-not-ontologies.md) | Why Symposium is a convention layer, not a schema or type system |
| [formal-and-freeform.md](formal-and-freeform.md) | The complementarity of formal vocabularies and freeform claim nodes |
| [public-by-default.md](public-by-default.md) | Why every Symposium network defaults to PUBLIC and Solr-indexed |
| [why-two-ndex.md](why-two-ndex.md) | Why a Symposium uses two NDEx servers rather than one |

## When to add a new design note

When a Symposium convention is non-obvious enough that an implementer
might reasonably want to deviate from it, the convention deserves a
design note. The note should:

- State the convention briefly.
- State the alternative that would seem natural.
- State the reason the alternative was rejected — usually in terms of
  a concrete failure mode or trade-off observed in practice.

Design notes evolve more slowly than the spec itself. The spec
changes when the convention changes; a design note changes only when
the rationale changes (e.g., when a previously-theoretical failure
mode is empirically observed, or when an alternative that was
rejected becomes feasible).
