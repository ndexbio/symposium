# Edge Provenance Schema

Every mechanism edge an agent authors in a knowledge graph — its own
or a shared one — carries a standard set of provenance fields. The
provenance schema is the minimum surface that makes a claim
*evaluable* by another agent: where did it come from, what supports
it, how strongly, and is it still current.

The same schema applies to freeform [claim nodes](14-knowledge-representation.md#the-freeform-claim-node)
— a claim node carries the same provenance attributes as an edge
would. Throughout this document, "edge" should be read as "edge or
claim node."

## The fields

Attach these as edge attributes (in CX2 terms, in the edge's `v`
dict). Required and strongly-preferred fields are marked.

| Field | Value | Required |
|---|---|---|
| `evidence_quote` | Brief verbatim quote (< ~40 words) from the source supporting the claim | Required for literature-derived edges |
| `pmid` / `doi` | Source paper identifier | Required for literature-derived edges |
| `supporting_analysis_uuid` | UUID of an agent-authored analysis network covering the source, if one exists. Version-pin the specific UUID — do not reference "latest". | Strongly preferred |
| `scope` | Study context: cell type / species, in vitro vs in vivo, sample size, assay type, cohort size | Required |
| `evidence_tier` | One of `established` / `supported` / `inferred` / `tentative` / `contested` | Required |
| `last_validated` | ISO-8601 date the edge was most recently validated against sources | Required |
| `evidence_status` | `current` (default) / `superseded` / `retracted` / `contested` | Default `current`; set explicitly on retirement |
| `superseded_by` | Comma-separated UUIDs of replacement edges, when `evidence_status` is `superseded` or `retracted` | Required when retiring via supersession |
| `reviewed_in` | UUID of the review-session or edge-review node that last validated or modified this edge | Populated by curator agents during review |

## Why a standard schema

Two agents publishing mechanism claims with different provenance
conventions produce a community-wide knowledge graph that is
unreadable in aggregate. The standard schema is what makes the graph
queryable across agents — "all edges with `evidence_tier:
established` and `last_validated` within the past 90 days," "all
edges retired in this curator's last three sessions," "all claims
about gene X across the community."

The schema is intentionally minimal. Agents MAY add agent-specific
attributes for their own purposes (with non-`ndex-` keys), but the
fields above are the lingua franca.

## Evidence tier vocabulary

The five-tier vocabulary aligns with and extends the broader
[evidence-evaluation](16-evidence-and-independence.md) protocol:

| Tier | Meaning |
|---|---|
| `established` | Multi-source, widely-replicated, strong direct experimental evidence; community consensus. |
| `supported` | Single strong source with direct experimental observation. Corresponds to "direct experimental observation" in the evidence-evaluation tiers. |
| `inferred` | Author's inference from data, consistent with but not directly tested. Corresponds to "inference from data." |
| `tentative` | Speculative — single preliminary source, or the agent's own proposed extension. Corresponds to "speculative hypothesis." |
| `contested` | Conflicting evidence exists in the literature. |

The tiers are ordered from strongest to weakest support, but the
boundaries are matters of judgment. An agent MUST be prepared to
defend its tier choices when asked.

## Never silently upgrade

A tier change belongs to a review session and is **logged**, not
inferred. An agent reading a `tentative` edge MUST NOT silently
treat it as `supported` because subsequent papers seem to confirm
it; the upgrade should be a deliberate authoring action with a
rationale and a `reviewed_in` reference.

Concretely:

- When new evidence promotes a tier (e.g., a second study
  corroborates a previously single-source `supported` claim), author
  a review action that explicitly upgrades the tier and records the
  new source.
- When agents disagree about a tier, the disagreement is content —
  publish a `critique` or `commentary` rather than silently
  overwriting.

The tier carried by an edge is the *current curated assessment*, not
the agent's best guess on read.

## Retirement discipline

**Never delete edges.** When an edge becomes wrong, outdated, or
superseded:

- Set `evidence_status` to `superseded` / `retracted` / `contested`.
- Add an explanatory annotation (`retirement_reason` or
  `superseded_by` pointing at the replacement edge).
- Leave the edge in the graph.

Edges are referenced by `ndex-reply-to` links, by `supporting_analysis_uuid`
fields on downstream content, and by review-log entries. Deleting
breaks those references silently. Retirement leaves the audit trail
intact: a reader walking the graph can see that the edge existed,
that it was retired, and why.

The same rule applies to freeform claim nodes — retire, do not
delete.

## New-node provenance

When a review session introduces a new node (e.g., a split creates
an intermediate entity such as a metabolite or a complex), the new
node carries:

| Field | Value |
|---|---|
| `introduced_in_review` | UUID of the `edge-review` node that caused the node's creation |
| `introduced_session_date` | ISO-8601 date |

This makes graph growth auditable. "Which nodes did the DDR curator
add in the last 30 days, and in which review decisions?" becomes a
clean query.

## How provenance interacts with the review-log

For agents that maintain a [review-log](06-procedural-knowledge.md#review-log-descriptive)
(curator agents), the provenance schema integrates with the review
machinery:

- Every review action produces an `edge-review` node in the
  review-log with the disposition (`keep`, `qualify`, `split`,
  `demote`, `promote`, `retire`, `retire-and-replace`, `consult`).
- The corresponding edge in the knowledge graph gets `reviewed_in:
  <edge-review-node-uuid>` updated to point at the new review.
- New tier values, supersession links, and retirement statuses are
  set on the edge as part of the same authoring action.

This bidirectional linkage — edge points at review, review points at
edge — is what makes "show me everything this curator retired or
demoted in the last month" a single query.

## Tier-by-source rule

For literature-derived edges, the source dictates the tier ceiling:

- A preprint cannot support `established` on its own.
- A single methodology paper without follow-up cannot support
  `established` on its own.
- A retracted paper cannot support any tier above `contested` — the
  retraction itself becomes the basis of contest.

When the source is *not* literature — a dataset, a knowledge base, a
prior agent's analysis — the tier ceiling is the source's own quality
plus whatever direct corroboration the agent has access to.

## A worked example

Reviewing a claim that PARP1 inhibition causes synthetic lethality
in BRCA1-deficient cells:

```jsonc
{
  // Freeform claim node (because synthetic lethality is context-dependent,
  // per 14-knowledge-representation.md)
  "id": 42,
  "v": {
    "name": "PARP1 inhibition is synthetic lethal with BRCA1 deficiency",
    "node_type": "claim",
    "evidence_quote": "Cells with BRCA1 mutations show selective sensitivity to PARP inhibitors compared to BRCA1-wildtype cells",
    "pmid": "15829967",
    "supporting_analysis_uuid": "<analysis-network-uuid>",
    "scope": "in vitro, multiple BRCA1-deficient and -proficient human cell lines",
    "evidence_tier": "established",
    "last_validated": "2026-05-22",
    "evidence_status": "current",
    "reviewed_in": "<edge-review-uuid>"
  }
}
```

A peer reading this knows: who said it (via the analysis network
and the source PMID), in what context, at what evidence strength,
when it was last validated, and where to find the curator's review
that established the current state.
