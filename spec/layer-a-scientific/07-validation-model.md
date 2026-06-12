# The Validation Model

**Layer A.** How the *correctness of an agent's report* is judged: what is
being judged, what can be tested procedurally, what must fall to documented
judgment, how an agent knows it is done, and the contract a critic runs
against any report. This is the operational heart of the trust claim.

It is written **general-first** — these are the rules for any *extractor*
agent (one that turns an unstructured source into structured claims) — with
**dscout** (a dataset-scout) as a running concrete instance.

## A reconciliation up front: contract vs. conventions

Elsewhere the spec is emphatic that Symposium is **conventions, not schemas**
— strict in publishing, tolerant in reading, no substrate-level validation
(see
[design-notes/conventions-not-ontologies.md](../../design-notes/conventions-not-ontologies.md)).
This document introduces a checklist with PASS/INVALID outcomes, which looks
like the opposite. It is not a contradiction, and the boundary is worth
stating:

> The **substrate** is convention-first — almost nothing is enforced on the
> NDEx write path. The **validation contract** is a *community SOP layered
> above the substrate* — enforced by critic agents and human reviewers, not
> by the substrate. Conventions govern what makes content **legible**; the
> validation contract governs what counts as a **trustworthy report**, and
> that bar **rises over time** as the community and its agents improve.

So a malformed report can be *published* (the substrate permits it) and then
fails *validation* (a critic flags it). Publication legibility and report
trustworthiness are two different gates. See
[CRITIQUE.md §6](../../CRITIQUE.md).

## 1. What is being judged

An extractor's output is a **report**: structured claims drawn from a source,
each carrying its provenance. Judging its correctness means answering three
*separable* questions. Keeping them separate is the central discipline — they
have different testability, different failure modes, and different agents may
be trusted to judge each.

| Question | Name | Testability | An error here looks like… |
|---|---|---|---|
| Does the report accurately represent what the source says? | **Faithfulness** | Mechanical core + bounded judgment | A sample count or accession the paper does not state |
| Did the report capture everything it should have? | **Completeness** | Partially procedural | A dataset named in the results but missing from the report |
| Does the report stay within its role's remit? | **Scope-fidelity** | Procedural | An interpretation claim in a report meant to catalog only what was performed |

A fourth property — **whether the underlying science is any good** — is
explicitly **not** the extractor's to judge. The extractor reports that the
authors used CellTiter-Glo; it does not adjudicate whether that was the right
assay. That belongs to critique/analysis roles. The extractor is judged on
faithfulness, completeness, and scope-fidelity *only*.

## 2. Scope-fidelity — the cleanest, and it fixes the other two

An extractor reports **what was performed**, not **what the authors believe
it means.**

- **In scope (faithfulness territory):** the experiment run, the
  assay/technique, the system it ran in, the data produced, and the caveats
  *inherent to that technique*. "viability by CellTiter-Glo in HeLa; 3
  biological replicates" — and CellTiter-Glo's known caveats travel with it,
  because they are properties of *what was performed*.
- **Out of scope (interpretation territory):** the authors' hypothesis,
  intent, assumptions, and what they take the result to demonstrate. "to test
  whether knockout reduces viability" is *intent* — the authors' framing of
  the measurement's purpose, not the measurement. This belongs to a separate
  paper-analysis role.

The boundary has a soft edge by design: enough experimental context travels
with a datum that its caveats are present, but the report stops short of the
authors' inferential intent. **That edge is the faithfulness boundary.** A
report crossing it commits a scope-fidelity error *even if every word is
faithful* — because it faithfully reports something the role must not assert.

*dscout instance:* a dscout report catalogs datasets and how they were
produced. It must not state why the authors ran the experiment or what they
concluded. If a paper is interpretation-rich, dscout leaves a free-text
pointer for the claims/mechanism agent — it does not extract the
interpretation.

## 3. Faithfulness — a mechanical core and a bounded judgment shell

The discipline that makes faithfulness checkable is in
[evidence-and-provenance](06-evidence-and-provenance.md): verbatim spans, the
span *set* as anchor, the **assembly / assembly-with-inference** grade, exact
locators. This document is about what a *checker* can verify.

> **Faithfulness is not "largely procedural" without qualification.** It has
> a **mechanical core** a deterministic harness can verify, and a **judgment
> shell** that is small, bounded, and provenanced. Naming the boundary is
> itself part of the discipline. See [CRITIQUE.md §3](../../CRITIQUE.md).

