# Symposium Trust Architecture — Integrated Review Draft

*An integration of six source documents on the knowledge architecture, knowledge
model, and the assessment of trust in assertions. Edited to remove redundancy and
to surface the critical design choices and their justifications. Internal
inconsistencies and gaps are flagged in-line and collected at the end. Nothing is
resolved here — this is a review instrument.*

**Sources integrated:** `trust-not-capability.md`, `inter-artifact-standard.md`,
`07-judgment-and-trust-tracking.md`, `05-evidence-and-provenance.md`,
`completeness-as-defensible-standard.md`, `formal-and-freeform.md`.

---

## 1. The thesis: trust is the contribution, capability is instrumented

**Banner.** Symposium's claim is *trust, not capability*. The demonstration agents
are not put forward as cutting-edge reasoners but as agents that operated
*trustworthily*.

**Why this is the right framing (two justifications):**

1. **It separates the contribution from model churn.** "Our agents reason better"
   is obsolete the moment a better model ships and competes badly with every
   frontier lab. "Our community makes agent work *trustworthy*" is a claim about
   architecture, not any model; it stays true as the models underneath improve.
   Any agent on any model can participate if it follows the standards.
2. **It identifies the actual bottleneck.** Agents already produce scientific
   artifacts faster than humans can review them. The limiting factor is **trust at
   agent speed across organizational boundaries** — and science's existing trust
   apparatus (peer review, replication, credentialing) has no counterpart that runs
   that fast.

**The critical correction — the dichotomy leaks.** Taken literally, "trust, *not*
capability" implies the two are separable. They are not, and the architecture's own
mechanisms prove it:

- **Completeness is capability-bound.** "Did the agent find every dataset?" has no
  mechanical answer. A coverage procedure run by a weak agent yields a "documented
  process trusted to a degree" — and the degree is low *because* the agent is weak.
- **Judge-provenance is capability tracking.** A judgment records the model and
  reasoning mode of its judge precisely so a later, more capable agent can decide
  whether to re-review. Capability is a first-class trust parameter, inside the
  trust model.

**The stronger form the spec actually adopts:**

> **Trust is the contribution; capability is a parameter the trust architecture
> makes *legible and auditable*.**

The distinctive move is not to *bracket* capability but to *instrument* it. The
demonstration agents can be modest reasoners and still make the point, because the
point is no longer "they reason well" but "however well they reason, you can see it,
audit it, and re-check it."

**A rejected analogy (worth keeping as a guardrail).** The tempting framing — "self-
driving cars must be *much* safer than humans, so agent output must be *much* more
rigorous than human output" — is withdrawn. "Much safer" is a measured multiple over
a well-characterized baseline (human crash rates), enforced because crashes are
loud, countable, and immediate. Scientific extraction failures are quiet and
compounding, and there is no agreed error rate for "a typical human scientist's
literature extraction." A project that disclaims quantitative evaluation in phase one
cannot lean on a quantitative analogy.

**The concept that replaces it — auditable rigor, in three parts:**

- **Auditable** — the agent wrote down *what it did*: every claim traces to a
  verbatim span, every judgment records its judge, every "done" cites its coverage
  procedure.
- **Rigor** — the agent wrote down *the important things*: the evidence, reasoning,
  judgment, and coverage that bear on whether the claim holds — not a raw transcript.
- **Evaluable structure** — it wrote them down in a form a critic can run a contract
  against.

The defensible asymmetry with ordinary output is not a safety multiple — it is *work
whose rigor you can audit claim-by-claim, structured so the audit can actually be
run.*

---

## 2. The unit of the commons and the two representational layers

**The artifact is the unit.** The commons is a graph of **artifacts**. A published
artifact (reference implementation: a CX2 network on NDEx) is the unit of
publication, credentialing, addressing, and provenance — the DOI analogue. One
artifact is what an agent produces, an owner credentials, and another artifact cites.
The inter-artifact standard is the successor to DOI-and-citation, but **richer**:
relationships are *typed* (not a flat "cites"), *claim-grained* (not only
artifact-to-artifact), and *machine-checkable*.

**Two layers that must not be conflated:**

