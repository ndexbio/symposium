# Procedural Knowledge

How an agent accumulates, refines, versions, and shares the *how-to* of its
work. Procedures are where the trust architecture's deeper moves bottom out:
coverage procedures (see [validation-model](06-validation-model.md)),
acquisition/validation procedures (see
[resources-promotion-credentialing](08-resources-promotion-credentialing.md)),
and criteria SOPs are all procedures. This document states the **requirement**
they must meet; the structure the reference implementation uses to store them
is in [Memento: procedural memory](https://github.com/ndexbio/memento/blob/main/design-docs/04-procedural-memory.md).

## The requirement: versioned, cited, inspectable

A procedure is not just private working memory; it is a **citable artifact**.
When a report says "completeness assessed via coverage-procedure v1.3," the
trust in that report is the trust in v1.3 — so v1.3 must be a real, retrievable,
versioned thing another agent or human can read and evaluate. Therefore:

- A procedure has a **stable name** and a **version**, and its current and
  prior versions are both retrievable.
- A citation always names **procedure + version**, never just the name — "ran
  the coverage procedure" is not auditable; "ran coverage-procedure v1.3" is.
- A consumer auditing a report retrieves the *exact cited version*, which may
  not be the current one — and that is correct, because the report was
  validated under that version (see
  [validation-model §4.3](06-validation-model.md#43-the-coverage-procedure-is-a-first-class-versioned-artifact)).
- Procedures that back published claims are **discoverable to the community**,
  so trust in a shared report is checkable.

How these are stored — node attributes, `refines` / `supersedes` edges, the
`<agent>-procedures` network, the query path — is implementation detail (see
the Memento link above). What Symposium requires is the *versioned, cited,
inspectable, discoverable* property, not any particular storage.

## Refinement and the promotion rule

Procedures improve as the agent learns, under two disciplines:

- A refinement creates a **new version** and records *why*; the prior version
  is **not deleted** — reports validated under it must stay honestly labeled.
- When an agent discovers a reusable pattern (a recurring fix, a better
  coverage heuristic), it is **promoted into a procedure** rather than left as
  a one-off note, so it can be cited and reused. A lesson learned from a caught
  error or an instruction-violation is a prime candidate.

> **Requirement vs. method.** *When* in a run an agent refines a procedure (at
> a session boundary, on handoff, continuously) is orchestration — a Memento
> concern. *That* refinements are versioned, reasoned, and non-destructive is
> the Symposium requirement.

This is the mechanism behind the [completeness-frontier](06-validation-model.md)
research goal: as agents converge on strong, versioned coverage and validation
procedures and share them, the bar for "adequate coverage" rises.

## The review log

A **review-log** records review actions on a knowledge graph — edges kept,
qualified, split, or retired, each with rationale and the reviewer's
judge-provenance. It is the curation counterpart of procedural memory, and it
interacts with the [retirement discipline](05-evidence-and-provenance.md#retirement-discipline):
when a curator retires an edge, the review-log is where the who/when/why lives.
A review-log entry is a judgment call and carries judge-provenance proportional
to its stakes (see [judgment-and-trust-tracking](07-judgment-and-trust-tracking.md)).
Its storage form, like other procedural structures, is described in the Memento
design doc.
