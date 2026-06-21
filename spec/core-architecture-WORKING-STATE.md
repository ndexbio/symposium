# Core Architecture — Working State / Conversation Capture

> **Purpose of this file.** A durable snapshot of the live co-editing discussion on
> [core-architecture.md](core-architecture.md) between Dexter and Claude, captured
> 2026-06-20 so the thread survives any loss of session context. This is a *scratch /
> handoff* file, not part of the spec. Delete or fold into the main doc once §1–§7 and
> the artifact-types section stabilize.

## How we are working

- Co-editing [core-architecture.md](core-architecture.md) — the project's
  **epistemological foundation** (the layer *under* [00-trust-thesis](requirements/00-trust-thesis.md),
  which covers scope/what-it-is-not).
- Mode: **one point at a time**, sharp critique, normal discussion (do NOT re-dump full
  analyses each turn). Dexter wants the thesis *revised and restructured*, not defended.
- Convention in the doc: `⊘ DEBATE` = open question; `↻ REVISIT` = inherited claim that
  may need surgery. Open-question index lives in the doc's Appendix B with
  RESOLVED/OPEN status.
- Dexter's email: depratt@ucsd.edu. Dexter writes re-frames directly into the doc (see
  §0.1 "Dexter's initial re-frame" — preserved verbatim, it is the origin of the spine).

## Document status

`core-architecture.md` has been **rewritten in place** around a new spine derived from
Dexter's §0.1 re-frame + the design conversation. Structure now:

- §0 / §0.1 — framing + Dexter's verbatim re-frame (origin of everything).
- §1 — assertion is the trust atom; **publishing = judgment** (all artifacts are
  judgments); two trust factors: **integrity** vs. **interpretive distance**;
  assertions live on an **interpretive-distance spectrum** (NOT observability; orthogonal
  to scope).
- §2 — **integrity** named, then **scoped out of this study with warrant** (it's the
  reputation axis; orthogonal to the measurement→assessment flow). Cooperative-by-
  assumption.
- §3 — grounding is an **evidence DAG** (not a chain); leaf = verbatim span certifying
  *faithfulness not interpretation*; interior composes **by reference**.
- §4 — **`evidence_tier` DISSOLVED** into four separable things: *interpretive distance*,
  *reliability*, *probativeness* (all support-EDGE properties, multiple per assertion,
  assessment-relative, cross-artifact) + *contestation* (a GRAPH-SHAPE property, not an
  edge label). An assertion has **no single stored strength** — it's recomputed per
  assessment.
- §5 — **assessment is the central act/artifact**: assembles a sub-DAG, records
  branch-termination/assumption choices, applies non-procedural judgment, is
  **decision-relative** (decision statement OPTIONAL). Both consumer of AND node in the
  DAG. Includes the **depth-of-diligence ladder** (literature import = its rungs; a
  citation = rung 1 = span-correctness + integrity granted + branch terminated).
- §6 — **re-assessment engine**: the trigger that drives members back into the DAG =
  *new decision + stakes not met by an old assessment over an evidence base that has
  since grown* (staleness + new evidence + higher stakes). Resolves the old "what drives
  challenge?" hole.
- §7 — **this is NOT a single knowledge graph**: a pathway/hypothesis is a *model derived
  for a purpose*; the community publishes assertions+assessments, consumers project
  models from them. Formal/freeform equally first-class follows from this.
- §8 — cross-group warrant (carried from prior draft, **still needs rewiring** to spine).
- Appendix A — source map. Appendix B — open-question index w/ RESOLVED markers.

### Key results already locked in (don't relitigate without cause)

1. **Publishing is itself a judgment** → "all artifacts are judgments." (Dexter's move;
   subsumed the old "is the atom assertion or (assertion,judge)?" debate.)
2. **DAG, not chain.** (Dexter.)
3. **Regress terminates economically, not epistemically** — via *recorded* assumptions:
   "assume true & proceed" / "abandon branch" / "**adopt a prior assessment**". (Dexter.)
4. **Two trust factors, gate-then-gradient:** integrity (about the source, granted first,
   scoped out) THEN interpretive distance (about the support, graded).
5. **Fact/claim knife = interpretive distance, NOT observability; orthogonal to scope.**
   *Everything is interpretation of measurements*; procedural/behavioral reports are
   near-zero distance (only integrity needed); scientific claims ("A phosphorylates B")
   are a different *order* of distance. Sub-split: "paper says they did E" (span-
   faithfulness, checkable) vs. "they really did E" (integrity, assumed).
6. **`evidence_tier` dissolved** into interpretive distance / reliability / probativeness
   / contestation. Reliability ≠ interpretive distance (a close test can be unreliable).
   Probativeness = how much a falsification result bears on the claim, discounted by
   whether the test's enabling assumptions hold in this case. Contestation = graph shape.
   **Replacement representation NOT yet designed** (Appendix B 4.A — next modeling task).
