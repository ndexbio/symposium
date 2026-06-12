# Layer B — Orchestration

**Read this first.** Everything in this directory describes *how an agent is
run*, not *what makes its work trustworthy*. It is **ephemeral by design**.
Coherent-task horizons are climbing fast; today's batch caps, session
mechanics, and handoff tricks will be obsolete soon. The documents here exist
so implementers have a worked example to start from — **not** as part of the
contribution.

> **The hard rule: nothing in Layer B may leak into Layer A.** If a Layer A
> spec ever depends on a specific orchestration choice, that is a bug in the
> separation, and the fix is to lift the *standard* into Layer A and leave the
> *mechanic* here.

## The sorting test

> **Would a more capable model or a longer task-horizon change the *standard
> itself*, or only how well an agent *meets* a fixed standard?**
>
> - Changes the standard → **orchestration (Layer B)**. It belongs here and
>   it will churn.
> - Only improves execution of a fixed standard → **scientific (Layer A)**.
>   It belongs in the contribution, and the architecture's job is to record
>   *how well* it was met.

The refinement matters. A naïve version of the test ("would a better model
change this choice?") mis-sorts: a better model assigns evidence tiers more
accurately, but tiers are Layer A — capability improves the *assignment*, not
the *rule*. Sort on the **rule/standard**, not on **execution quality**. See
[CRITIQUE.md §8](../../CRITIQUE.md).

## What lives here

| Concern | Document | Why it churns |
|---|---|---|
| Session lifecycle (`init`/`work`/`close`, registry, orphan sweep) | [01](01-session-lifecycle.md) | "Session" is a resourcing primitive, not a unit of scientific meaning |
| Work chunking (batch sizes, time budgets, tier caps) | [02](02-work-chunking.md) | Pure resourcing; changes with model cost and throughput |
| Context management & handoff | [03](03-context-handoff.md) | Tied to context-window size, which is growing |
| Agent archetypes by lifecycle | [04](04-agent-archetypes.md) | Batch-vs-resident is a deployment fact, not a scientific one |

## The adequacy rule — the one place the layers touch honestly

Layer A standards sometimes *presume* Layer B resourcing. The completeness
standard requires that a coverage procedure "has been run across all source
sections" — but whether the agent *can* run it depends on batch size, time
budget, and whether the whole source was ever in context. That dependency is
real. The separation does not deny it; it **surfaces** it, and resolves it
with one rule:

> **Layer A defines the standard. Layer B must be *adequate to* the standard.
> Where orchestration cannot afford the standard, the result is
> VALID-WITH-GAPS — never silently "done."**

So a starved run does not get to *lower* the scientific bar; it gets to honestly
report that it could not *reach* it. The standard stays in Layer A; the
shortfall is recorded, not hidden. See
[validation-model §4.4](../layer-a-scientific/07-validation-model.md#44-the-layer-b-adequacy-rule)
and [CRITIQUE.md §7](../../CRITIQUE.md).

## How to read the rest of this directory

Treat every mechanic described here as *"how we happened to run the demo."*
When the project re-runs on a longer horizon or a resident architecture,
these documents are expected to be rewritten wholesale — and **none of Layer
A should change when they are.** That invariance is the test of whether the
separation is clean.
