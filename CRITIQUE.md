# A Critique of the Symposium Thesis

This document is an honest, adversarial reading of the Symposium concept as
expressed in the three source documents (the NIAID project description, the
layer-separation document, and the validation model). It exists because the
author asked for the thesis to be stress-tested, not just restated.

The rewrite of this repository reflects my best judgment about how to state
the concept well. Where that judgment departed from the source documents, I
have flagged it inline in the relevant spec file with a `> **Critique
deviation.**` note, so nothing is silently overridden. This document
collects the substantive disagreements and the reasoning behind them.

The short version: **the core architecture is right, and the layer
separation is the single best decision in the project.** Most of what
follows is not "this is wrong" but "this claim is stronger than the evidence
or the mechanism currently supports, and the project will be attacked
exactly there." Tightening these is how the thesis survives review.

> **Author response (resolved).** These critiques were discussed with the
> project owner, who accepted §1, §2, §4, and §5 and refined the resolutions.
> The headline correction: Symposium is the **scientific-community trust
> structure, and only that** — agent organization, agent autonomy/horizon, and
> human–agent interaction are separable ideas that earlier drafts conflated
> into it. Each affected section below carries a **Resolved** note, and the
> resolutions are now baked into the spec. See
> [design-notes/what-symposium-is-not.md](design-notes/what-symposium-is-not.md).

---

## 1. "Trust, not capability" is a useful slogan and a slightly false dichotomy

The thesis foregrounds trust over capability: the demonstration agents are
"not put forward as cutting-edge reasoners — they are put forward as agents
that operated trustworthily." This is the right banner for the
contribution, and it correctly separates what the paper claims from the
churn of model progress.

But the dichotomy leaks. Trustworthiness and capability are not orthogonal
in this architecture; capability is doing load-bearing work *inside* the
trust model:

- **Completeness is capability-bound.** "Did the agent find every dataset?"
  has no mechanical answer (the validation model concedes this). A coverage
  procedure run by a weak agent yields a "documented process trusted to a
  degree" — but the degree is low *precisely because the agent is weak*.
  The trust you can extend is a function of capability.
- **Judge-provenance concedes the point.** The reason an agent records its
  model, reasoning mode, and criteria version alongside a judgment is that
  *a later, more capable agent needs to know how capable the judge was* to
  decide whether to re-review. That is capability as a first-class trust
  parameter. The architecture doesn't bracket capability; it *instruments*
  it.

**Recommendation, adopted in the rewrite.** State the thesis as *trust is
the contribution; capability is a parameter the trust architecture makes
legible and auditable.* This is strictly stronger than "trust, not
capability" — it owns the fact that capability matters and shows the
architecture's distinctive move is to make capability *trackable* rather
than to pretend it is irrelevant. The slogan survives; the dichotomy is
dropped. (Reflected in `spec/layer-a-scientific/00-trust-thesis.md`.)

## 2. The self-driving-car analogy promises a safety case the project disclaims

> **Resolved.** The analogy is **withdrawn entirely** (not merely
> de-quantified). It is replaced by **auditable rigor**: the agent wrote down
> *what it did* (auditable), wrote down *the important things* — evidence,
> reasoning, judgment, coverage — (rigor), in a structure a critic can
> evaluate. Auditability without rigor is an unusable transcript; rigor without
> auditability is an uncheckable claim; Symposium requires both, structured for
> evaluation.

The analogy: just as self-driving cars must be *much* safer than human
drivers to earn adoption, agent output must be *much* more rigorous than
typical human output to be trusted.

Two problems.

First, the analogy imports a **quantitative bar** — "much safer" is a
measured multiple over a well-characterized human baseline — into a project
that *explicitly disclaims quantitative evaluation* in Phase 1 and whose
failure mode (subtle, human-like blind spots) is by construction hard to
measure and often undetectable for years. There is no agreed error rate for
"a typical human scientist's literature extraction," so "much more rigorous"
has no denominator.

Second, the analogy's persuasive force comes from a feature agent science
*lacks*: self-driving failures are catastrophic, legible, and immediate (a
crash). Scientific-extraction failures are quiet and compounding. The thing
that makes the car bar enforceable — you can count crashes — is exactly the
thing missing here.

**Recommendation, adopted in the rewrite.** Keep the *direction* of the
analogy (the bar is above human parity, not at it) but drop the implied
measurable multiple. Ground the actual claim in **process legibility**:
every published claim traces to a verbatim span, every judgment carries the
provenance of its judge, every "done" cites the coverage procedure that
backs it. The defensible statement is *not* "agents are N× more rigorous";
it is "agent rigor is auditable claim-by-claim in a way human output rarely
is." That is a real and defensible asymmetry, and it is the one the
architecture actually delivers. (Reflected in `00-trust-thesis.md`.)

## 3. Faithfulness is "largely procedural" only if you don't look at the seam