7. **Trust is decision-relative.** The axes do NOT combine into a context-free scalar;
   they're assembled & weighed per assessment, relative to a decision's stakes.
8. **Depth-of-diligence ladder** for literature import (rungs 1-4: span-only → methods →
   re-run analysis → trace cited support). Citation = cheapest legal assessment, with
   depth RECORDED (unlike DOI citations which hide depth).
9. **Re-assessment engine** = staleness + new evidence + new decision-stakes.

## ACTIVE THREAD — artifact types (in progress, NOT yet written into the doc)

We are deriving the artifact-type set from the §1–§5 principles (not just listing).
**Agreed cuts:**

- **Analysis = (recorded procedure + emitted derived data), interpretation EXCLUDED.**
  An analysis emits derived data, *that's all*. The moment a claim is drawn from data,
  that's an **assessment** edge, not part of the analysis. (Dexter confirmed.)
- **Imported vs. derived data is AUTHORSHIP/PROVENANCE, not type.** Same node type;
  provenance edge = `imported-from` (external leaf) or `authored-by`/`derived-by`
  (member/interior). Some papers give only derived data (raw unavailable/impractical) —
  so we import derived data too. (Dexter confirmed.)
  - **Ripple (Claude proposed, awaiting confirm):** "import proxies" was never a *type* —
    it's a *provenance state* that EVERY artifact carries (assessments, hypotheses too).
    So drop "import proxies" as a type; add a universal provenance axis.
- **Hypothesis = top-level type.** Justified by *rich formal structure*: claims, null,
  alternates, free-text rationale. **It is a MODEL, not a single assertion.** Stands
  *separate* from assessments on it. (Dexter confirmed.)
  - **Sharpening (Claude proposed):** what makes it a model not a compound assertion =
    null/alternates are *mutually exclusive candidate explanations*; assessment-of-a-
    hypothesis is **adjudication AMONG alternates**, not a single trust verdict → implies
    assessments are non-uniform (claim-assessment vs. hypothesis-assessment differ).

**Proposed derived type set (NOT yet in doc):**

| Type | Distinguishing principle | DAG role |
|---|---|---|
| Source document | span-anchorable external text | leaf (text-ground) |
| Dataset | computable measurement data | leaf (data-ground) OR interior (if derived) |
| Analysis | recorded procedure that emits derived data — nothing more | interior; emits a Dataset |
| Hypothesis | structured model of *competing* explanations (null/alternates) | proposed model; assessed by adjudication |
| Assessment | judgment over a sub-DAG; for hypotheses, adjudication among alternates | interior; consumer & node |

Plus two **cross-cutting properties (NOT types):**
- **Provenance:** `imported-from` (external) vs. `authored-by` (member).
- **Leaf-grounding:** text-span OR data-locator.

### OPEN — the two questions on the table when Dexter stepped away

- **Q1 (likely yes):** The "gene A is the 5th-most-significant DEG in derived table T"
  object = a **dataset-locator-grounded assertion** = the *data-side twin of the verbatim
  span* (faithfulness-checkable, integrity-gated, near-zero distance). Claude proposes it
  is NOT a new type — it generalizes §3's leaf to **two flavors of faithful pointer:
  text-span (into a document) and data-locator (into a dataset).** Awaiting Dexter's
  confirm.
- **Q2 (Claude leans "keep separate"):** Source-document vs. Dataset — two leaf types, or
  one "external source" type with text/data sub-distinction? Claude leans keep-separate
  (grounding mechanism differs: span vs. locator; span machinery is text-specific). Same
  question as: is leaf-grounding ONE mechanism with two flavors, or TWO mechanisms?
  Awaiting Dexter.

## NEXT STEPS (Dexter to choose on return)

1. Answer Q1 / Q2 above → then write the artifact-types section into the doc.
2. Design the §4.A replacement representation for dissolved `evidence_tier`.
3. Rewire §8 (cross-group warrant) to the new spine; address DEBATE 6.A (does re-
   assessment guarantee cross-group *encounter*, or only *enable* it?).
4. DEBATE 7.A — how forcefully to own that "the reader does the integration" leans on
   consuming-agent capability.

## Related files

- Main doc: [core-architecture.md](core-architecture.md)
- Integrated review that kicked this off: [../design-notes/trust-architecture-review.md](../design-notes/trust-architecture-review.md)
  (Dexter said reading its preview removed the need for the PDF; ok to delete on request.)
- Upstream sources: [00-trust-thesis](requirements/00-trust-thesis.md),
  [05-evidence-and-provenance](requirements/05-evidence-and-provenance.md),
  [07-judgment-and-trust-tracking](requirements/07-judgment-and-trust-tracking.md),
  [inter-artifact-standard](inter-artifact-standard.md),
  [../design-notes/completeness-as-defensible-standard.md](../design-notes/completeness-as-defensible-standard.md),
  [../design-notes/formal-and-freeform.md](../design-notes/formal-and-freeform.md),
  [../design-notes/trust-not-capability.md](../design-notes/trust-not-capability.md)
