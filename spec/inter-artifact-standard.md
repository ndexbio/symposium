# The Inter-Artifact Standard — artifacts, the trust vocabulary, and conformance

The Symposium commons is a graph of **artifacts**. The trust and provenance the
community builds on rest on every artifact conforming to a single, deliberately
small **inter-artifact standard**: a controlled vocabulary of trust-bearing object
types and the relationships between them. It is the successor to today's
DOI-and-citation structure — but **richer**: relationships are *typed* (not a flat
"cites"), *claim-grained* (not only artifact-to-artifact), and *machine-checkable*
(conformance is mechanical).

This document fixes what that standard governs and what it deliberately leaves free.
It is the inter-artifact complement to [knowledge-representation](requirements/04-knowledge-representation.md)
(content *inside* an artifact) and [evidence-and-provenance](requirements/05-evidence-and-provenance.md)
(the span discipline). Normative language is RFC-style: **MUST**, **SHOULD**, **MAY**.

## The artifact is the unit of the commons

A published artifact (in the reference implementation, a CX2 network on NDEx) is the
unit of publication, credentialing, addressing, and provenance — the DOI analogue.
One artifact is what an agent produces, an owner credentials, and another artifact
cites.

**Identity is currently provisional.** The reference implementation addresses an
artifact by its server-minted NDEx UUID, which is **resolvable but not portable**:
copying a set of artifacts to another server re-mints UUIDs and breaks cross-references.
For the initial system, cross-artifact identity MUST be treated as provisional —
coped with procedurally, or via a stable `user / folder-path / artifact-name` logical
address. Portable, server-independent persistent identifiers are deferred (a natural
evolution, since the project owns the NDEx substrate). This is a known, bounded gap,
not a solved problem.

## Two representational layers — do not conflate them

- **The inter-artifact standard (this document)** — the controlled vocabulary of
  **trust-bearing** node types and the ~8 relationship kinds. This is what
  conformance is checked against and what trust/provenance rest on.
- **Intra-artifact content** ([04](requirements/04-knowledge-representation.md)) —
  the scientific content *inside* an artifact, authored **formal** (BEL, GO-CAM,
  OpenCypher-shaped, …) or **freeform**. This is **free and evolvable**; the standard
  does not mandate it.

> **Naming caution.** "Controlled vocabulary" is overloaded. [04](requirements/04-knowledge-representation.md)
> uses it for an *intra-artifact formal modeling* vocabulary (e.g. BEL). *This*
> document's "controlled trust vocabulary" is the *inter-artifact* trust/provenance
> standard. They are different vocabularies at different layers; an artifact may use
> any formal modeling vocabulary internally while conforming to the one trust standard.

## What conforms: trust-bearing assertions, wherever they appear

The conformance boundary is **trust-bearing vs. domain content — it is orthogonal to
the artifact boundary.** A trust relationship is most often expressed *inside* one
artifact (a conclusion supported by a claim supported by a source-reference), with
only the citation crossing to another artifact. The standard governs the trust-bearing
structure **wherever it appears** — within an artifact and across artifacts — because
the no-error-laundering guarantee and the chain-of-evidence trace require the internal
support structure to be legible, not opaque.

> **Conformance.** An artifact conforms iff **every trust-bearing node and edge it
> publishes is drawn from the controlled vocabulary.** Domain content alongside the
> trust-bearing structure is unconstrained and is ignored by the trust machinery
> (but see *the judge as bridge*, below).

For the system reported by the paper, the community is **restricted to conforming
artifacts**. Coexistence with less formal artifacts — e.g. an artifact declaring it
conforms to a *separate* standard — is explicitly **future work**, out of scope here.

## The controlled trust-relationship vocabulary

The relationships fall into a small number of **kinds of trust relationship** — on
the order of eight — plus deliberate **foils** that carry no trust (their being
named is itself load-bearing: it is how the architecture states trust-inertness and
no-laundering out loud). The working set, distilled from the first live run
(see `symposium_dev:drafts/design/trust-vocabulary-review-r1.md`):

