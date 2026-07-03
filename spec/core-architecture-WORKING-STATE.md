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

## NEW WORKSTREAM (2026-06-21→22) — the "annotated precursor" doc

We pivoted to writing an **annotated precursor** to the paper's *framework* section:
[framework-precursor.md](framework-precursor.md). Separate from implementation (NOT
artifacts-as-knowledge-graphs). Structure = **interleaved Pass A (abstract, no domain
vocab) / Pass B (grounded in representational + assessment choices)**, section by section,
so the abstract/grounded boundary can be judged in place. Pass A may incur *debts* that the
following Pass B pays.

**Register rules locked** (in the doc's "Register and vocabulary rules" block — enforce
while drafting):
- 3 registers kept apart: scientific-method / trust / **content (object-relationship-
  property, held BELOW & introduced AFTER the trust layer)**.
- **Rule 2:** inoculate against binary belief UP FRONT (Preamble before §1) — trust graded,
  evidence *increases/decreases* trust, never proves.
- **Rule 3:** Symposium NAMES axes, does NOT grade them numerically. No scoring scale.
  Rubrics are an assessor's projection (like adopting BEL). Covers interpretive distance +
  reliability + probativeness + contestation in one move.
- **Rule 4 quarantine:** banned — load-bearing, node/edge, DAG/leaf/interior, gate-then-
  gradient. Use: "converging lines of evidence," "support relationship/link," "checkable
  ground"/"terminating ground," "assertion/assessment/artifact." One parenthetical "(formally
  a DAG)" allowed once for the architect.
- Keep: interpretive distance, probativeness, addressability (coined; define on first use),
  grounding.

**Sections DRAFTED in precursor (A+B each):** Preamble (+ early scope note: paper is about
trust in agent communities; non-trust-bearing artifacts exist, refer-but-never-enter-
evidence, named in artifact-types §), §1 (assertion atom + publishing-is-judgment + paper
anatomy + "any reasonable reader" bar + paper=self-assessment carry-forward), §2 (integrity
scoped out; cooperative-by-assumption; integrity re-enters as recorded non-grounding), §3
(grounding: two-part headline; two flavors of faithful pointer text/data; three production
choices; interior by-reference), §4 (dissolve evidence_tier → 4 named properties; legacy-
label teardown; self-vs-independent changes how reliability/probativeness judged), §5
(assessment central act; 3 termination choices; depth-of-diligence ladder bound to §2's 3
practice tiers; self-vs-independent assessment; trust-bearing-vs-rationale distinction +
decision-to-act vs outcome cut; decision-relativity + optional decision statement), **§6**
(re-assessment engine = staleness+new-evidence+higher-stakes; decision HORIZON w/ Venn
"how-wide-and-around-whom you draw the circle" metaphor; siloed reviewer = high diligence,
wrongly-PLACED horizon; silo DETECTED by differently-sensitive reader, NOT self-named),
**§7** (commons = substrate not single graph; models = projections; formal/freeform first-
class; PUBLICATION BOUNDARY = framework governs publication ONLY, private interior free,
lab-notebook analogy; §7.A honesty: consumer capability instrumented-not-assumed;
discovery/encounter rests here).

**§1–§7 SPINE COMPLETE (interleaved A/B).** **§8 artifact-types DRAFTED (single pass, no
A/B — partition first):** 8.1 trust-bearing/non-trust-bearing partition; 8.2 trust-bearing
types (Source material, **Data** [not "Dataset"], Analysis, Hypothesis, Assessment); 8.3
cross-cutting properties (provenance, leaf-grounding flavor); 8.4 reuse-driven reification/
separation spectrum. Remaining: conformance/precision section (see NEXT).

**TWO NEW STRUCTURAL RESULTS from §8 (back-port to core-architecture.md):**
- **Non-trust-bearing signature = in-edges allowed, evidence-out-edges forbidden.** Support
  flows INTO a recommendation (it cites datasets/sources/assessments), never OUT of it as
  evidence. "Never a node another assessment grounds on." Recommendation FIXED as definitely
  non-trust-bearing. It can be DISCOVERED, not cited-as-evidence. Qualifies/cautions about
  trust-bearing results without being part of them (expert-agent bundle example: analysis +
  data + assessment + qualifying recommendation, straddling the partition).
- **Hypothesis (incl. PREDICTION) = a PROPOSAL, NOT trust-bearing until assessed.** Becomes
  trust-bearing only when an ASSESSMENT addresses its claims; an assessment may SUBSUME a
  hypothesis (claims drawn inside, grounding makes them trust-bearing). Corrects earlier
  neutral "hypothesis is a model" framing. This dissolves 8·A: implicit prediction in a
  recommendation is a hypothesis → not evidence until separately assessed.
- **`data` is the type; `dataset`/`gel image`/etc. are CHARACTERIZATIONS of data;** sub-
  taxonomy LEFT OPEN to refine with system mileage (Rule-3-style restraint).

**Key NEW results locked in the precursor (back-port to core-architecture.md later):**
- **2·B-ii RESOLVED:** integrity-assumption floor = a **deliberate non-grounding** (recorded
  decision to stop short of ground), NOT a 2nd kind of ground. Stated LOUDLY as the
  fidelity-to-practice argument: real communities run on reputation/critical-reading
  terminations; full reanalysis is rare. Grounding headline = "checkable ground OR a recorded
  choice to stop short of it" — never "checkable ground" alone.