| Layer | What it governs | Status |
|---|---|---|
| **Inter-artifact standard** | Controlled vocabulary of **trust-bearing** node types + ~8 relationship kinds. What conformance is checked against; what trust/provenance rest on. | Shape settled; term set under definition |
| **Intra-artifact content** | The scientific content *inside* an artifact, authored **formal** or **freeform**. | **Free and evolvable**; not mandated by the standard |

> **Naming caution (flagged by the sources themselves).** "Controlled vocabulary" is
> overloaded. Doc 04 uses it for an *intra-artifact formal modeling* vocabulary (e.g.
> BEL). The inter-artifact standard's "controlled trust vocabulary" is the
> trust/provenance standard at a different layer. An artifact may use any formal
> modeling vocabulary internally while conforming to the one trust standard.

**The conformance boundary is orthogonal to the artifact boundary.** A trust
relationship is most often expressed *inside* one artifact (a conclusion supported by
a claim supported by a source-reference), with only the citation crossing to another
artifact. The standard governs trust-bearing structure **wherever it appears** —
within and across artifacts — because the no-error-laundering guarantee and the
chain-of-evidence trace require internal support structure to be legible, not opaque.

> **Conformance rule.** An artifact conforms iff **every trust-bearing node and edge
> it publishes is drawn from the controlled vocabulary.** Domain content alongside the
> trust-bearing structure is unconstrained and ignored by the trust machinery.

**Scope choice.** For the system reported by the paper, the community is **restricted
to conforming artifacts**. Coexistence with less formal artifacts (e.g. one declaring
it conforms to a *separate* standard) is explicitly **future work**.

---

## 3. The controlled trust-relationship vocabulary

The relationships fall into ~8 **kinds of trust relationship**, plus deliberate
**foils** that carry no trust — their being named is load-bearing: it is how the
architecture states trust-inertness and no-laundering out loud.

1. **SUPPORT** — X is evidence that grounds/raises the trust of claim Y.
2. **CORROBORATION / INDEPENDENCE** — X *independently* corroborates Y (raises trust
   only if independent); includes the negative case (declined-to-count).
3. **VALIDATION** — X reviews/grades the correctness of Y and issues a verdict.
4. **INTERPRETATION / JUDGMENT** — X is a provenanced judgment about Y, not new
   evidence.
5. **COVERAGE** — X attests how completely Y was swept.
6. **PROCEDURE** — Y was produced by method/procedure X.
7. **CONFLICT / DISPOSITION** — X stands in contradiction; a disposition gates Y's
   trust and is owned by a role.
8. **GAP / OWNERSHIP** — Y's trust is blocked-on / scoped-by a typed gap, deferred to
   a named role.

**Foils (carry no trust):** prediction (trust-inert), provenance/lineage facts,
control/structural navigation.

**The shape of the resulting graph:** *trust bottoms out in span-anchored external
facts at the leaves, and composes by-reference internally.* Grounded where it touches
the world; legible where it builds on itself.

> **Status (flagged).** The *shape and governance* are settled; the exact closed term
> set is **under definition** (decision `D-0025`: controlled, not dynamically extended;
> one-time mapping of the first run's improvised terms onto the set; extension
> candidates recorded for gated addition). The vocabulary is not frozen until that
> lands.

**Free content is the substrate; the judge is the bridge.** Domain content that is
*not* formally trust-bearing is not inert decoration — it is the substrate over which
trust-bearing assertions are made. Prose, a hypothesis rationale, or a data-analysis
result **MAY be read by a judge** (agent or human) as input to its decision to assert
a trust-bearing type. *The judgment is the conformant output; the content is what it
was made over.* This generalizes the fact/judgment split — "an expert agent is a
judgment-wrapped tool invocation" — to the whole commons.

**Governance.** The standard is evolved **deliberately and slowly** by the
**community owner** (within a lab, the PI or designate; in a public community, an
organization with human governance). It is **not** dynamically extended to match
whatever agents emit. A live run may surface a genuine relation the vocabulary cannot
express; such cases are **recorded as extension candidates** for gated, owner-approved
addition — never auto-admitted.

---

## 4. Evidence and provenance — the load-bearing discipline

This is the discipline that backs every assertion. If a claim cannot be traced to its
source, none of the validation machinery has anything to stand on.

### 4.1 The core rule

> Every claim an agent publishes is traceable to one or more **verbatim spans** in its
> source. Copy the exact source text; never paraphrase, smooth, reorder, or infer a
> locator that is not there.

