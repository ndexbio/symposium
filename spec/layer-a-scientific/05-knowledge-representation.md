# Knowledge Representation

**Layer A.** How scientific content is expressed inside a network. Two modes,
equally first-class: **formal** (a controlled vocabulary) and **freeform**
(narrative claim nodes with full provenance). The spec does not mandate a
particular formal vocabulary; the reference implementation uses
[BEL](http://openbel.org/) for mechanism claims.

## Two modes, complementary — not a hierarchy

The common framing — "formal mode is the goal; freeform is a fallback" —
produces worse knowledge graphs, because forcing a claim into a vocabulary
that does not fit *degrades* it. The agent either picks the nearest formal
predicate (losing the qualifier that made the claim meaningful) or invents a
vocabulary extension (undermining the interoperability that motivated formal
mode at all).

> A claim like "PARP1 inhibition is synthetic lethal with BRCA1 deficiency
> *in cells with intact homologous recombination elsewhere*" has no clean
> single-edge formal form. The "in cells with X" clause is part of the
> *claim*, not study context. Drop it and the claim becomes a universal —
> which is false.

So the modes are complementary. Formal content is composable and queryable
across the graph; freeform content says what the vocabulary cannot. See
[design-notes/formal-and-freeform.md](../../design-notes/formal-and-freeform.md)
for the full argument, including why "just extend the vocabulary" is almost
always the wrong instinct.

## When to author in formal mode

Use formal mode when the claim fits the vocabulary cleanly: a directional
mechanism (`X increases Y`), a well-typed entity relationship, anything other
agents will want to **compose** with other formal claims. Formal content
carries the same provenance as freeform — formality does not exempt a claim
from [evidence and provenance](06-evidence-and-provenance.md).

## When to author in freeform mode

Use freeform when forcing the vocabulary would distort meaning. The decision
is a **fit test**: *would the formal vocabulary lose part of the claim?* If
yes, freeform. Patterns where freeform wins by default:

- context-dependent dependencies (synthetic lethality) rather than directional cause;
- multi-state mechanisms (drug bound + protein trapped + adduct formed);
- quantitative qualifiers in the claim's core ("75% of cases", "selective in late-stage disease");
- methodological caveats that change meaning ("only in overexpression systems", "not reproducible in primary cells");
- patterns observed across several papers but asserted by none;
- open puzzles, contested observations, meta-observations about a field.

**Never invent hybrid formal syntax.** Under-claim in prose rather than
over-claim in malformed formal syntax.

## The freeform claim node

A freeform claim node is first-class content, not a degraded edge. It carries:

- the full narrative claim, with all qualifiers preserved;
- the same provenance fields as any formal edge (`evidence_quote`, source
  identifier, `scope`, `evidence_tier`, `last_validated` — see
  [evidence-and-provenance](06-evidence-and-provenance.md));
- optional links to canonical entity nodes via `asserted_in` edges, so a
  consumer walking entity links still finds the claim.

The structure of a freeform claim is in its **provenance and entity links**,
not in a predicate. A consumer querying "all claims about PARP1" by walking
`asserted_in` edges finds it; a consumer wanting to *compose* it with other
formal claims about PARP1 cannot — and that inability is correct, because if
the vocabulary could express the claim it should have been authored formally.

## Commentary as a node

Interpretive context, a caveat, or a meta-observation *about* another node or
edge is itself a node, linked to its target by an `applies_to` edge —
**commentary-as-node**. This preserves dialectic without rewriting history:
a later agent's qualification of an earlier claim attaches to it rather than
overwriting it.

- **Commentary on commentary** is allowed: an `applies_to` edge can target a
  commentary node, forming a visible chain of qualification.
- **Commentary vs. edge attribute.** A fact intrinsic to *what was performed*
  (an assay's known caveat, the scope of an observation) belongs as an
  attribute on the edge/claim. A *stance about* the claim (a reviewer's
  doubt, a cross-paper observation, a "this conflicts with X") belongs as a
  commentary node. The test: is it part of the claim, or a position on the
  claim?

## What the spec does not prescribe

The choice of formal vocabulary (BEL, OpenCypher-shaped, GO-CAM-shaped, …) is
out of scope; the spec requires only that mechanism content carry the
standard [edge-provenance schema](06-evidence-and-provenance.md). Viewers and
tooling SHOULD display formal and freeform content **together**, distinguished
by node type but not segregated — hiding freeform content because it does not
render as a clean predicate loses signal.
