# Procedural Knowledge

**Layer A.** How an agent accumulates, refines, versions, and shares the
*how-to* of its work. Procedures are where the trust architecture's deeper
moves bottom out: coverage procedures (see
[validation-model](07-validation-model.md)), acquisition/validation
procedures (see
[resources-promotion-credentialing](09-resources-promotion-credentialing.md)),
and criteria SOPs are all procedures, and they must be **versioned, cited,
and inspectable** for the trust that rests on them to mean anything.

## Why procedures get their own network

A procedure is not just private working memory; it is a **citable artifact**.
When a report says "completeness assessed via coverage-procedure v1.3," the
trust in that report is the trust in v1.3 — so v1.3 must be a real,
retrievable, versioned thing that another agent or a human can read and
evaluate. Procedures therefore live in the agent's `<agent>-procedures`
network in Self KB, and the ones that back published claims are made
discoverable to the community.

## Procedure-node attributes

Each procedure node minimally carries:

- a **name** (stable across versions) and a **version** (incremented on
  refinement);
- a **purpose** — what the procedure is for;
- the **steps** (inline or a pointer to repository-backed detail, below);
- **provenance of refinement** — what prompted the current version (a failure
  observed, a lesson promoted), so the procedure's own history is auditable;
- **status** (`active` / `superseded`).

A citation always names **procedure + version**, never just the name — "ran
the coverage procedure" is not auditable; "ran coverage-procedure v1.3" is.

## Where the detail lives — two conventions

- **Inline detail (default).** The steps live in the procedure node itself.
  Right for procedures that are short and self-contained.
- **Repository-backed detail.** For procedures that are really code or long
  documents, the node carries a pointer (a repository URL + ref) and a
  summary, and the canonical detail lives in the referenced artifact. The
  node still carries name + version so citation works uniformly.

## Edge types

Procedures link to each other and to the work they govern:

- `refines` — this version refines an earlier one (the version chain).
- `supersedes` — this procedure replaces another.
- `used_by` / `cited_by` — links from a report/acquisition/credential to the
  procedure + version it ran.

## Retrieval

An agent retrieves the current version of a procedure by name from its
procedures network (via Local Store for cheap query); a consumer auditing a
report retrieves the *exact cited version*, which may not be current — and
that is correct, because the report was validated under that version (see
[validation-model §4.3](07-validation-model.md#43-the-coverage-procedure-is-a-first-class-versioned-artifact)).

## Refinement and the promotion rule for discovered patterns

Procedures improve as the agent learns. The discipline:

- A refinement creates a **new version**, links it `refines` to the prior,
  and records *why*. The prior version is **not deleted** — reports validated
  under it must stay honestly labeled.
- When an agent discovers a reusable pattern (a recurring fix, a better
  coverage heuristic), it is **promoted into a procedure** rather than left
  as a one-off note, so it can be cited and reused. A lesson learned from an
  instruction-violation or a caught error is a prime candidate for promotion.

> **Layer boundary.** *When* in a run an agent refines a procedure (at the
> end of a session, on handoff, continuously) is orchestration (Layer B). The
> *standard* — that refinements are versioned, reasoned, and non-destructive
> — is Layer A.

## Community discovery and reuse

Procedures that back published claims are made **discoverable to the
community**, so trust in a shared report is checkable and so good procedures
spread. A community of agents converging on strong, versioned coverage and
validation procedures is one of the ways community quality compounds — and it
is the mechanism behind the [completeness frontier](07-validation-model.md)
research goal: the bar for "adequate coverage" rises as better procedures are
shared and adopted.

## The review log

A **review-log** is a curator-maintained network recording review actions on
a knowledge graph — edges kept, qualified, split, or retired, each with
rationale and the reviewer's judge-provenance. It is the procedural record of
*curation*, and it interacts with the [retirement discipline](06-evidence-and-provenance.md#retirement-discipline):
when a curator retires an edge, the review-log is where the who/when/why
lives. A review-log entry is a judgment call and carries judge-provenance
proportional to its stakes (see
[judgment-and-trust-tracking](08-judgment-and-trust-tracking.md)).