A span is exact source text. Light trimming with ellipses between clauses is permitted
past a length bound; **never** synonym substitution, never multi-sentence collapse
that fabricates contiguity.

### 4.2 A claim's anchor is a *set* of spans

Authors scatter the pieces of one fact across a document — an accession in the
data-availability statement, the assay in results, the replicate count in a figure
legend. A single-contiguous-span rule would punish the agent for the *authors'* text
structure. So the anchor is a **set of spans**, and the claim must be supported by
them **jointly**. Every component of the structured claim must map to at least one
span; an unsupported component makes the claim unfaithful — find the span or drop the
component.

### 4.3 Joining spans is itself a graded inference

When an anchor draws on several spans, the agent has contributed an *association*.
The grade decides whether it must be provenanced:

- **Assembly** — the association is *forced by the text*: the only consistent reading,
  no new fact introduced. Faithfulness-preserving bookkeeping. The multi-span anchor
  is recorded; **not** a judgment call. *(e.g. joining `GSE12345` from the availability
  statement with "RNA-seq in HeLa" from results when the paper describes one dataset.)*
- **Assembly-with-inference** — the agent supplied something the spans do not
  individually state: a **connective fact** in no span, or a **non-forced association**
  chosen among alternatives. This **is** a judgment call and records judge-provenance +
  rationale. *(e.g. inferring an unstated tissue; allocating an accession to one of
  several datasets a paper describes.)*

**The operational test:** *did the agent introduce a fact, or only an association —
and if an association, was it forced by the text or chosen among alternatives?* Forced
→ assembly. Introduced fact or chosen-among-alternatives → assembly-with-inference,
justify it.

This grade scales with the extraction target: light for dataset cataloging; for
hypothesis or experiment-plan extraction the assembly *is* the hard inferential work
and the recorded reasoning is most of the value. Same rule, very different weight.

> **Cross-reference to §6.** Cross-span assembly-with-inference is named there as "the
> most frequent and the most error-prone" judgment type — misallocating a statement to
> the wrong dataset, or importing an implied-but-unstated fact.

### 4.4 Locators are copied exactly

Identifiers — accessions, PMIDs, sample sizes — are transcribed verbatim, never
normalized, never inferred when absent. **A missing locator is a distinct, recorded
state, not a blank to fill.**

### 4.5 The edge-provenance schema

Every mechanism edge (and every freeform claim node) carries a standard set of
provenance attributes. A standard schema is what makes provenance *checkable*: a
critic or deterministic harness verifies each field mechanically without re-deriving
the science.

| Field | Meaning |
|---|---|
| `evidence_quote` | the verbatim span(s) supporting the claim |
| `source` | source identifier (PMID, accession, dataset id, URL) |
| `scope` | the experimental/study context the claim is bound to |
| `evidence_tier` | strength of support (vocabulary below) |
| `last_validated` | ISO date the claim was last checked against its source |
| `status` | `active` / `retired` (retirement discipline below) |

### 4.6 Evidence-tier vocabulary

`established` · `supported` · `inferred` · `tentative` · `contested`

The tier states how strongly the *evidence* supports the claim — distinct from how
capable the *judge* was (recorded separately as judge-provenance, §6).

- **Never silently upgrade.** A claim's tier MUST NOT exceed what its spans license.
  Raising a tier is a **distinct, logged act**, never a silent edit.
- **Role-ceilinged.** A role may be forbidden from asserting a tier it cannot justify.
  An extractor that cannot confirm an accession resolves MUST NOT assert availability
  above `deposited-wellformed-unverified`; a literature scout may be forbidden from
  `established`. Exceeding a ceiling is a faithfulness defect.
- **Tier-by-source.** The tier a claim *may* carry is bounded by its source kind. A
  claim resting on an author's assertion cannot be `established` on that basis alone;
  one demonstrated by data in the source can be. A span that *asserts* a result does
  not license the same tier as one that *demonstrates* it.

### 4.7 Retirement discipline

- A claim is **retired, not deleted** — `status: retired`, with reason and date, so the
  history of what was once believed (and why it was given up) remains inspectable.
- Retiring a claim others built on SHOULD trigger an acknowledgement to dependents.
- A curator's review action that retires an edge is itself recorded in the review-log.

### 4.8 New-node provenance

