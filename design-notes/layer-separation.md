# Why the Repo Splits into Two Layers

The single most important structural decision in Symposium is the separation
of the **scientific-community architecture** (Layer A) from the
**orchestration architecture** (Layer B). The repository makes the split
physical: two sibling directories under `spec/`, with Layer B explicitly
marked ephemeral. This note explains why the separation exists and why it is
worth the discipline of maintaining it.

## The natural alternative

The obvious thing is to write one integrated specification: here is how an
agent runs, and woven through it, here is what makes its output trustworthy.
This is how the earlier draft read — "session" appeared as a primitive
throughout, evidence discipline and session lifecycle interleaved, the trust
rules expressed in terms of the run mechanics that happened to carry them.

It is the wrong structure, for one decisive reason.

## The two layers change at wildly different rates

Layer A — what an agent may assert, what backs it, how it is judged — is
**slow-changing**. The need to anchor a claim to its source, to record how a
judgment was made, to define "done" defensibly: these are about the nature of
trustworthy scientific work and they will look much the same in five years.

Layer B — sessions, batch sizes, context-window management, handoffs, whether
an agent is scheduled or resident — is **changing fast**. Coherent-task
horizons are climbing rapidly; today's batch caps and session mechanics will
be obsolete soon.

When the two are tangled, the fast-churning layer drags the slow one with it.
A spec that defines completeness in terms of "what an agent does in a session"
has to be rewritten every time the session model changes — even though
*completeness itself did not change*. Worse, the **contribution gets muddied**:
a reader cannot tell which parts of the spec are the durable scientific claim
and which are the disposable run mechanics. The paper points at the spec; if
the spec cannot distinguish its contribution from its scaffolding, neither can
the paper.

## The principle

> A concept belongs to **Layer A** if it governs *what an agent may assert and
> how its work is judged*. It belongs to **Layer B** if it governs *how an
> agent's work is chunked, scheduled, or resourced.*

This mirrors how human science already works: the standards by which a finding
is trusted (peer review, reproducibility, provenance of methods) are
independent of the logistics by which a lab schedules its people and
instruments. Nobody thinks "we run lab meetings on Tuesdays" is part of the
epistemology.

## The sorting test, and its refinement

> Would a more capable model or a longer task-horizon change the **standard
> itself**, or only how well an agent **meets** a fixed standard?
> Changes the standard → Layer B. Only improves execution → Layer A.

The refinement — sorting the *standard*, not the *execution quality* — guards
against a real mis-sort. A naïve test ("would a better model change this
choice?") sends evidence tiers to Layer B, because a better model assigns
tiers more accurately. But tiers and their honesty rule are Layer A:
capability improves the *assignment*, not the *rule*. The architecture's job
is precisely to record *how well* a fixed standard was met (that is what
judge-provenance is) — so "improves with capability" is not a sign of being
orchestration; *changing the standard* is. See [CRITIQUE.md §8](../CRITIQUE.md).

## The layers touch in exactly one honest place: adequacy

The separation is not a claim that the layers are independent — it is a claim
that the *dependency runs one way and is made explicit*. Layer A standards
sometimes presume Layer B resourcing: completeness requires running a coverage
procedure across all sections, which presumes the budget and context to do so.

Rather than hide this, the spec states it:

> Layer A defines the standard. Layer B must be **adequate to** it. Where
> orchestration cannot afford the standard, the result is **VALID-WITH-GAPS**,
> never silently "done."

A starved run does not get to lower the scientific bar; it gets to honestly
report that it could not reach it. This keeps the standard wholly in Layer A
while acknowledging — rather than denying — that meeting it costs resources
the orchestration must supply. The seam is real; making it explicit is the
point. See [CRITIQUE.md §7](../CRITIQUE.md).

## The test of a clean separation

> When Layer B is someday rewritten wholesale — sessions replaced by resident
> agents, batches replaced by continuous processing — **not one word of Layer
> A should change.**

That invariance is the whole payoff. It is what lets the paper claim a durable
contribution while running the demo on whatever orchestration is convenient
today, clearly marked as "how we happened to run it."

## Where the earlier draft resisted the split

Reconciling the earlier repo toward this structure surfaced the frictions
worth recording as findings: "session" was treated as a unit of meaning in
self-knowledge (re-expressed as orchestration-agnostic work-records);
self-knowledge was PUBLIC-by-default for community inspectability (a property
that belonged to the audit story, not the run model — see
[community-privacy.md](community-privacy.md)); and the authority model and its
cadence were fused (split, with authority in A and cadence in B — see
[spec/layer-a-scientific/12-authority-and-goals.md](../spec/layer-a-scientific/12-authority-and-goals.md)).
Each friction was a place where a Layer A standard had been expressed in Layer
B terms; each is a small confirmation that the separation was needed.
