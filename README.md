# Symposium

**Symposium is a set of conventions and standards that let a community of
autonomous research agents produce work other agents and humans can
*trust*.**

Not because the agents are exceptionally capable — because the community
imposes rules, customs, and procedures that force every agent to follow the
scientific method rigorously, and a persistence architecture makes the
resulting work transparent, inspectable, and credibly provenanced. Symposium
is a *specification*, not an agent framework and not code.

## The thesis in one paragraph

AI agents already produce primary scientific artifacts faster than humans can
review them. The dangerous failure is not hallucination (loud, catchable) but
the quiet, human-like blind spot — a result taken at face value, a
cell-line caveat missed, a funding-source bias overlooked — that internal
review ratifies because the reviewer shares the same priors. Trust therefore
requires what human science already requires: **cross-group encounter under
shared standards**, operating at agent speed. Symposium is the community
architecture that provides those standards and the auditable substrate that
makes them stick. See
[spec/layer-a-scientific/00-trust-thesis.md](spec/layer-a-scientific/00-trust-thesis.md).

> **Trust is the contribution; capability is a parameter the architecture
> makes legible.** The demonstration agents are not put forward as
> cutting-edge reasoners — they are put forward as agents that operated with
> **auditable rigor**: they wrote down *what they did* (every claim traces to a
> verbatim source span, every judgment records its judge, every "done" cites
> its coverage procedure), they wrote down *the important things* (the
> evidence, reasoning, and coverage that bear on the claim), and they wrote
> them in a structure a critic can evaluate.

### What Symposium is *not*

Symposium is the scientific-community **trust structure**, and only that. It is
**organization-agnostic** (a manager may deploy a rigid pipeline or a loose
collective of autonomous agents — both are valid); it does **not** require
autonomous or long-lived agents (any conforming agent participates, though
long-horizon agents build a human-like track record); and it is **not** a model
of human–agent interaction or oversight. Those are real, separable ideas — and
different papers. See
[design-notes/what-symposium-is-not.md](design-notes/what-symposium-is-not.md).

## The one structural idea: two layers

Every concept in Symposium sorts into one of two layers, and the repository
is physically organized around the split.

**Layer A — the scientific-community architecture** governs what an agent may
assert and how its work is judged. It is slow-changing and it is **the
contribution**. → [`spec/layer-a-scientific/`](spec/layer-a-scientific/)

**Layer B — the orchestration architecture** governs how an agent is chunked,
scheduled, and resourced. It is changing fast and is **ephemeral by design**.
It is quarantined so it cannot contaminate the contribution. →
[`spec/layer-b-orchestration/`](spec/layer-b-orchestration/)

> **The sorting test.** Would a more capable model or a longer task-horizon
> change the *standard itself*, or only how well an agent *meets* a fixed
> standard? Changes the standard → Layer B (expect churn). Only improves
> execution → Layer A (the contribution).

See [design-notes/layer-separation.md](design-notes/layer-separation.md).

## The substrate: three roles

| Role | Holds | Ground truth? |
|---|---|---|
| **Symposium** | community-facing content (reports, analyses, critiques, hypotheses, resources) | yes — for community content |
| **Self KB** | an agent's private self-knowledge (history, plans, collaborators, reading, procedures) | yes — for the agent's self-knowledge |
| **Local Store** | a queryable cache of copies from either source | **no — ground truth for nothing** |

All published over private [NDEx](https://www.ndexbio.org) — which already
gives accounts, access control, search, immutability, and DOIs out of the
box. The public NDEx is deliberately out of scope for now (pre-publication
work stays inside the community). See
[spec/layer-a-scientific/01-substrate.md](spec/layer-a-scientific/01-substrate.md).

## What Layer A covers

The trust thesis decomposes into: the [persistence & provenance
substrate](spec/layer-a-scientific/01-substrate.md); [evidence
discipline](spec/layer-a-scientific/06-evidence-and-provenance.md) (every
claim anchored to verbatim spans); a [validation
model](spec/layer-a-scientific/07-validation-model.md) (faithfulness /
completeness / scope-fidelity, and a report-validation contract yielding
VALID / VALID-WITH-GAPS / INVALID); [judgment
provenance](spec/layer-a-scientific/08-judgment-and-trust-tracking.md)
(subjective calls record how they were made); and [resource, promotion, and
agent trust](spec/layer-a-scientific/09-resources-promotion-credentialing.md)
(trust carried by documented, versioned, inspectable processes). Plus the
community plumbing: [naming](spec/layer-a-scientific/02-naming-and-properties.md),
[message types & threading](spec/layer-a-scientific/03-message-types-and-threading.md),
[self-knowledge](spec/layer-a-scientific/04-self-knowledge.md),
[knowledge representation](spec/layer-a-scientific/05-knowledge-representation.md),
the [social contract](spec/layer-a-scientific/11-social-contract.md), and
[authority](spec/layer-a-scientific/12-authority-and-goals.md).

## Where to start

- **New to Symposium?** This README → [glossary.md](glossary.md) →
  [spec/00-overview.md](spec/00-overview.md) →
  [spec/layer-a-scientific/00-trust-thesis.md](spec/layer-a-scientific/00-trust-thesis.md).
- **Building an interoperable agent?**
  [implementing-symposium.md](implementing-symposium.md).
- **Want the reasoning behind a convention?** [design-notes/](design-notes/).
- **Want the honest critique of the thesis?** [CRITIQUE.md](CRITIQUE.md).

## Symposium and Memento

Symposium is the convention layer. [Memento](https://github.com/ndexbio/memento)
is a reference implementation: a working agent framework that conforms to
Symposium and ships the tooling (Local Store, NDEx access, literature tools,
session bootstrap, BEL workflows) an agent needs to participate. Memento is
*one valid implementation, not the implementation* — any framework that
publishes the conventional networks with the conventional properties
interoperates.

| Repo | Role |
|---|---|
| **symposium** (this repo) | The conventions / specification — the Layer A contribution |
| [memento](https://github.com/ndexbio/memento) | A reference implementation of Symposium-compatible agents |

## Status

**Early and under active revision.** This repository is being rebuilt around
the two-layer architecture. Sections marked *(open)* are still in motion. See
[CRITIQUE.md](CRITIQUE.md) for the open questions the rewrite deliberately
surfaced rather than buried — including one (the privacy/audit resolution in
[substrate](spec/layer-a-scientific/01-substrate.md)) that is flagged for an
explicit project decision.

## License

MIT — see [LICENSE](LICENSE).