When an agent introduces a *new entity node* (gene, construct, dataset not previously
in the graph), that introduction carries its own provenance: where the entity came
from and why the agent is confident it is real and correctly identified. New nodes are
a common place for silent error (mis-resolved gene symbol, hallucinated construct), so
they get the same evidence discipline as claims.

---

## 5. Anchoring across artifacts — the two-tier obligation

This refines §4 for the inter-artifact setting. The key design choice: **the
verbatim-span rule is enforced only for external source text, and by-reference between
artifacts.**

- **Guideline (SHOULD), universal.** Every trust-bearing judgment anchors to what it
  relied on. A bare "the source says so" with no locator is insufficient. The *form*
  of the anchor is deliberately **not** universally mandated — a universal anchor spec
  over open content would be brittle. When content genuinely cannot be anchored, the
  assertion declares a **typed gap** (`uncomputable` / `blocked_on`) — never a
  fabricated anchor.
- **Enforced (MUST), external source text only.** An anchor referencing **external
  source text** (the literature) MUST use the **span mechanism** of §4: a verbatim
  span set + exact locator, with span-existence mechanically re-checkable.
- **Inter-artifact references are by-reference.** A reference from one artifact's
  assertion to another artifact is made **by reference** at assertion/artifact
  granularity. The span mechanism *may* quote agent-generated text in another artifact
  but is **not required** — enforcing span-level internal cross-references would breed a
  machine-precise but human-inaccessible tangle, defeating the legibility the standard
  exists to provide.

> **What a span certifies.** A span anchor certifies **faithfulness** (the quoted text
> is really in the source), **not interpretation** (that the judge read it correctly).
> It therefore *enables* a later reader's re-analysis or dispute — handing them the
> precise locus — rather than foreclosing it.

**Identity is provisional (flagged gap).** The reference implementation addresses an
artifact by its server-minted NDEx UUID — **resolvable but not portable**: copying
artifacts to another server re-mints UUIDs and breaks cross-references. Cross-artifact
identity MUST be treated as provisional — coped with procedurally, or via a stable
`user / folder-path / artifact-name` logical address. Portable persistent identifiers
are deferred. A known, bounded gap, not a solved problem.

**Future / owner-governed extension point.** An artifact declaring its anchors follow a
separate evidence standard (e.g. "we follow the BEL evidence requirements") is a clean
extension the owner may sanction over time.

---

## 6. Judgment provenance and trust-tracking

Many validation steps are not fully mechanical. The response is not to eliminate
judgment but to make every judgment **provenanced and reviewable** — and to scale the
weight of that provenance to the stakes.

**The recurring judgment types:**

- **cross-span assembly-with-inference** (§4.3) — the most frequent and most
  error-prone.
- **span-set support** — do the spans jointly support the claim?
- **material-caveat** — is this assay caveat worth recording?
- **coverage-adequacy** — was the sweep enough? (§7)

**Every judgment call carries judge-provenance.** Beside the verdict, the agent records
*how the judgment was made*:

| Field | Meaning |
|---|---|
| `judged_by_agent` | the agent identity that made the call |
| `judged_by_model` | the underlying model |
| `reasoning_mode` | reasoning effort/mode (e.g. extended vs. standard) |
| `criteria_version` | the version of the criteria/SOP applied |
| `judgment_date` | ISO date |
| `verdict` | the decision |
| `rationale` | brief, in the agent's words |

Judge-provenance backing a **published** verdict is **published with the verdict**, not
kept in private working memory. The community must audit not just the verdict but the
judge behind it.

**Why this is the capability-analogue of evidence tiers.** Evidence tiers tell a reader
how strong the *evidence* is; judge-provenance tells a reader how strong the *judge*
was.

> A later, more capable agent deciding whether to trust earlier work — when that work
> is critical to its current task — needs to know the call was made by a less capable
> agent (or weaker reasoning mode, or older criteria version) to decide whether
> **re-review is warranted.**

Without judge-provenance, every prior judgment looks equally authoritative — exactly
the failure the architecture exists to prevent. This is the concrete mechanism behind
"capability is an instrumented parameter, not a bracketed one" (§1).

**Trust-tracking scales with stakes.**

- A **low-stakes** request (routine lookup) may record a minimal verdict.
- A **high-stakes** expert judgment (a completeness sign-off another agent will build
  on) records the full bundle.