**Mechanical core** (a harness verifies these without re-deriving science):

- **Span existence** — every cited span occurs in the source, verbatim.
- **Component coverage** — every component of the structured claim maps to at
  least one span; no component is left supported by nothing.
- **Locator integrity** — each identifier matches its span
  character-for-character and matches its declared repository/type.
- **Tier honesty** — no claim carries a tier above what its spans license; no
  role-ceiling violation.

**Judgment shell** (these require a decision, and the decision is
provenanced):

- **Joint support** — do the spans, read together, support the claim?
- **Assembly grade** — for each multi-span claim, was the agent's
  contribution mere *assembly* (forced association, passes) or
  *assembly-with-inference* (introduced fact or chosen-among-alternatives —
  must carry judge-provenance)? An unprovenanced inference masquerading as
  assembly is a faithfulness defect.

The residual judgment is therefore not "does this one span support this one
claim" but the sharper, smaller question *"for each multi-span claim, was the
contribution assembly or inference?"* — bounded and reviewable, which is the
point of surfacing the join rather than hiding it in a single verdict.

A report can be **100% faithful and badly incomplete.** Faithfulness says
nothing about coverage; that is §4's job, and the two MUST NOT be collapsed
into one "accuracy" score.

*dscout instance:* faithfulness for a dataset record = the accession occurs
verbatim; the provenance quote is the data-availability sentence and contains
the availability claim; `production_method` and `assay_type` are stated, not
inferred; the availability state does not exceed
`deposited-wellformed-unverified` (dscout's ceiling, since it cannot confirm
the accession resolves).

## 4. Completeness — the hard half

The checker cannot know what the source contains that the report omitted
without, in effect, redoing the extraction. Critical information hides where
extractors under-look — the **results section and supplementary materials**,
not just methods. "Did the agent find every dataset?" has no closed-form
answer.

### 4.1 What CAN be tested procedurally (partial)

The standard *requires running* these, because they are mechanically catchable:

- **Locator sweep** — scan the *entire* source (methods, results,
  data-availability, supplementary, figure/table captions) for identifier
  patterns (accession regexes, repository names, "available at…" phrasings).
  Any hit not represented in the report is a completeness gap.
- **Internal-consistency cross-check** — entities the report's own prose
  names but does not capture as structured records. ("RNA-seq and ATAC-seq
  were performed" → two assays named; if only one dataset record exists, flag
  it.)
- **Required-field population** — every record has every required field
  populated **or explicitly marked absent with a reason**. A silent blank is
  a completeness defect; an explicit "no accession stated" is complete.

### 4.2 What CANNOT be proven — and the standard that replaces proof

The residue — did the agent correctly understand which experiments produced
which data, and find experiments described only narratively — cannot be
proven complete. The standard is therefore **defined-and-defensible, not
provably-complete**:

> An extractor is **done** when:
> 1. every claim is faithfulness-anchored (§3),
> 2. every required field is populated or explicitly marked absent, and
> 3. a **declared coverage procedure** has been run across all source
>    sections, **and its negative results are recorded.**

The third clause is the crux. "I scanned methods, results, data-availability,
and supplementary for accession patterns and dataset mentions; none beyond
the three catalogued" is a **recorded negative** — it converts an absence into
evidence. Completeness becomes *a documented process trusted to a degree*,
governed by which coverage procedure ran at what version. This is exactly
where community SOPs carry what procedure alone cannot: the community decides
which coverage procedures count as adequate, and that bar rises as agents
improve.

### 4.3 The coverage procedure is a first-class, versioned artifact

Because "done" rests on the coverage procedure, that procedure is a
**versioned, cited artifact** (see [procedures](10-procedures.md)). A report
records *which* coverage procedure + version it ran. Trust in the report's
completeness is then no better and no worse than trust in that procedure —
and the procedure is inspectable and improvable independently. A report
validated under coverage-procedure v1.3 stays honestly labeled after v1.4
exists; re-validation under v1.4 is a distinct, logged act.

### 4.4 The Layer B adequacy rule

Completeness presumes the orchestration gave the agent enough budget and
enough of the source in view to *run* the coverage procedure. That dependency
is real and is stated, not hidden:

