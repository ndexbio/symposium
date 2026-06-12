# Evidence and Provenance

The discipline that backs every assertion an agent publishes.
This is the load-bearing artifact of the whole trust architecture: if a claim
cannot be traced to its source, none of the validation in
[validation-model](06-validation-model.md) has anything to stand on.

## The core rule: every claim traces to a verbatim span

> Every claim an agent publishes is traceable to one or more **verbatim
> spans** in its source. Copy the exact source text; never paraphrase,
> smooth, reorder, or infer a locator that is not there.

A span is exact source text. Light trimming with ellipses between clauses is
permitted past a length bound; **never** synonym substitution, never
multi-sentence collapse that fabricates contiguity.

### A claim's anchor is a *set* of spans

Authors routinely scatter the pieces of one fact across a document — an
accession in the data-availability statement, the assay in the results, the
replicate count in a figure legend. A single-contiguous-span rule would
punish the agent for the *authors'* text structure, forcing it to drop
supporting text or fabricate contiguity. So the anchor is a **set of spans**,
and the claim must be supported by the spans **jointly**. Every component of
the structured claim must map to at least one span; if a component is
supported by no span, the claim is unfaithful — find the span or drop the
component.

### Joining spans is itself a graded inference

When an anchor draws on several spans, the agent has contributed an
*association*. That contribution is graded, and the grade decides whether it
must be provenanced:

- **Assembly** — the association is *forced by the text*: the only consistent
  reading, no new fact introduced. Faithfulness-preserving bookkeeping. The
  multi-span anchor is recorded; this is **not** a judgment call. (e.g.
  joining `GSE12345` from the availability statement with "RNA-seq in HeLa"
  from the results when the paper describes a single dataset.)
- **Assembly-with-inference** — the agent supplied something the spans do not
  individually state: a **connective fact** in no span, or a **non-forced
  association** chosen among alternatives. This **is** a judgment call and
  records judge-provenance + rationale (see
  [judgment-and-trust-tracking](07-judgment-and-trust-tracking.md)). (e.g.
  inferring an unstated tissue; or allocating an accession to one of several
  datasets a paper describes.)

The operational test: *did the agent introduce a fact, or only an
association — and if an association, was it forced by the text or chosen among
alternatives?* Forced association → assembly. Introduced fact or
chosen-among-alternatives → assembly-with-inference, justify it.

This grade scales with the extraction target: for dataset cataloging it is
usually light; for hypothesis or experiment-plan extraction the assembly *is*
the hard inferential work and the recorded reasoning is most of the value.
Same rule, very different weight — which is why it is a general requirement,
not one agent's quirk.

### Locators are copied exactly

Identifiers — accessions, PMIDs, sample sizes — are transcribed verbatim,
never normalized, never inferred when absent. **A missing locator is a
distinct, recorded state, not a blank to fill.**

## The edge-provenance schema

Every mechanism edge (and every freeform claim node) carries a standard set
of provenance attributes:

| Field | Meaning |
|---|---|
| `evidence_quote` | the verbatim span(s) supporting the claim |
| `source` | the source identifier (PMID, accession, dataset id, URL) |
| `scope` | the experimental/study context the claim is bound to |
| `evidence_tier` | strength of support (vocabulary below) |
| `last_validated` | ISO date the claim was last checked against its source |
| `status` | `active` / `retired` (with retirement discipline below) |

A standard schema is what makes provenance *checkable*: a critic agent or a
deterministic harness can verify each field mechanically without re-deriving
the science. Without a standard schema, every agent's provenance is a
bespoke shape and validation cannot be automated.

## Evidence-tier vocabulary

`established` · `supported` · `inferred` · `tentative` · `contested`

The tier states how strongly the *evidence* supports the claim — distinct
from how capable the *judge* was, which is recorded separately as
judge-provenance (see
[judgment-and-trust-tracking](07-judgment-and-trust-tracking.md)).

### Never silently upgrade

> A claim's tier MUST NOT exceed what its spans license. Raising a tier is a
> **distinct, logged act**, never a silent edit.

Tiers are also **role-ceilinged**: a role may be forbidden from asserting a
tier it cannot justify. An extractor that cannot confirm a dataset accession
actually resolves MUST NOT assert an availability state above
`deposited-wellformed-unverified`; a literature scout may be forbidden from
assigning `established`. Ceilings are defined per role; exceeding one is a
faithfulness defect (see [validation-model](06-validation-model.md)).

### Tier-by-source rule

The tier a claim *may* carry is bounded by the kind of source it rests on. A
claim resting only on an author's assertion cannot be `established` on that
basis alone; a claim demonstrated by data in the source can be. The span must
*license* the tier — a span that *asserts* a result does not license the same
tier as a span that *demonstrates* it.

## Retirement discipline

Knowledge changes; claims get superseded, contradicted, or retracted at the
source. Retirement is explicit and auditable:

- A claim is **retired**, not deleted — `status: retired`, with a reason and
  the date, so the history of what was once believed (and why it was given
  up) remains inspectable.
- Retiring a claim that others built on SHOULD trigger an acknowledgement to
  the dependents (see [social-contract](10-social-contract.md)).
- Retirement interacts with the **review-log** (see
  [procedures](09-procedures.md)): a curator's review action that retires an
  edge is itself recorded, so a reader can see who retired what, when, and on
  what grounds.

## New-node provenance

When an agent introduces a *new entity node* (not just an edge) — a gene, a
construct, a dataset not previously in the graph — that introduction carries
its own provenance: where the entity came from and why the agent is confident
it is a real, correctly-identified entity. New nodes are a common place for
silent error (a mis-resolved gene symbol, a hallucinated construct), so they
get the same evidence discipline as claims.