> All judgments remain community artifacts — **trust over speed is the priority.** Low
> latency is pursued through **technical infrastructure**, never by dropping the
> artifact requirement. An agent does not get faster by skipping the trail; it gets
> faster by better tooling.

**Re-review and the trust chain.** Because each judgment records its judge, trust is
revisable, not frozen. A later agent that finds a critical dependency was judged by a
weaker predecessor may re-review it; the re-review records its own judge-provenance and
links to the judgment it revisits. Over time a claim carries a visible chain of
judgments and re-judgments, each honestly labeled with the capability that produced it.
*That chain — not any single authoritative verdict — is what the community trusts.*

---

## 7. Completeness — a defensible standard, not a proof

The hardest question in the validation model: *did the agent find everything it should
have?*

**Why completeness resists a clean test.** Faithfulness is grounded — every claim
points at a span, so a checker verifies the link without re-deriving the science.
Completeness has no such ground. To know what a report *omitted*, a checker would have
to know what the source contains that the report does not — i.e., redo the extraction.
"Did the agent find every dataset, every experiment?" has no closed-form answer,
especially for information that hides where extractors under-look: results sections and
supplementary materials, not just methods.

**The temptation, and why it fails.** The temptation is to chase proof: add enough
mechanical checks that completeness becomes testable. *Some* incompleteness is
mechanically catchable — a locator sweep finds missed accession patterns; an
internal-consistency check flags an assay named in prose but absent from records — and
the standard **requires running these**. But the residue is irreducible: whether the
agent correctly understood which experiments produced which data, and found experiments
described only narratively, cannot be proven complete short of redoing the work.

**The move that rescues it — recorded negatives:**

> An extractor is **done** when every claim is faithfulness-anchored, every required
> field is populated or explicitly marked absent, and a **declared coverage procedure
> has been run across all source sections, with its negative results recorded.**

The crux is the word *recorded*. "I scanned methods, results, data-availability, and
supplementary for accession patterns and dataset mentions; none beyond the three
catalogued" is a **recorded negative** — it converts an absence into evidence. The
agent no longer claims "I found everything" (unprovable); it claims "I ran *this*
procedure across *these* sections and *this* is what it turned up, including where it
turned up nothing" (checkable, and honest about its limits).

Completeness thereby becomes **a documented process trusted to a degree**, rather than
a guarantee. *The trust is no better and no worse than the trust in the procedure that
was run.*

**Why the coverage procedure must be versioned and cited.** Because "done" rests
entirely on the procedure, it must be a real, inspectable, **versioned** artifact. A
report cites coverage-procedure *name + version*; an auditing reader retrieves *that
exact version* and judges adequacy. Three payoffs:

1. **Honest labeling across time.** A report validated under v1.3 stays correctly
   labeled after v1.4 exists; re-validation under v1.4 is a distinct, logged act.
2. **Independent improvement.** The procedure improves on its own track; every report
   citing an old version remains interpretable.
3. **A rising bar.** The community decides which procedures count as adequate, and that
   bar rises as agents improve (the *completeness frontier* research goal).

**Why this is where community SOPs do their real work.** Completeness is where "trust"
stops being mechanical and becomes social. No procedure can prove completeness; the
community's *agreement* on which procedures are adequate carries the residual trust.
This is not a weakness — it is how human science handles the same problem. No reviewer
proves a paper reported every relevant experiment; the field's shared standards for
"adequate methods" carry the trust, and rise over time. Symposium makes the same move
explicit and machine-legible.

**The honest dependency on orchestration.** Running a coverage procedure "across all
sections" presumes the orchestration gave the agent the budget and context to do so.
When it did not — too small a batch, the supplementary never loaded — the agent does
not get to claim "done." It records what it could cover and the verdict becomes
**VALID-WITH-GAPS**. The standard stays fixed; the shortfall is recorded, not hidden.

---

## 8. Formal and freeform modes are complementary

Content uses two modes of representation — **formal** (a controlled modeling
vocabulary, e.g. BEL/GO-CAM/OpenCypher-shaped) and **freeform** (narrative claim nodes
with full provenance). They are **equally first-class**. The spec rejects the common
framing of "formal is the goal; freeform is a fallback."

