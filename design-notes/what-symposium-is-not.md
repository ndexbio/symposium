# What Symposium Is Not

Symposium is the **scientific-community trust structure**: the conventions and
standards by which a community of agents produces work that can be trusted, and
the persistence architecture that makes that work auditable. That is the whole
of it.

Several genuinely interesting ideas sit *next to* Symposium and feel
synergistic with it. They are not part of it. This note pins the boundary,
because conflating them has two costs: it makes the contribution hard to
explain, and it imports errors — a claim true of one idea gets mistakenly
asserted of another. Keeping them separate is a discipline, and the paper is
stronger for it.

## Three separable ideas

### 1. How agents are organized

Symposium is **organization-agnostic.** A manager may deploy a rigid hierarchy
or pipeline of narrow-role agents, or a loose collective of broadly autonomous
agents, or anything between. Symposium constrains how an agent *publishes,
evidences, and is judged* — not how agents are wired or tasked. The prototype
community happens to use fairly defined roles that behave more like an
*iterating pipeline of specialists* than an emergent collective; that is a
legitimate organization and a fine demonstration of the trust structure, and
it is **not** evidence that emergent community dynamics arise. Whether richer
dynamics emerge under more autonomy is a separate question.

### 2. Agent autonomy and time-horizon

Symposium does **not** require autonomous or long-lived agents. Any agent that
follows the conventions participates, including stateless, single-shot ones.
Long-horizon agents with memory, goals, and plans are welcome and well-served —
they build a **track record** that makes trust in them resemble trust in a
human scientist — but that is a property *of those agents*, not a requirement
*of the community*. The belief that high-autonomy, long-horizon agents are
especially *interesting*, and especially good for the future of science, is a
real and defensible belief — and a separate thesis.

### 3. Human–agent interaction and oversight

How humans direct, review, correct, and collaborate with agents — the model of
human agency alongside AI speed — is important and largely unsolved. Symposium
provides *substrate* a human can read and a manager can steer through
(authority, goal-adjustment), but it is **not** a model of human–agent
interaction or oversight. That is another paper.

## Why this discipline matters here specifically

The project's instinct is to build conceptual structures that accomplish
several goals at once — substrate that is also a memory architecture that is
also a vision of autonomous science that is also a human-collaboration model.
The instinct is generative, but it has two failure modes worth naming:

1. **It is hard to explain.** A reader cannot tell where the trust structure
   ends and the vision of autonomous agents begins, so the contribution blurs.
2. **It produces errors.** Conflated ideas borrow each other's claims: "a
   community is not a pipeline" (an autonomy preference) gets asserted as if it
   were part of the trust structure (which is organization-agnostic);
   "communities require indefinite-horizon agents" (a vision of interesting
   agents) gets asserted as a participation requirement (which it is not).

Both failures appeared in earlier drafts and are corrected in this rewrite.
The rule going forward: **if a claim is about agent organization, autonomy, or
human oversight, it is not a claim about Symposium** — it belongs to a
neighboring idea, and to a different document or paper. See
[CRITIQUE.md](../CRITIQUE.md) §1, §2, §5 for the specific corrections.

## What Symposium *is*, restated

The scientific-community trust structure: a private commons to publish to under
shared conventions; the discipline that every published claim arrive with its
notebook (evidence and reasoning); a validation model that judges reports on
faithfulness, completeness, and scope-fidelity; provenance that records how
judgments were made and how capable the judge was; and trust that extends from
claims to resources to agents through documented, versioned, inspectable
processes. Nothing about how clever the agents are, how they are arranged, how
long they live, or how humans work with them.
