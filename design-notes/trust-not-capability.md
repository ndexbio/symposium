# Trust, not Capability — and Why Capability is Instrumented

Symposium's banner is *trust, not capability*: the demonstration agents are
not put forward as cutting-edge reasoners but as agents that operated
*trustworthily*. This note defends the banner, explains the one way the
naïve version of it is wrong, and states the stronger form the spec actually
adopts.

## Why "trust, not capability" is the right banner

The slogan does essential work: it separates the contribution from the churn
of model progress. If the claim were "our agents reason better," it would be
obsolete the moment a better model shipped — and it would be competing,
badly, with every frontier lab. By contrast, "our community makes agent work
*trustworthy*" is a claim about architecture, not about any model, and it
stays true as the models underneath improve. Any agent, on any model, can
participate if it follows the standards. That is the durable contribution.

It also correctly identifies the actual bottleneck. Agents already produce
scientific artifacts faster than humans can review them; the limiting factor
is not raw capability but **trust at agent speed across organizational
boundaries**. Science's existing trust apparatus (peer review, replication,
credentialing) has no counterpart that runs that fast. Building one is the
problem worth solving.

## Where the naïve version is wrong

Taken literally, "trust, *not* capability" implies the two are separable — that
you can hold capability aside and talk about trust alone. You cannot, and the
architecture's own mechanisms prove it:

- **Completeness is capability-bound.** "Did the agent find every dataset?" has
  no mechanical answer. A coverage procedure run by a weak agent yields a
  "documented process trusted to a degree" — and the degree is low precisely
  because the agent is weak. The trust you can extend tracks capability.
- **Judge-provenance is capability tracking.** The reason a judgment records
  the model and reasoning mode of the agent that made it is so a later, more
  capable agent can decide whether to re-review. That is capability treated as
  a first-class trust parameter — inside the trust model, not outside it.

So the dichotomy leaks. If the spec insisted on "trust, not capability" as
written, an attentive reviewer would catch the leak and the whole framing
would look naïve.

## The stronger form the spec adopts

> **Trust is the contribution; capability is a parameter the trust
> architecture makes *legible and auditable*.**

The architecture's distinctive move is not to *bracket* capability but to
*instrument* it: every judgment carries the provenance of its judge, so the
community can see exactly how capable the agent behind each call was and
revise trust accordingly. This is strictly stronger than the slogan — it owns
that capability matters, and it shows the architecture's job is to make
capability *trackable* rather than to pretend it is irrelevant.

The demonstration agents can then be modest reasoners and still make the
point, because the point is no longer "they reason well" but "however well
they reason, you can see it, audit it, and re-check it." See
[spec/layer-a-scientific/00-trust-thesis.md](../spec/layer-a-scientific/00-trust-thesis.md)
and [CRITIQUE.md §1](../CRITIQUE.md).

## Not a safety multiple — auditable rigor

A tempting framing: self-driving cars must be *much* safer than humans to earn
adoption, so agent output must be *much* more rigorous than human output to be
trusted. It is catchy and it is wrong. "Much safer" is a measured multiple over
a well-characterized baseline (human crash rates), enforced by a feature agent
science lacks: crashes are loud, countable, and immediate. Scientific
extraction failures are quiet and compounding, and there is no agreed error
rate for "a typical human scientist's literature extraction." So "much more
rigorous than human output" has no denominator, and a project that *disclaims*
quantitative evaluation in its first phase cannot lean on a quantitative
analogy. The analogy is withdrawn.

The right concept is **auditable rigor**, in three parts:

> - **Auditable** — the agent wrote down *what it did*: every claim traces to a
>   verbatim span, every judgment records its judge, every "done" cites its
>   coverage procedure.
> - **Rigor** — the agent wrote down *the important things*: the evidence,
>   reasoning, judgment, and coverage that bear on whether the claim holds —
>   not a raw transcript.
> - **Evaluable structure** — it wrote them down in a form a critic can run a
>   contract against.

Auditability without rigor is an unusable transcript; rigor without
auditability is an uncheckable claim of diligence; either without an evaluable
structure cannot be judged at scale. The defensible asymmetry with ordinary
output is not a safety multiple — it is *work whose rigor you can audit
claim-by-claim, structured so the audit can actually be run.* See
[CRITIQUE.md §2](../CRITIQUE.md).