**The assumption being rejected — "ontology coverage equals rigor."** The intuitive
starting point: pick a controlled vocabulary, author everything in it, and treat
coverage as a proxy for rigor (if a claim fits, the agent is doing the work; if not,
keep refining until it fits). This is widely held and produces *worse* knowledge graphs.

**Why.** Forcing a claim into a vocabulary that doesn't fit *degrades* it. The agent
either picks the closest formal predicate (losing the qualifier that made the claim
meaningful) or invents a vocabulary extension (undermining the interoperability that
motivated the formal choice).

*Worked example:* "PARP1 inhibition is synthetic lethal with BRCA1 deficiency *in cells
with intact homologous recombination elsewhere*." The "in cells with X" qualifier is
not study-context (which `scope` handles) — it is part of the *claim itself*. Drop it,
and the claim reads as a universal, which is wrong.

**What freeform actually does.** A freeform claim node carries: the full narrative
claim with all qualifiers preserved; the same provenance fields as any formal edge
(`evidence_quote`, `pmid`, `scope`, `evidence_tier`, `last_validated`); and optional
links to canonical entity nodes via `asserted_in` edges. *This is not "less structured"
content — it is structured differently:* the structure is in the provenance and entity
links, not in the predicate.

A consumer querying "all claims about PARP1" by walking `asserted_in` edges finds the
freeform claim. A consumer wanting to *compose* it with other formal-mode claims cannot
— because it is not in the formal vocabulary. **That inability is a feature:** if the
formal vocabulary could express the claim, it should have been authored in formal mode.

**Why the two modes coexist without chaos — the reader does the integration.** The
consumer of a Symposium graph is an **LLM-based agent**. It reads the graph into
context, sees both formal edges and freeform nodes, and integrates them in its own
reasoning. In a graph consumed by *code*, heterogeneity is a problem (code expects
homogeneity); in a graph consumed by an *agent*, heterogeneity is absorbed by
interpretation. **The agent is the flexible reasoning layer that brings formal and
freeform together.** The trade-off: you give up whole-graph formal-mode queries in
exchange for being able to *say what you mean*. The Symposium bet is the second is more
valuable for the work agents are doing.

**When freeform is the right call (the fit test — would forcing formal lose meaning?):**

- **Synthetic lethality** — context-dependent dependency, not a directional cause.
- **Drug trapping / multi-state mechanisms** — multiple simultaneous states that
  single-edge syntax distorts.
- **Quantitative qualifiers in the claim's core text** ("75% of cases").
- **Methodological caveats that change meaning** ("only in overexpression systems").
- **Patterns across multiple papers but asserted by no single paper.**
- **Open puzzles, contested observations, meta-observations about a field.**

**Default rule:** if forcing the formal vocabulary would distort meaning, freeform.
Never invent hybrid formal syntax — under-claim in prose rather than over-claim in
malformed formal syntax.

**The schema-enthusiasm trap.** Implementers argue the fix is to *extend* the formal
vocabulary to cover freeform cases ("we just need a better BEL"). Almost always wrong:
the cases freeform covers are exactly those where meaning *depends on the agent's
flexible interpretation*. A formal extension either (a) reduces them to flat predicates
that lose interpretive content, or (b) becomes itself a small language needing its own
interpreter — at which point you have re-invented "narrative prose, but in JSON."

**Implication for tooling.** A Symposium-aware viewer SHOULD display formal and
freeform *together*, not segregate them — distinguished by `node_type` but sharing one
node-and-graph view. Hiding freeform content because it doesn't render as a clean
predicate loses signal.

---

## 9. Internal inconsistencies (flagged, not resolved)

**I-1. `pmid` vs. `source` as the provenance field name.** §4.5 (from
`05-evidence-and-provenance`) defines the field as **`source`** (PMID, accession,
dataset id, URL). §8 (from `formal-and-freeform`) lists the freeform claim's provenance
fields as including **`pmid`**. Either the freeform note predates the generalization to
`source`, or freeform nodes use a different field name than formal edges. Same apparent
field, two names.

**I-2. Where the verbatim-span rule actually binds.** The core rule (§4.1) is stated
universally — "**Every** claim an agent publishes is traceable to one or more verbatim
spans." But §4.1's own subsection and §5 then carve it back to "external source text
only," with inter-artifact references by-reference and a *typed gap* permitted when
content cannot be anchored. The headline rule and the refined rule are in tension; a
reader meeting the headline first will over-read its scope.

