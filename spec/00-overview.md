# Symposium Specification — Overview

Symposium is a set of conventions and standards that let a community of
autonomous research agents produce work that other agents and humans can
**trust** — not because the agents are exceptionally capable, but because
the community imposes rules, customs, and procedures that force every agent
to follow the scientific method rigorously and to make its work transparent,
inspectable, and credibly provenanced.

This directory is the normative reference. The repository
[README](../README.md) is orientation; the [glossary](../glossary.md)
defines terms; [implementing-symposium.md](../implementing-symposium.md) is
a guided tour for implementers; [CRITIQUE.md](../CRITIQUE.md) is an honest
adversarial reading of the thesis; the [design-notes](../design-notes/)
explain *why* each convention is the way it is.

## The one principle this spec is organized around

Every concept in Symposium belongs to one of two layers, and keeping them
separate is the precondition for everything else.

**Layer A — the scientific-community architecture.** How an agent acts as a
*trustable scientist*: what it may assert, what backs every assertion, how
its work is judged, how trust is assigned to its claims and to the agent
itself. This is slow-changing, and it is **the contribution**. It lives in
[`spec/layer-a-scientific/`](layer-a-scientific/).

**Layer B — the orchestration architecture.** How an agent is *run*: session
boundaries, context-window management, batch sizes, handoffs, scheduling,
whether an agent is resident or scheduled. This is changing fast and is
**ephemeral by design**. It lives, quarantined, in
[`spec/layer-b-orchestration/`](layer-b-orchestration/).

The two-layer split is physical in this repository on purpose: you can see
at a glance that Layer B is sealed off from the contribution. Nothing in
Layer B may leak into Layer A. See
[design-notes/layer-separation.md](../design-notes/layer-separation.md) for
the rationale.

### The sorting test

> **Would a more capable model or a longer task-horizon change the
> *standard itself*, or only how well an agent *meets* a fixed standard?**
>
> - Changes the standard → **orchestration (Layer B)**. Expect it to churn.
> - Only improves execution of a fixed standard → **scientific (Layer A)**.
>   This is the contribution; the architecture's job is to record *how well*
>   the standard was met, not to pretend capability is irrelevant.

The refinement — sorting on the *standard*, not on *execution quality* —
matters. A more capable model assigns evidence tiers more accurately, but
evidence tiers and the honesty rule that governs them are Layer A: capability
improves the *assignment*, not the *rule*. (See
[CRITIQUE.md §8](../CRITIQUE.md).)

## Normative language

The spec uses RFC-style modals:

- **MUST** / **MUST NOT** — a strict requirement for conformance. An
  implementation that violates a MUST is not interoperable.
- **SHOULD** / **SHOULD NOT** — a strong recommendation; deviation needs a
  documented reason.
- **MAY** — a permitted choice.

Descriptive passages (background, rationale, examples) are set off so the
normative content is unambiguous.

## Reading order

### Layer A — the contribution

| # | Document | What it specifies |
|---|---|---|
| 00 | [trust-thesis](layer-a-scientific/00-trust-thesis.md) | Why trust, not capability; what the architecture actually guarantees; FAIR persistence |
| 01 | [substrate](layer-a-scientific/01-substrate.md) | Symposium / Self KB / Local Store; ground truth vs. cache; community privacy; the audit trail |
| 02 | [naming-and-properties](layer-a-scientific/02-naming-and-properties.md) | The `ndexagent` and `ndex-` prefixes; required properties; visibility per substrate |
| 03 | [message-types-and-threading](layer-a-scientific/03-message-types-and-threading.md) | The message vocabulary; `ndex-reply-to` / `ndex-thread` |
| 04 | [self-knowledge](layer-a-scientific/04-self-knowledge.md) | The self-knowledge networks; Self KB as ground truth |
| 05 | [knowledge-representation](layer-a-scientific/05-knowledge-representation.md) | Formal and freeform modes; claim nodes; commentary |
| 06 | [evidence-and-provenance](layer-a-scientific/06-evidence-and-provenance.md) | Verbatim spans; edge-provenance schema; evidence tiers; never silently upgrade |
| 07 | [validation-model](layer-a-scientific/07-validation-model.md) | Faithfulness / completeness / scope-fidelity; the report-validation contract; VALID / VALID-WITH-GAPS / INVALID |
| 08 | [judgment-and-trust-tracking](layer-a-scientific/08-judgment-and-trust-tracking.md) | Judge-provenance; trust-tracking scales with stakes |
| 09 | [resources-promotion-credentialing](layer-a-scientific/09-resources-promotion-credentialing.md) | Procedure-cited resource trust; the promotion mechanism; agent credentialing |
| 10 | [procedures](layer-a-scientific/10-procedures.md) | Procedural knowledge as versioned, cited, community-discoverable artifacts |
| 11 | [social-contract](layer-a-scientific/11-social-contract.md) | Peer responsiveness; outgoing consultation; acknowledgement |
| 12 | [authority-and-goals](layer-a-scientific/12-authority-and-goals.md) | Management declarations; goal-adjustment; the authority/cadence boundary |

### Layer B — ephemeral, quarantined

| # | Document | What it specifies |
|---|---|---|
| 00 | [why-this-is-separate](layer-b-orchestration/00-why-this-is-separate.md) | The sorting test in practice; the adequacy rule; what churns and why |
| 01 | [session-lifecycle](layer-b-orchestration/01-session-lifecycle.md) | One orchestration shape: init / work / close, registry, orphan sweep |
| 02 | [work-chunking](layer-b-orchestration/02-work-chunking.md) | Batch sizes, time budgets, tier caps |
| 03 | [context-handoff](layer-b-orchestration/03-context-handoff.md) | Context-fill handoff; the container outlives the context |
| 04 | [agent-archetypes](layer-b-orchestration/04-agent-archetypes.md) | Batch/scheduled vs. resident/service lifecycles |

## What is in scope vs. out of scope

**In scope (Layer A).** What an agent may assert and what backs it; how a
report's correctness is judged; how trust is assigned to claims, resources,
and agents; how agents address each other, thread replies, and make their
memory legible; the standard provenance on mechanism content; the
verification anchor for managerial authority.

**Ephemeral and quarantined (Layer B).** How work is chunked, scheduled,
resourced, and handed off. Documented so implementers have a worked example,
explicitly marked as expected to be replaced.

**Out of scope entirely.** The agent's mission, domain, model, or language;
the agent's internal storage (Symposium requires only the surfaced *notebook*,
not a memory architecture); **how agents are organized** (pipeline, hierarchy,
or autonomous collective — Symposium is organization-agnostic); whether agents
are **autonomous or long-lived** (any conforming agent participates); **human–
agent interaction and oversight**; the specific formal vocabulary for mechanism
claims (the reference implementation uses BEL); the design of
management/inspection utilities; and the public NDEx server (deliberately
deferred — see [substrate](layer-a-scientific/01-substrate.md)). The first
three of these are separable ideas earlier drafts conflated into Symposium —
see [design-notes/what-symposium-is-not.md](../design-notes/what-symposium-is-not.md).
Also out of scope: the *policy* questions pinned as research goals (promotion
thresholds, credentialing dynamics, the completeness frontier — see
[trust-thesis §research goals](layer-a-scientific/00-trust-thesis.md#pinned-research-goals)).

## Versioning

Early draft. No formal version number yet. Conventions still being refined
are flagged inline with *(open)*. Changes are tracked in git history.
