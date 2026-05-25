# Formal and Freeform Modes are Complementary

Symposium content uses two modes of representation: formal (a
controlled vocabulary) and freeform (narrative claim nodes with full
provenance). They are equally first-class. This note explains why
the spec rejects the more common framing of "formal mode is the
goal; freeform mode is a fallback."

## The "ontology coverage equals rigor" assumption

The intuitive starting point for representing scientific knowledge is
to choose a controlled vocabulary and stick with it. Pick BEL, or
OpenCypher, or a GO-CAM-shaped representation, and author everything
in it. Coverage in the formal vocabulary is then a proxy for rigor:
if a claim fits, the agent is doing the work; if it doesn't fit, the
agent should keep refining until it does.

This view is widely held and it produces *worse* knowledge graphs in
practice.

The reason: forcing a claim into a vocabulary that doesn't fit
*degrades* the claim. The agent either picks the closest formal
predicate (and loses the qualifier that made the claim meaningful)
or invents an extension to the vocabulary (and undermines the
interoperability that motivated the choice).

A claim like "PARP1 inhibition is synthetic lethal with BRCA1
deficiency *in cells with intact homologous recombination
elsewhere*" has a structure that no single BEL edge captures
cleanly. The "in cells with X" qualifier is not a study-context
detail (which `scope` handles); it is part of the *claim itself*.
Drop it, and the claim now reads as a universal — which is wrong.

## What freeform actually does

A freeform claim node carries:

- The full narrative claim, with all of its qualifiers preserved.
- The same provenance fields as any formal edge (`evidence_quote`,
  `pmid`, `scope`, `evidence_tier`, `last_validated`).
- Optional links to canonical entity nodes via `asserted_in` edges.

This is not "less structured" content. It is structured *differently*:
the structure is in the provenance and the entity links, not in the
predicate.

A consumer querying for "all claims about PARP1" by walking
`asserted_in` edges finds the freeform claim. A consumer wanting to
compose the claim with other formal-mode claims about PARP1 cannot —
because the freeform claim is not in the formal vocabulary. That
inability is a feature: if the formal vocabulary could express the
claim, it should have been authored in formal mode in the first
place.

## The reader does the integration

The reason the two modes can coexist without producing chaos is that
the consumer of a Symposium knowledge graph is an LLM-based agent.
The agent reads the graph into context, sees both formal edges and
freeform claim nodes, and integrates them as part of its own
reasoning.

In a graph consumed by code, this would be a problem — code expects
homogeneity. In a graph consumed by an agent, heterogeneity is
absorbed by the agent's interpretation. The agent is the flexible
reasoning layer that brings formal and freeform together.

The trade-off: you give up the ability to compose formal-mode
queries that span the whole graph, in exchange for being able to
*say what you mean*. The Symposium bet is that the second is more
valuable than the first for the kind of work agents are doing.

## When freeform is the right call

The spec describes the decision as a fit test: would forcing the
formal vocabulary lose meaning? Practical examples where the answer
is yes:

- **Synthetic lethality.** Context-dependent dependency, not a
  directional cause.
- **Drug trapping / multi-state mechanisms.** Multiple simultaneous
  states (drug bound + protein trapped + adduct formed) that
  single-edge formal syntax distorts.
- **Quantitative qualifiers in a claim's core text** ("75% of
  cases," "selective in late-stage disease").
- **Methodological caveats that change meaning** ("only in
  overexpression systems," "not reproducible in primary cells").
- **Patterns observed across multiple papers but not asserted by
  any single paper.**
- **Open puzzles, contested observations, meta-observations about a
  field.**

The default rule: if forcing the formal vocabulary would distort
meaning, freeform. Never invent hybrid formal syntax — under-claim
in prose rather than over-claim in malformed formal syntax.

## A pre-emptive note on schema enthusiasm

Implementers occasionally argue that the right answer is to *extend*
the formal vocabulary to cover the freeform cases. "We just need a
better BEL." Some version of this is always tempting and almost
always wrong.

The reason it tempts: the formal claims are queryable, the freeform
ones are not, and the asymmetry feels untidy.

The reason it's almost always wrong: the cases freeform covers
(quantitative qualifiers, contextual dependencies, methodological
caveats, meta-observations) are the exact cases where the meaning
*depends on the agent's flexible interpretation*. A formal extension
that "captures" them either (a) reduces them to flat predicates that
lose the interpretive content, or (b) becomes itself a small
language that needs its own interpreter — at which point you have
re-invented "narrative prose, but in JSON."

Resisting the schema-extension instinct is one of the harder
disciplines for a freshly-onboarded implementer. The freeform mode
is not a failure of the formal vocabulary; it is the explicit choice
to let the reader do the integration.

## Implication for tooling

A Symposium-aware viewer should display formal and freeform content
*together*, not segregate them. A reader skimming an agent's
knowledge graph should be able to see, for a given entity, both the
formal edges and the freeform claims that mention it. Hiding
freeform content because it doesn't render as a clean predicate
loses signal.

The reference implementation's agent-hub viewer follows this rule:
freeform claims and formal edges share the same node-and-graph view,
distinguished by `node_type` but not segregated. Implementations of
Symposium-aware tooling SHOULD do the same.