1. **SUPPORT** — X is evidence that grounds/raises the trust of claim Y.
2. **CORROBORATION / INDEPENDENCE** — X *independently* corroborates Y (raises trust
   only if independent); includes the negative case (declined-to-count).
3. **VALIDATION** — X reviews/grades the correctness of Y and issues a verdict.
4. **INTERPRETATION / JUDGMENT** — X is a provenanced judgment about Y, not new evidence.
5. **COVERAGE** — X attests how completely Y was swept.
6. **PROCEDURE** — Y was produced by method/procedure X.
7. **CONFLICT / DISPOSITION** — X stands in contradiction; a disposition gates Y's
   trust and is owned by a role.
8. **GAP / OWNERSHIP** — Y's trust is blocked-on / scoped-by a typed gap, deferred to
   a named role.
- **Foils (carry no trust):** prediction (trust-inert), provenance/lineage facts,
  control/structural navigation.

> **Status.** The *shape and governance* of the vocabulary are settled here; the
> exact closed term set is **under definition** (decision `D-0025`: controlled, not
> dynamically extended; one-time mapping of the first run's improvised terms onto the
> set; extension candidates recorded for gated addition). The vocabulary is not frozen
> until that lands.

The shape of the resulting graph: **trust bottoms out in span-anchored external facts
at the leaves, and composes by-reference internally.** Grounded where it touches the
world; legible where it builds on itself.

## Free content is the evidence substrate; the judge is the bridge

Domain content that is *not* formally trust-bearing is not inert decoration — it is
the substrate over which trust-bearing assertions are made. Prose explaining a
finding, a hypothesis rationale, or a data-analysis result **MAY be read by a judge**
(agent or human) as input to its decision to assert a trust-bearing type or
relationship. The judgment is the conformant output; the content is what it was made
over. This generalizes the fact/judgment split and "an expert agent is a
judgment-wrapped tool invocation" to the whole commons (see
[judgment-and-trust-tracking](requirements/07-judgment-and-trust-tracking.md)).

## Anchoring — a two-tier obligation

Refines [evidence-and-provenance](requirements/05-evidence-and-provenance.md) for the
inter-artifact setting.

- **Guideline (SHOULD), universal.** Every trust-bearing judgment anchors to what it
  relied on. A bare "the source says so" with no locator is insufficient. The *form*
  of the anchor is deliberately **not** universally mandated — a universal anchor spec
  over open content would be brittle. When content genuinely cannot be anchored, the
  assertion declares a **typed gap** (`uncomputable` / `blocked_on`) — never a
  fabricated anchor.
- **Enforced (MUST), external source text only.** An anchor that references **external
  source text** (the literature) MUST use the **span mechanism** of
  [05](requirements/05-evidence-and-provenance.md): a verbatim span set + exact
  locator, with span-existence mechanically re-checkable.
- **Inter-artifact references are by-reference.** A reference from one artifact's
  assertion to another artifact (or its assertions) is made **by reference** at
  assertion/artifact granularity. The span mechanism *may* be used to quote
  agent-generated text in another artifact, but it is **not required** — enforcing
  span-level internal cross-references would breed a tangled web that is
  machine-precise but human-inaccessible, defeating the legibility the standard exists
  to provide.

> A span anchor certifies **faithfulness** (the quoted text is really in the source),
> **not interpretation** (that the judge read it correctly). It therefore *enables* a
> later reader's re-analysis or dispute — handing them the precise locus — rather than
> foreclosing it.

**Future / owner-governed:** an artifact declaring its anchors follow a separate
evidence standard (e.g. "we follow the BEL evidence requirements") is a clean
extension point the owner may sanction over time.

## Governance

The inter-artifact standard is evolved **deliberately and slowly** by the **community
owner** — within a lab, the PI or their designate; in a large public community, an
organization with a human governance structure. It is **not** dynamically or
automatically extended to match whatever agents emit. A live run **may** surface a
genuine relation the vocabulary cannot express; such cases are **recorded as
extension candidates** for gated, owner-approved addition — never auto-admitted.
Conformance is paramount precisely because the whole community's trust and provenance
are computed over it.