> **Layer A defines the standard; Layer B (orchestration) must be adequate to
> it. Where orchestration cannot afford the coverage procedure — too small a
> batch, too tight a budget, the supplementary never in context — the result
> is VALID-WITH-GAPS, never silently "done."**

This keeps the standard wholly in Layer A while making the dependency
explicit and honest. See
[layer-b-orchestration/00-why-this-is-separate.md](../layer-b-orchestration/00-why-this-is-separate.md)
and [CRITIQUE.md §7](../../CRITIQUE.md).

*dscout instance:* dscout's coverage procedure names the sections to sweep,
the identifier patterns per repository-of-interest, and the dataset-mention
cues. Running it and recording its negatives is what lets dscout assert "this
paper offers exactly these datasets" defensibly rather than hopefully.

## 5. The report-validation contract (the testable surface)

The checklist a critic agent or human reviewer runs against any extractor
report. This is the concrete artifact to stress-test.

**A report PASSES validation when all hold:**

*Faithfulness:*
- [ ] Every structured claim is anchored to one or more verbatim spans, each
      occurring in the source.
- [ ] Every claim component maps to at least one span; the span set jointly
      supports the claim.
- [ ] Every multi-span claim is graded: forced associations pass as assembly;
      any introduced fact or chosen-among-alternatives association carries
      judge-provenance. An unprovenanced inference is a defect.
- [ ] Every identifier matches its span exactly and matches its declared
      format/repository.
- [ ] No claim's tier exceeds what its span licenses; no role-ceiling
      violation.

*Scope-fidelity:*
- [ ] No claim is in another role's remit (no interpretation/intent in an
      extractor report).

*Completeness:*
- [ ] Every required field is populated or explicitly marked absent with a
      reason.
- [ ] The locator sweep ran over *all* source sections; every hit is
      represented or explicitly dispositioned.
- [ ] The internal-consistency cross-check ran; entities named in prose but
      not captured are explained.
- [ ] The declared coverage procedure (name + version) is recorded, and its
      **negative results** are recorded.

*Judgment provenance:*
- [ ] Every judgment-call step carries judge-provenance proportional to its
      stakes (see [judgment-and-trust-tracking](08-judgment-and-trust-tracking.md)).

### The trichotomy

- **INVALID** (not merely incomplete) if any faithfulness or scope-fidelity
  check fails, **or** a required field is silently blank, **or** no coverage
  procedure is recorded.
- **VALID-WITH-GAPS** when faithfulness and scope hold, fields are explicitly
  dispositioned, and the coverage procedure ran — but the procedure or a
  reviewer flags a known residual completeness risk (recorded, not hidden);
  or when the Layer B adequacy rule (§4.4) could not be met.
- **VALID** when all checks pass with no flagged residual risk.

The VALID / VALID-WITH-GAPS / INVALID verdict is itself a **trust signal that
downstream agents read** when deciding whether to build on the report.

## 6. The seam to promotion

Report validation is **separate from** the community decision to promote a
resource from agent-owned to community-owned — but it is the **evidence that
decision consumes.** A report's validation status, its coverage-procedure
citation, and its judgment-provenance are exactly what a promotion gate
weighs. The validation model here is the *mechanism*; the promotion *policy*
(who decides, what threshold, how duplicates reconcile) is a pinned research
goal — see [resources-promotion-credentialing](09-resources-promotion-credentialing.md).

## 7. Open seams

1. **Assembly-grade adjudication.** Worth a lightweight deterministic
   pre-check for the "forced association" case (spans share the claim's key
   entities/identifiers, no alternative referent present) before falling to a
   model judgment — keeping the common case cheap and reserving provenance
   for genuine inference. The hard instances (accession-to-dataset allocation
   among several datasets) likely always need the model judgment and recorded
   rationale.
2. **Coverage-procedure adequacy.** The *process* by which the community
   blesses a coverage procedure as adequate is unspecified and overlaps the
   credentialing research goal.
3. **Criteria versioning.** Faithfulness/completeness/scope criteria are
   themselves versioned SOPs. Where they live (community SOP networks vs.
   per-agent procedures) and how an agent learns the current version needs a
   home — see [procedures](10-procedures.md).
4. **VALID-WITH-GAPS semantics.** Whether this is one state or a small graded
   vocabulary, and how downstream consumers are required to treat it.
