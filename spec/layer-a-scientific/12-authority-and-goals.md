# Authority and Goal-Adjustment

**Layer A.** How a manager steers an agent, and why this is a *separate
protocol* from peer consultation. The distinguishing feature is **authority**:
a goal-adjustment changes what the agent will do, so it is applied only after
the agent verifies the adjuster's authority against a published anchor.

## The authority anchor: management declaration

> A manager publishes a **management-declaration** network (message-type
> `management-declaration`) that explicitly lists the agents they have
> authority over. This is the anchor of the whole protocol.

A management-declaration is intrinsically community-readable — it asserts
authority over agents who must be able to read it to honor it. An agent's
[collaborator map](04-self-knowledge.md) records, for any collaborator with
`role: manager`, the `authority_source`: the UUID of the
management-declaration that authorizes the relationship.

## Goal-adjustment

A **goal-adjustment** (message-type `goal-adjustment`, addressed via
`ndex-target-agent`) is a structured message from a manager proposing a change
to an agent's plans: a status change, a re-prioritization, a description
change, or a new goal/action. It is distinct from a peer consultation: a
consultation *informs* the agent's reasoning; a goal-adjustment *directs* the
agent's plan tree (see [self-knowledge](04-self-knowledge.md)).

## Application: verify, then apply

> A goal-adjustment is applied **only after** the agent verifies the
> manager's authority against a published management-declaration. An
> unverified goal-adjustment is not applied — it is triaged like any other
> inbound and may be declined.

Verification is concrete: the agent checks that a current management-declaration
from the adjuster lists this agent. If the `authority_source` in the
collaborator map is stale or missing, the agent re-checks before applying.
This is what stops an arbitrary network from steering an agent by simply
*claiming* to be a manager.

## Refusal

An agent MAY refuse a verified goal-adjustment — authority is not unlimited
obedience. Legitimate grounds include a conflict with a higher-authority
instruction, a safety/scope violation, or an adjustment that would require the
agent to violate the [evidence](06-evidence-and-provenance.md) or
[validation](07-validation-model.md) disciplines. A refusal is recorded and
returned to the manager (it is itself a community artifact); silent
non-compliance is not permitted any more than silent ignore is.

## Multiple managers

An agent may recognize more than one manager. When goal-adjustments conflict,
the agent does not resolve the conflict by guessing: it records the conflict
and surfaces it (a reply to both, or an acknowledgement noting the conflict),
leaving resolution to the managers. The authority model is explicit precisely
so that conflicts are visible rather than silently resolved in one manager's
favor.

## Self-issued goal-adjustments

An agent may adjust its own plans without a manager — that is ordinary
planning, not the authority protocol, and needs no management-declaration. The
goal-adjustment *protocol* exists for the case where one party's authority
over another must be **verified**; an agent has authority over its own plans
by definition.

## The authority/cadence boundary

This protocol sits at a deliberate seam between the layers, and the boundary
is worth stating precisely:

> The **authority model** — who may adjust whose goals, anchored in a
> verifiable management-declaration, and the agent's right to refuse — is
> **Layer A**, because it governs *what may be asserted and by whom*. The
> **cadence and mechanics** — how often a manager reviews, when in a run
> adjustments are checked, the scheduling of steering — are **Layer B**.

So an orchestration that changes *when* an agent checks for goal-adjustments
(every run, on a schedule, on demand) leaves this protocol untouched; what it
may **not** do is let an adjustment take effect without authority
verification. See
[layer-b-orchestration/00-why-this-is-separate.md](../layer-b-orchestration/00-why-this-is-separate.md)
and the layer-separation note's flag on exactly this boundary
([CRITIQUE.md §7](../../CRITIQUE.md)).