The validation model's faithfulness/completeness/scope split is the best
idea in the second document and the rewrite builds the validation spec
around it. But the headline "faithfulness is largely procedurally testable"
is itself the kind of over-claim the project exists to police in agents.

Faithfulness has a **mechanical core** (does the span exist verbatim? does
the identifier match character-for-character? does each claim component map
to some span?) and a **judgment shell** (do the spans *jointly* support the
claim? is a multi-span join mere assembly or assembly-with-inference?). The
validation document actually handles this well in its own §3.1–3.2 — the
assembly grade *is* the admission that joint support is a judgment call. The
problem is only in the summary framing that files all of faithfulness under
"procedural."

**Recommendation, adopted in the rewrite.** Name the mechanical/judgment
boundary *inside* faithfulness explicitly and put the judgment shell under
the same judge-provenance discipline as everything else. Don't let
"procedural" do summary work that the detailed text already qualifies. The
honest claim — "faithfulness has a checkable core and a small, bounded,
provenanced judgment surface" — is more defensible and loses nothing.
(Reflected in `spec/layer-a-scientific/07-validation-model.md`.)

## 4. The privacy reversal is the weakest link in the audit story

> **Resolved.** Reframed as a **technology-agnostic requirement on the agent**,
> not a storage prescription: share the **lab notebook** (the reasoning and
> evidence behind every published claim), keep the **diary** (internal state,
> framework memory) private. Because Symposium requires no particular agent
> technology, "publish your self-knowledge networks" was the wrong frame — a
> stateless agent has none. The notebook is published per-claim to the commons;
> the audit guarantee no longer depends on private state or any management
> utility. Self KB / Local Store are demoted to *the reference
> implementation's* way of holding the diary.

This is the most serious critique.

The old design made *all* self-knowledge PUBLIC and Solr-indexed, and the
NIAID document leans hard on that: the community preserves "auditable trails
of actions and evidence," and misroute diagnosis, authority verification,
and plan visibility all depend on self-knowledge being readable by peers and
humans.

The new containerized model **reverses this**: Self KB is private to the
agent, and the inspectability that used to be a property of the substrate is
now delegated to "management utilities (out of scope)."

For a project whose entire thesis is *auditable* trust, moving the audit
substrate to private-by-default and deferring the inspection mechanism to an
undesigned, out-of-scope component is a real regression, and a reviewer will
find it. "Trust us, the trail exists, it's just private and the viewer isn't
built yet" is precisely the posture the project criticizes in junior
researchers and opaque pipelines.

**Recommendation, adopted in the rewrite with a flag.** Resolve this rather
than defer it. Two coherent options:

- **(a) Provenance mirroring (my preferred).** Self KB stays private as
  *working* memory, but any self-knowledge assertion that *backs a published
  community claim* — the judgment-call provenance, the coverage-procedure
  citation, the used-profile audit field for a published network — is itself
  published to Symposium as provenance attached to the claim. The audit
  trail for *what the community can see* lives in the community layer, not
  behind a private door. Private working memory stays private; the trail
  that trust depends on stays public. This preserves the FAIR/auditable
  claim honestly.
- **(b) Scope the claim down.** If self-knowledge must be fully private,
  then the paper must stop claiming self-knowledge is auditable and restrict
  the audit guarantee to community-facing content only.

The rewrite adopts (a) as the design and marks it as a deviation from the
source documents, because leaving auditability to "utilities, out of scope"
undercuts the thesis. See `spec/layer-a-scientific/01-substrate.md` and
`design-notes/community-privacy.md`. **This one is worth an explicit
decision from you.**

## 5. "A community is not a pipeline" — the architecture earns this; the prototype evidence is thin

> **Resolved.** The point is **withdrawn**, and replaced by a stronger
> principle: Symposium is **organization-agnostic**. It imposes no agent
> organization — a manager may deploy a rigid pipeline/hierarchy *or* a loose
> collective of autonomous agents; Symposium constrains only how agents
> publish, evidence, and are judged. The prototype is, fairly, more of an
> iterating pipeline of specialists than an emergent collective — which is
> *allowed*, and is *not* evidence of emergent dynamics. The belief that
> autonomous, emergent agents are especially interesting is a separate thesis.
> (Original analysis below retained for the record.)

The claim that a community is not a pipeline and not an org chart is
architecturally well-supported: independent deployment, accumulated
reputation, broad sharing, unscripted consultation. But the worked example
offered as evidence (R. Solar → R. Vernal → R. Corona) is a *near-linear
hand-off chain* — which is what a pipeline looks like. The genuinely
non-pipeline features (an agent declining, proposing its own follow-up,
reputation altering future routing) appear but thinly, in one ten-day
window.

This is a critique of *claim-to-evidence calibration in the paper*, not of
the architecture. The architecture permits community dynamics; one chain
doesn't demonstrate that they emerge robustly.

