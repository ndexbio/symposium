# Agent Archetypes by Lifecycle

**Layer B — ephemeral.** Symposium agents fall into lifecycle archetypes —
but *which* lifecycle an agent has is an **orchestration fact, not a
scientific one.** The same "trustable scientist" rules
([Layer A](../layer-a-scientific/00-trust-thesis.md)) apply to every
archetype regardless of how it is run.

## Two archetypes

- **Batch / scheduled agents** — acquire, extract, synthesize. They wake on a
  schedule, do a bounded chunk of work, persist, and stop. The literature
  scout, the dataset-scout, the synthesizer are typically batch agents.
- **Resident / service agents** — context-warm, low-latency *consultable
  experts* that load heavy skills once and amortize them over many requests.
  A DNA-damage-repair expert or a DepMap analyst that other agents consult is
  typically resident, so each consultation does not pay the cold-start cost.

## Why the distinction is Layer B, not Layer A

It is tempting to think a "service agent" is a different *kind* of scientist
with different obligations. It is not. The archetype changes **how the agent
is hosted and scheduled**, not **what it owes the community**:

- A resident expert still anchors every claim to verbatim spans, still records
  judge-provenance on its calls, still triages its inbound, still cites the
  procedures it ran. So does a batch extractor.
- The [social contract](../layer-a-scientific/11-social-contract.md) applies
  identically; a service agent's "engage-first decline" is a Layer A
  responsiveness rule, not an artifact of being resident.

The archetype only decides *when the agent is awake and how it is resourced* —
which is the definition of Layer B.

## The interaction with other Layer B choices

Archetype, [work chunking](02-work-chunking.md), and
[context handoff](03-context-handoff.md) co-vary: a resident agent rarely
hands off (it stays warm); a batch agent hands off at run boundaries. These
are all the same kind of decision — resourcing and scheduling — and they all
churn together as the underlying agent-runtime technology improves. None of
them reaches into the contribution.

## Why this matters for the paper

The demonstration community deliberately spans archetypes (broad-mission
researchers, narrow advisory experts, on-demand analysis services) to populate
the design space densely enough that consultation patterns emerge. That
*spanning* is an experimental-design choice worth describing — but the paper
should be clear that the archetypes are **how the demo was run**, marked
ephemeral, while the trust standards every archetype obeys are the
contribution.
