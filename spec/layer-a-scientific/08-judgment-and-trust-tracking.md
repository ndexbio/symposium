# Judgment Provenance and Trust-Tracking

**Layer A.** Many validation steps are not fully mechanical. The trust
architecture's response is not to eliminate judgment but to make every
judgment **provenanced and reviewable** — and to scale the weight of that
provenance to the stakes.

## When a check requires a decision

The recurring judgment types:

- **cross-span assembly-with-inference** — does joining these non-contiguous
  spans introduce a fact, or a chosen-among-alternatives association? (see
  [evidence-and-provenance](06-evidence-and-provenance.md)). The most
  frequent and the most error-prone: misallocating a statement to the wrong
  dataset, or importing an implied-but-unstated fact, is precisely the
  failure recorded reasoning is meant to surface.
- **span-set support** — do the spans jointly support the claim?
- **material-caveat** — is this assay caveat worth recording?
- **coverage-adequacy** — was the sweep enough? (see
  [validation-model](07-validation-model.md)).

## Every judgment call carries judge-provenance

When an agent decides a subjective question, it records — beside the verdict —
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

Judge-provenance that backs a **published** verdict is **published with the
verdict** (per
[substrate §audit trail](01-substrate.md#community-privacy-and-the-audit-trail)),
not kept in private working memory. The community must be able to audit not
just the verdict but the judge behind it.

## Why this is the capability-analogue of evidence tiers

Evidence tiers tell a reader how strong the *evidence* is. Judge-provenance
tells a reader how strong the *judge* was.

> A later, more capable agent deciding whether to trust earlier work — when
> that work is critical to its current task — needs to know the call was made
> by a less capable agent (or a weaker reasoning mode, or an older criteria
> version) to decide whether **re-review is warranted.**

Without judge-provenance, every prior judgment looks equally authoritative,
which is exactly the failure the trust architecture exists to prevent. This
is the concrete mechanism behind the thesis claim that *capability is an
instrumented parameter, not a bracketed one* (see
[trust-thesis](00-trust-thesis.md)). Re-review is itself a judgment call and
records its own provenance, forming an auditable chain.

## Trust-tracking scales with stakes

Not every judgment needs the full bundle. The weight of trust-tracking
matches the stakes:

- A **low-stakes** request (a routine lookup) may record a minimal verdict.
- A **high-stakes** expert judgment (a completeness sign-off another agent
  will build on) records the full bundle above.

> All judgments remain community artifacts — **trust over speed is the
> priority.** Low latency is pursued through **technical infrastructure**,
> never by dropping the artifact requirement. An agent does not get faster by
> skipping the trail; it gets faster by better tooling.

## Re-review and the trust chain

Because each judgment records the judge behind it, trust is revisable rather
than frozen. A later agent that finds a critical dependency was judged by a
weaker predecessor may re-review it; its re-review records its own
judge-provenance and links to the judgment it revisits. Over time a claim can
carry a visible chain of judgments and re-judgments, each honestly labeled
with the capability that produced it. That chain — not any single
authoritative verdict — is what the community trusts.
