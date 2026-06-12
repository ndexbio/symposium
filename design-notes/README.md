# Design Notes

Rationale behind specific conventions. Where [`spec/`](../spec/) says *what* a
convention is, design-notes say *why*. These are descriptive, not normative —
for implementers weighing whether to deviate, reviewers auditing the spec, and
future contributors revisiting decisions.

For the honest adversarial reading of the *thesis* (as opposed to the
rationale for individual conventions), see [CRITIQUE.md](../CRITIQUE.md).

## Contents

| Document | Topic |
|---|---|
| [layer-separation.md](layer-separation.md) | Why the whole repo splits into Layer A (contribution) and Layer B (ephemeral orchestration) |
| [trust-not-capability.md](trust-not-capability.md) | Why the contribution is trust, and why capability is instrumented rather than bracketed |
| [substrate-three-roles.md](substrate-three-roles.md) | Why Symposium / Self KB / Local Store, and why Local Store is ground truth for nothing |
| [community-privacy.md](community-privacy.md) | Why self-knowledge is private under containerization, and how the audit trail survives that |
| [completeness-as-defensible-standard.md](completeness-as-defensible-standard.md) | Why "done" is a documented, defensible standard rather than a proof |
| [conventions-not-ontologies.md](conventions-not-ontologies.md) | Why Symposium is a convention layer, not a schema — and how the validation contract coexists with that |
| [formal-and-freeform.md](formal-and-freeform.md) | Why formal vocabularies and freeform claim nodes are equal, complementary modes |

## When to add a new design note

When a convention is non-obvious enough that an implementer might reasonably
deviate. A note states the convention briefly, states the alternative that
would seem natural, and states why the alternative was rejected — usually in
terms of a concrete failure mode or trade-off observed in practice. Design
notes change only when the *rationale* changes, more slowly than the spec
itself.