- **1·B-i RESOLVED:** data-only artifact carries the **faithfulness voucher** (vs.
  interpretive voucher); "every artifact is a judgment" spans both.
- **"Any reasonable reader in target audience" bar** = the stop-rule for declaration depth;
  NOT total declaration (matter-is-atoms floor). "Target audience" = decision-class =
  **decision horizon** (→ §6). Now a recurring named principle (give it its own index row).
- **Paper = self-assessment** (own claims, own newly-produced data). Import fork: *formalize
  their self-assessment* vs. *perform independent assessment* (= deeper rungs + your own
  substituted evidence). Recorded depth lets a reader tell translation from independent
  confirmation — citations erase this.
- **Two flavors of faithful pointer:** text-span (checkable BY VALUE, carried) vs.
  data-locator (checkable BY REFERENCE, inherits dataset-identity gap → pushes old 3.A
  identity gap DOWN into the ground layer).

**RESOLVED in §6/§7 (this session):**
- **5·B-i RESOLVED (§6):** formalization records at the AUTHOR'S bar but MARKS, as inherited
  *unexamined* assumptions, the tacit moves a WIDER horizon would not grant. Surfaces-as-
  placeholders, not adjudicates (adjudication = independent assessment). By whose bar? The
  formalizer's — used to FIND assumptions worth marking, not to JUDGE them.
- **old 6.A RESOLVED (§6):** re-assessment + recorded horizon make cross-group catch
  POSSIBLE, do NOT schedule it. Necessary-not-sufficient, stated as such.
- **7·B-ii RESOLVED (§7):** discovery = IN the paper, OUTSIDE trust machinery. Brief body
  treatment + implemented mechanisms in supplemental methods (w/ agent prompts). Discovery-
  mechanism studies = other-paper work (like agent design). ALL artifacts are discovery
  vehicles (all indexed); non-trust-bearing reviews/recommendations are a *distinctive*
  vehicle, not the only one (cf. findings-paper + journal both do discovery in current
  practice).
- **Siloed-priors framing CORRECTED:** silo is DETECTED by a differently-sensitive reader
  (recognizes a gap their priors make them see), NOT self-named (can't name what you don't
  recognize). Record exposes the SHAPE of what was/wasn't done.

**NEW open questions opened in precursor (still OPEN):**
- **6·B-i:** detection still needs a differently-positioned reader to ENCOUNTER the work.
  Old 6.A gap relocated, not closed: "blind spot invisible" → "detectable blind spot goes
  undetected, no out-of-silo reader encounters it." Discovery/encounter = first-class problem
  (→ handled per 7·B-ii). Also where GENERATIVE cross-silo value lives.
- **7·B-i:** how hard to lean on consuming-agent capability — specify a MINIMUM consumer
  capability, or leave unspecified to avoid coupling epistemics to an agent class?
- **GENERATIVE cross-silo (NEW, from Dexter):** same legibility that catches errors discovers
  SYNERGIES — adjacent-silo reuse up to INTEGRATIVE HYPOTHESES (multi-virus host mechanisms,
  more complex than shared interactors). Strong USER motivation (loosely-collaborating labs),
  NOT *the* foundation. Shares 6·B-i's unsolved half (enables, doesn't schedule encounter).
- **Reified-human-agents (NEW, from Dexter, NOT yet written):** humans reified as community
  agents; their assistants help them conform; artifacts include published AND unpublished-but-
  shared work. Expands WHO is in the commons / WHAT circulates. May want own treatment. Park
  until placed.
- **Dataset-separation (NEW, 2026-06-22, from Dexter):** literature import should cleanly
  SEPARATE the reusable dataset (+ assessment of its production methods) from the authors'
  specific self-assessment uses of it. Most downstream agents want only the dataset; don't
  conflate it with the authors' validated hypotheses. → write into §5/artifact-types.
- **Rationale-is-valuable-not-trust-bearing (NEW, 2026-06-22, from Dexter):** explanation
  behind a choice (e.g. "I used Wilcoxon not t-test because I suspect non-normal
  distribution") is VALUABLE but NOT trust-bearing; the analysis stands apart from the
  agent's motivation. If the agent actually ran a distribution analysis to justify it, that
  raises trust in the DECISION TO ACT, not in the analysis OUTCOME. Such a sub-analysis is at
  the "nth-most-significant-gene" level — reifying it as a separate artifact is a POOR CHOICE
  but NOT an error. → write into §4/§5.

**NEXT in precursor:** §1–§8 DONE. Now the LAST planned section:
- **§9 Conformance/precision section** — TWO-TIER conformance (Tier 1 procedural
  addressability floor checked pre-publish; Tier 2 rubric + assessor judgment, editors-not-
  validators governance) + precision ⟂ addressability + BEL > precise-prose > lossy-KG
  ordering (enemy = information loss; coarse controlled vocab worse than prose) + "use vocab
  where it carries meaning, depart where it can't" + AKT/AKT1 imprecision = trust concern
  weighted by how critical the term is. Single pass likely (grounded section, like §8).
Then DONE with first full draft. Pending after: back-port ALL resolutions to
core-architecture.md (still has 2.B etc. OPEN); place reified-human-agents point; build
consolidated open-question index for the precursor; decide if precursor supersedes
core-architecture.md or they merge.

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
