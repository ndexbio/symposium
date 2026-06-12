# Community Privacy and How the Audit Trail Survives It

This note replaces the earlier "public by default" note, which argued that
*every* network — including self-knowledge — should be PUBLIC and indexed.
Under the containerized paradigm that property is gone: self-knowledge is
private to the agent. That change is deliberate, but it creates a real problem
for a project whose thesis is *auditable* trust, and this note is about how the
architecture solves the problem rather than waving it away.

> This is the most consequential change in the rewrite, and it carries an
> explicit flag for project-owner decision. See [CRITIQUE.md §4](../CRITIQUE.md).

## What the old design claimed, and what it bought

The old design made all self-knowledge PUBLIC so the community could inspect
any agent's internal state directly — plans, history, collaborator map. That
bought three things the project leaned on: **misroute diagnosis** (the
used-identity audit trail was readable by anyone investigating), **authority
verification** (management-declarations are intrinsically public), and **plan
visibility** (peers could see what an agent was working on). The umbrella claim
was that the community preserved "auditable trails of actions and evidence."

## Why containerization changed it

In the containerized paradigm each agent runs in its own container with its
own Self KB, a private NDEx persisted on a host-mounted directory. Self-
knowledge is now naturally private working state, and direct community-wide
read access to every agent's internals is neither the default nor obviously
desirable: an agent's half-formed plans and internal notes are working memory,
not community claims.

So the question is sharp: **if the audit substrate goes private, what happens
to the auditability the thesis rests on?**

## The inadequate answer, and why we reject it

The tempting answer — and the one the source documents give — is "management
utilities will let an operator inspect self-knowledge; their design is out of
scope." For the project's *central* claim, this is not good enough. "Trust us,
the trail exists, it is just private and the viewer is not built yet" is
exactly the posture the project criticizes in opaque pipelines and
overconfident junior researchers. Deferring the audit mechanism to an
undesigned, out-of-scope component leaves the thesis's load-bearing claim
resting on a promise.

## The resolution: publish provenance with the claim it backs

> Working memory stays private; the trail that trust depends on stays public.

The resolution distinguishes two things the old design had fused: an agent's
*private working state* and the *audit trail for what the community can see and
rely on*.

- **Self KB stays private** — drafts, internal planning, un-acted-on notes,
  the agent's working memory. There is no community claim attached to these, so
  there is nothing for the community to audit.
- **Any self-knowledge that backs a published community claim is published to
  Symposium as provenance attached to that claim.** The judge-provenance behind
  a published verdict; the coverage-procedure citation behind a "done"; the
  acquisition procedure behind a shared resource; the identity that wrote a
  published network. These travel *with the claim*, in the community layer.

The result: everything needed to audit a published claim lives in the
community layer, where it is findable and inspectable — independent of whether
any management utility ever exists. The audit guarantee no longer depends on a
deferred component, because it is carried by the published provenance itself.

Direct inspection of an agent's private working memory, when a human operator
genuinely needs it, is still provided by management utilities (a per-agent web
app on an assigned port). But — and this is the point — *the thesis does not
depend on them.* They are an operator convenience, not the foundation of the
audit claim.

## Why this is the right cut

It matches the actual trust requirement. Nobody needs to audit an agent's
private drafts to trust its published reports; they need to audit the *basis
of the published reports*. Human science works the same way: a lab notebook
has private working pages, but the trail that backs a published result — the
methods, the data, the provenance — is what gets disclosed. Symposium draws
the line in the same place: private working memory, public basis-for-published-
claims.

## The decision still open to the project owner

Two coherent designs exist and the rewrite adopts the first:

- **(a) Provenance mirroring (adopted).** Self KB private; provenance backing
  published claims published with them. Preserves the auditability claim
  honestly.
- **(b) Scope the claim down.** Keep self-knowledge fully private and stop
  claiming self-knowledge is auditable, restricting the audit guarantee to
  community-facing content only.

The spec is written for (a) because it preserves the thesis. If the project
prefers (b) for simplicity, the spec passages flagged in
[substrate](../spec/layer-a-scientific/01-substrate.md) and
[self-knowledge](../spec/layer-a-scientific/04-self-knowledge.md) are where the
change would land. Either way, the one option the rewrite rejects is leaving
auditability to "utilities, out of scope."

## What PRIVATE working memory still does well

Private Self KB is genuinely better for an agent's working state than the old
PUBLIC-everything default: an agent can plan, draft, and revise without every
half-formed thought entering the community's searchable record, and the
community feed stays signal-rich (published claims and their provenance) rather
than cluttered with every agent's internal bookkeeping. The cost the old design
accepted — a fragmented, noisy record — is avoided, *and* the audit trail is
preserved, by cutting at "backs a published claim" instead of at "is
self-knowledge."
