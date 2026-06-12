# Work Chunking (batch sizes, budgets, caps)

**Layer B — ephemeral.** Pure resourcing decisions about how much work an
agent attempts in one run. Every number here is expected to change as model
cost, throughput, and context size change.

## What this covers

- **Batch sizes** — e.g. "process 5 papers per run." Chosen so a run finishes
  within its budget, not because 5 is scientifically meaningful.
- **Time/compute budgets** — e.g. a ≤15-minute scheduled budget per run.
- **Tier caps** — orchestration-level limits on how much expensive work
  (deep reasoning mode, large analyses) a run may spend.

## The one rule that connects to Layer A

A batch size or budget must never become a silent excuse to lower a
scientific standard. If the budget does not allow the coverage procedure to
run across all source sections, the report is **VALID-WITH-GAPS**, not
"done" — the shortfall is recorded, never hidden. This is the **adequacy
rule** (see
[00-why-this-is-separate.md](00-why-this-is-separate.md) and
[validation-model §4.4](../layer-a-scientific/07-validation-model.md#44-the-layer-b-adequacy-rule)).

> Concretely: an agent that can only get through 3 of a paper's 5 sections in
> its budget does not report "complete." It reports what it covered, records
> the sections it did not reach as recorded negatives-it-could-not-run, and
> the verdict reflects the gap.

## Why these are not scientific

By the sorting test: a more capable model or a cheaper context would change
every number on this page — raise the batch size, drop the time pressure,
lift the tier cap — **without changing what makes a report trustworthy.** That
is the signature of orchestration. The batch size is how we afford the work;
the validation contract is what the work must meet.
