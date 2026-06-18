# Scope and Terminology — Symposium vs. the Runtime

Symposium and the agent runtime are **two different things**, and conflating them
causes real confusion as the runtime gets used for work that has nothing to do
with Symposium. This document fixes the boundary.

## The two layers

- **Symposium** is a **trust contract**. It is the set of requirements in this
  repository — the trust thesis, evidence tiers, the validation model, judgment
  provenance, the resource/promotion/credentialing model — together with the
  **role behavioral specifications** (each a *trust envelope*: remit,
  prohibitions, evidence discipline, validation surface, consultation
  obligations, trust semantics) and the **NDEx CX2 artifact contracts** they
  publish to a shared commons. Symposium is about *how scientific claims earn
  trust* and *what a downstream consumer may rely on*.

- **Memento** is an **agent runtime/framework**: it specifies how an agent is
  *run* — lifecycle, memory, batching, scheduling, tool and NDEx mechanics. It
  runs **any** task given to it. Nothing about Memento is inherently scientific,
  and most of what a Memento agent file specifies is deliberately **out of scope**
  for Symposium.

  **Dockerization is a deployment convenience, not part of what Memento is.**
  Running Memento agents as docker containers is a convenient and common strategy,
  but it is **not definitional** and does **not preclude other run strategies** —
  a Memento agent need not be dockerized. So there are three distinct levels, not
  two: the *Symposium trust contract*, the *Memento runtime/framework*, and
  *dockerization* as one (convenient, optional) way to deploy Memento.

## The two are orthogonal

A **Symposium agent** is any agent that operates under the Symposium
requirements: it fills a role's trust envelope and publishes the role's CX2
artifacts to the commons, regardless of what runtime executes it.

These two properties are **independent axes**:

|  | **Symposium agent** | **not a Symposium agent** |
|---|---|---|
| **runs on Memento** | e.g. the `dscout` extractor (a Memento agent *and* a Symposium role) | a Memento agent doing ordinary software/engineering work — no trust contract, no commons |
| **runs on another runtime** | a Symposium role implemented on a different stack | unrelated |

So:

- **Not every Memento agent is a Symposium agent.** Memento is used for
  non-Symposium, non-science tasks that do not follow the scientific-method
  discipline these requirements encode. Such agents are outside this repository's
  scope and make **no** Symposium trust claims.
- **Not every Symposium agent need run on Memento.** A role spec is a runtime-
  agnostic contract; Memento is the *current* runtime, not a requirement of the
  contract.

## How this shows up in the specs

Every role behavioral specification states its scope as **Symposium-level**: it
defines the trust envelope and the CX2 contract, and explicitly leaves *how the
role is run* (session lifecycle, retrieval budgets, NDEx mechanics) to a runtime
agent file — e.g. a Memento agent. When a spec says "this lives in the Memento
agent file," it means *that detail is runtime orchestration, not part of the
Symposium trust contract* — and a different runtime would supply its own.

## Naming guidance

- Say **"Symposium agent"** (or "Symposium role") when the trust contract is what
  matters: evidence discipline, validation, provenance, commons artifacts.
- Say **"Memento agent"** when the runtime is what matters: how the agent is
  containerized, scheduled, given memory, or wired to tools.
- Do **not** use "Memento agent" and "Symposium agent" interchangeably, and do
  not assume a dockerized agent follows the scientific-method discipline of these
  requirements unless it is explicitly operating as a Symposium role.