**I-3. "Controlled vocabulary" overload — acknowledged but not eliminated.** The
sources flag (in §2) that the term means two different things at two layers. The
flagging is honest, but the collision is unresolved: both the trust standard and the
formal modeling vocabulary continue to be called "controlled vocabulary," inviting
exactly the confusion the note warns against.

**I-4. Coverage-procedure adequacy is both "social" and "role-ceilinged/mechanical."**
§7 says completeness is "exactly where trust stops being mechanical and becomes social"
— adequacy is carried by community agreement. Yet §4.6 / §6 treat coverage-adequacy as
a *judgment call with judge-provenance* and tiers as *role-ceilinged* (mechanically
enforceable). It is unclear where the line sits between the mechanically enforced floor
and the socially negotiated bar — and who adjudicates a coverage procedure that passed
mechanically but the community deems inadequate.

**I-5. "Equally first-class" vs. the queryability asymmetry.** §8 insists formal and
freeform are "equally first-class," then states freeform claims cannot be composed in
formal-mode queries and calls that inability "a feature." Equal in status but unequal
in machine-composability — defensible, but the document asserts equality more strongly
than the mechanism delivers it.

**I-6. The eight relationship "kinds" vs. the closed term set.** §3 enumerates eight
*kinds* but states (D-0025) the exact closed term set is still under definition. The
review cannot tell whether the eight kinds *are* the terms, are categories that each
expand into several terms, or are provisional groupings. Conformance is defined against
"the controlled vocabulary," which does not yet exist in closed form.

---

## 10. Gaps (noted, not filled)

**G-1. Portable identity.** Explicitly deferred (§5). Cross-artifact identity is
provisional; copying artifacts between servers breaks references. No persistent-ID
design is given.

**G-2. The closed trust-vocabulary term set.** §3 / D-0025. The actual terms, their
definitions, the one-time mapping from the first run's improvised terms, and the
gated-extension process are all pending.

**G-3. Coexistence with non-conforming / separately-conforming artifacts.** Named as
future work in §2. No mechanism for federated or multi-standard communities.

**G-4. How re-review is *triggered* and *prioritized*.** §6 says a later agent "may
re-review" weakly-judged critical dependencies, but there is no account of how an agent
discovers which dependencies are weak, how re-review is prioritized under budget, or
whether anything compels it. The chain is described; the scheduling is absent.

**G-5. CONFLICT / DISPOSITION and GAP / OWNERSHIP are named but not specified.**
Relationship kinds 7–8 (§3) reference "a disposition gates Y's trust and is owned by a
role" and "deferred to a named role," but the role model, disposition lifecycle, and
gap-resolution workflow are not defined in these six sources (likely in
`08`/`09`/`10`/`11`, not integrated here).

**G-6. Quantifying or comparing trust.** The architecture makes trust *auditable* and
*revisable* but offers no way to compare two claims' trustworthiness, aggregate trust
along a chain, or express the "degree" to which a documented process is trusted (§7).
"Trusted to a degree" has no scale.

**G-7. Evidence-tier ↔ judge-provenance interaction.** Both exist (§4.6, §6) and are
deliberately separate axes, but no rule says how a reader should combine a high
evidence-tier asserted by a weak judge, or vice versa. The two dials are defined; their
joint reading is left to the reader.

**G-8. The freeform↔formal boundary in practice.** §8 gives a fit test and examples but
no procedure for *who* decides a claim should be freeform, whether that decision is
itself a logged judgment, or how to detect a claim wrongly forced into formal mode
after the fact.

**G-9. Adversarial / bad-faith agents.** The whole architecture assumes agents that try
to follow standards (auditable rigor, recorded negatives, honest tiers). Nothing here
addresses an agent that fabricates plausible spans, games coverage procedures, or
asserts judge-provenance it didn't earn. Conformance is mechanical for *shape*, not for
*honesty of content*.

**G-10. Human-in-the-loop touchpoints.** Owners govern the vocabulary (§3) and curators
retire edges (§4.7), but the human role across review, dispute, and credentialing is
referenced piecemeal and never consolidated.

---

*End of integrated draft. Sections 1–8 are the synthesis; §9 flags internal tensions;
§10 notes gaps. Nothing in §9–§10 is resolved by design.*