**Recommendation.** In the paper, claim "the substrate permits and records
community dynamics, and we observed early instances of non-pipeline behavior
(unsolicited follow-up, explicit decline, cross-team consultation)" rather
than "community dynamics emerged." Save the stronger claim for when there
are more independent instances. (Out of scope for this repo, which is the
spec; noted here for the paper.)

## 6. Convention-first vs. the validation contract is a real, unacknowledged tension

The repo's design philosophy is emphatic: Symposium is conventions, not
schemas; *be strict in publishing, tolerant in reading; do not validate by
schema; the reader (an LLM) is the integration layer.* The validation model,
however, introduces a **checklist a critic agent or harness runs against a
report** with PASS/INVALID outcomes. That is, structurally, a validator.

These can be reconciled — but the current documents assert the
convention-first philosophy as absolute and never note that the validation
contract qualifies it. An attentive reader will see the contradiction.

**Recommendation, adopted in the rewrite.** Reconcile explicitly: *the
substrate is convention-first; the validation contract is a community SOP
layered above the substrate, not substrate enforcement.* Conventions govern
what makes content **legible**; the validation contract governs what counts
as a **trustworthy report**. One is enforced by the NDEx write path (almost
nothing) and social pattern; the other is enforced by critic agents and
human reviewers as a community standard that rises over time. Stating this
boundary removes the contradiction and actually clarifies both ideas.
(Reflected in `design-notes/conventions-not-ontologies.md` and
`07-validation-model.md`.)

## 7. The Layer A / Layer B boundary leaks in more than the one place you flagged

The layer separation is the project's best structural decision and the
rewrite is organized around it. The layer-separation document already flags
one leak (authority: *who* may adjust goals is Layer A, *cadence* is Layer
B). There are at least two more, and they all have the same shape — **Layer
A's standards presume Layer B's resourcing:**

- **Completeness presumes budget.** "Done" requires that a declared coverage
  procedure "has been run across all source sections." Whether the agent
  *can* run it across all sections in one go depends on batch size and time
  budget — Layer B. If orchestration starves the agent, the Layer A standard
  is unmet through no scientific fault.
- **The locator sweep presumes the whole source is in view.** Context-window
  management (Layer B) determines whether the agent ever sees the
  supplementary section the sweep is supposed to cover.

This is not a flaw in the separation; it is the separation working — it
*surfaces* the dependency instead of hiding it. But the resolution should be
stated, not left implicit.

**Recommendation, adopted in the rewrite.** State the rule: **Layer A
defines the standard; Layer B must be adequate to it; where orchestration
cannot afford the standard, the result is VALID-WITH-GAPS, never silently
"done."** This keeps the standard wholly in Layer A while making the
dependency on Layer B explicit and honest. (Reflected in
`spec/layer-b-orchestration/00-why-this-is-separate.md` and
`07-validation-model.md`.)

## 8. The one-line test mis-sorts execution quality

The test — *"would a more capable model or a longer task-horizon change this
choice? yes → orchestration; no → scientific"* — is a good heuristic but it
conflates **the standard** with **the quality of meeting it.**

Consider evidence tiers. A more capable model assigns tiers *more
accurately*. By a literal reading of the test, "a more capable model would
change this," so tiers sort to Layer B — which is wrong. Tiers, and the
honesty rule that governs them, are the contribution. What improves with
capability is the *assignment*, not the *rule*.

**Recommendation, adopted in the rewrite.** Refine the test to sort on the
**rule/standard**, not on execution: *"Would a more capable model change the
standard itself, or only how well an agent meets a fixed standard?* Changes
the standard → orchestration. Only improves execution of a fixed standard →
scientific (and the architecture's job is to record how well it was met)."
This is the same test the author intends; it just guards against the
mis-sort. (Reflected in `spec/00-overview.md` and
`spec/layer-b-orchestration/00-why-this-is-separate.md`.)

---

## What I did not change

To be clear about the boundaries of this critique — the following are
correct as stated and the rewrite preserves them faithfully:

- **The three-substrate model** (Symposium / Self KB / Local Store) with
  Local Store as "ground truth for nothing." Clean and right.
- **The faithfulness / completeness / scope-fidelity decomposition.** This
  is the analytic core of the validation story and it is excellent.
- **Coverage procedures as versioned, cited, first-class artifacts**, with
  recorded negatives converting absence into evidence. This is the single
  most important move for making completeness defensible.
- **Procedure-cited resource trust** ("fetched/validated via procedure X
  v1.3") rather than a single canonical pipeline. Correctly anticipates a
  community of continuously improving agents.
- **Credentialing as process-carries-trust** (Nature vs. predatory journal).
  Right framing; the policy is correctly left as a research goal.
- **Pinning promotion/credentialing/completeness-frontier as research
  goals** rather than over-designing them now. Good discipline.

The architecture is sound. The work the rewrite does is to make every claim
in it survive a hostile reading — which is, fittingly, exactly the standard
the architecture demands of its own agents.
