# Requirements vs. Methods

The single most important structural decision in this project is the separation
of **requirements** — what Symposium asks of any trustworthy agent — from
**methods** — how a particular framework (Memento) meets those requirements.
The two now live in two repositories: requirements in Symposium, methods in
Memento's [`design-docs/`](https://github.com/ndexbio/memento/tree/main/design-docs).
This note explains why the separation exists and why it is worth maintaining.

## The natural alternative

The obvious thing is to write one integrated specification: here is how an
agent runs, and woven through it, here is what makes its output trustworthy.
This is how the earliest draft read — "session" appeared as a primitive
throughout, evidence discipline and session lifecycle interleaved, the trust
rules expressed in terms of the run mechanics that happened to carry them.

It is the wrong structure, for one decisive reason.

## Requirements and methods change at wildly different rates

The **requirements** — what an agent may assert, what backs it, how it is
judged — are **slow-changing**. The need to anchor a claim to its source, to
record how a judgment was made, to define "done" defensibly: these are about
the nature of trustworthy scientific work and they will look much the same in
five years.

The **methods** — sessions, batch sizes, context-window management, handoffs,
memory storage, whether an agent is scheduled or resident — are **changing
fast**. Coherent-task horizons are climbing rapidly; today's batch caps and
session mechanics will be obsolete soon.

When the two are tangled, the fast-churning methods drag the slow requirements
with them. A spec that defines completeness in terms of "what an agent does in a
session" has to be rewritten every time the session model changes — even though
*completeness itself did not change*. Worse, the **contribution gets muddied**:
a reader cannot tell which parts are the durable scientific claim and which are
the disposable run mechanics. The paper points at the requirements; if they
cannot be distinguished from their scaffolding, neither can the paper.

## The principle

> A concept is a **requirement** (Symposium) if it governs *what an agent may
> assert and how its work is judged*. It is a **method** (Memento) if it
> governs *how an agent's work is stored, chunked, scheduled, or resourced.*

This mirrors how human science already works: the standards by which a finding
is trusted (peer review, reproducibility, provenance of methods) are
independent of the logistics by which a lab schedules its people and
instruments. Nobody thinks "we run lab meetings on Tuesdays" is part of the
epistemology.

A document also belongs to Symposium if it would still be true and necessary
after deleting Memento entirely, and to Memento if another conforming agent
could make the choice differently. The two phrasings pick out the same line.

## The sorting test, and its refinement

> Would a more capable model or a longer task-horizon change the **standard
> itself**, or only how well an agent **meets** a fixed standard?
> Changes the standard → method (Memento). Only improves execution →
> requirement (Symposium).

The refinement — sorting the *standard*, not the *execution quality* — guards
against a real mis-sort. A naïve test ("would a better model change this
choice?") sends evidence tiers to the methods column, because a better model
assigns tiers more accurately. But tiers and their honesty rule are a
requirement: capability improves the *assignment*, not the *rule*. The
architecture's job is precisely to record *how well* a fixed standard was met
(that is what judge-provenance is) — so "improves with capability" is not a sign
of being a method; *changing the standard* is. See
[CRITIQUE.md §8](../CRITIQUE.md).

## They touch in exactly one honest place: adequacy

The separation is not a claim that requirements and methods are independent —
it is a claim that the *dependency runs one way and is made explicit*. A
requirement sometimes presumes the method supplies enough resource:
completeness requires running a coverage procedure across all sections, which
presumes the budget and context to do so.

Rather than hide this, the spec states it:

> The requirement defines the standard. The method must be **adequate to** it.
> Where the method cannot afford the standard, the result is **VALID-WITH-GAPS**,
> never silently "done."

A starved run does not get to lower the scientific bar; it gets to honestly
report that it could not reach it. This keeps the standard wholly in the
requirements while acknowledging — rather than denying — that meeting it costs
resources the method must supply. The seam is real; making it explicit is the
point. See [CRITIQUE.md §7](../CRITIQUE.md).

## The test of a clean separation

> When Memento's methods are someday rewritten wholesale — sessions replaced by
> resident agents, batches by continuous processing — **not one word of the
> Symposium requirements should change.**

That invariance is the whole payoff. It is what lets the paper claim a durable
contribution while running the demo on whatever methods are convenient today,
clearly marked as "how we happened to run it."

## A note on the earlier "two-layer" framing

An intermediate draft of this repo split the spec into "Layer A" (the
scientific contribution) and "Layer B" (orchestration), as two sibling
directories. That was the right first cut, and its natural conclusion is the
arrangement described here: Layer B was always *methods*, so it moved to
Memento, and the "Layer A/B" vocabulary is retired in favor of
"requirements vs. methods." Reconciling the repo through that split surfaced
the frictions worth recording: "session" had been treated as a unit of meaning
in self-knowledge (re-expressed as run-agnostic work-records); self-knowledge
was PUBLIC-by-default for community inspectability (a property that belonged to
the audit story, not the run model — see [community-privacy.md](community-privacy.md));
and the authority model and its cadence were fused (split, with authority a
requirement and cadence a method — see
[spec/requirements/11-authority-and-goals.md](../spec/requirements/11-authority-and-goals.md)).
Each friction was a place where a requirement had been expressed in method
terms; each is a small confirmation that the separation was needed.
