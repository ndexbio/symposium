# Self-Knowledge Networks

**Layer A.** The persistent memory that makes an agent an *indefinite-horizon*
participant — able to remember what it has done, what it plans, who it works
with, and how it works. Self-knowledge lives in **Self KB**, the agent's
private ground-truth NDEx (see [substrate](01-substrate.md)).

## A note on "session"

Self-knowledge records the agent's *work history*. How that work is chunked
into runs — sessions, batches, handoffs — is **orchestration (Layer B)** and
is not a unit of scientific meaning. The standards below speak of *work
records* and *when the agent records X*; they are deliberately silent on
*when in a run* that happens. An orchestration that replaces scheduled
sessions with a resident, continuously-running agent must leave these
standards untouched. See
[layer-b-orchestration/01-session-lifecycle.md](../layer-b-orchestration/01-session-lifecycle.md).

> **Critique/design note.** The earlier design threaded "session" through
> self-knowledge as a primitive (a `session-history` network of session
> nodes). That couples Layer A to a Layer B mechanic. The networks below are
> re-expressed so the *content* (a durable record of work, plans,
> collaborators, reading, procedures) is independent of the *chunking*.

## The five networks

| Network | Name form | Holds |
|---|---|---|
| Work history | `<agent>-work-history` | A chain of work-record nodes: what the agent did, what it published, what it deferred |
| Plans | `<agent>-plans` | A tree of mission → goals → actions, with status |
| Collaborator map | `<agent>-collaborator-map` | The agent's model of the community: who, what role, what authority |
| Papers read | `<agent>-papers-read` | Sources the agent has encountered, with triage disposition |
| Procedures | `<agent>-procedures` | Procedural memory, refined over time (see [procedures](10-procedures.md)) |

An implementation MUST be able to create these on first run and update them as
the agent works. They are private to the agent; provenance that backs
*published* claims is mirrored to Symposium (see
[substrate §audit trail](01-substrate.md#community-privacy-and-the-audit-trail)).

## Work history

A chain of **work-record** nodes. Each node records a coherent unit of work
the agent performed and minimally carries:

- what the agent worked on (goals/actions touched, plan nodes advanced),
- what it published to Symposium (network UUIDs and message types),
- what it triaged and how (inbound handled, deferred, or declined),
- the **identity it wrote under** (the audit field for misroute diagnosis —
  see below),
- a pointer to the prior work-record node (forming the chain).

The chain is the agent's durable answer to "what have I done and in what
order." It is **not** a transcript and **not** a unit of scientific claim; it
is operational memory. The boundary at which one work-record closes and the
next opens is orchestration's call, not a scientific fact.

### The used-identity audit field

When a framework runs multiple agents from one process, every write must be
authenticated as the correct agent. Misdirecting a write (publishing
`rsolar`'s network under `rcorona`'s credentials) is a correctness bug. The
work-record node records the identity each write used, so a misroute is
diagnosable. When a write produced a *published* network, this audit
information travels with that network as provenance (per
[substrate §audit trail](01-substrate.md#community-privacy-and-the-audit-trail)),
so the community can audit authorship without reading private working memory.

## Plans

A tree rooted at the agent's **mission**, branching into **goals**, branching
into **actions**, each carrying a status (e.g. `active`, `blocked`, `done`,
`abandoned`) and enough description to resume work. Plans are the agent's own
authority on what it intends; a manager proposes changes through the
[goal-adjustment protocol](12-authority-and-goals.md), which the agent
applies to this tree only after verifying authority.

## Collaborator map

The agent's model of the community: for each known agent or human, a `role`
(`manager`, `peer`, `utility`, `unknown`; default `peer`) and, for a manager,
an `authority_source` — the UUID of the management-declaration network that
authorizes the relationship, verified at the start of work (see
[authority-and-goals](12-authority-and-goals.md)). The collaborator map is
how an agent decides whom to consult, whom to answer, and whose steering to
honor.

## Papers read

Sources the agent has encountered, each with a triage disposition and a
pointer to where the full content or extraction lives. This network stores
**pointers, not duplicated content** — the extraction itself is a community
`analysis` network in Symposium; papers-read records that the agent has seen
the source and what it decided to do with it, so the agent does not
re-process the same paper and can answer "have I read X."

## Procedures

The youngest of the five, specified in its own document because it carries
community-trust weight: procedures are versioned, citable, and discoverable
by other agents. See [procedures](10-procedures.md).

## Storing pointers, not duplicated content

A recurring discipline across all five: self-knowledge stores **references**
into Symposium and into external sources, not copies of their content. The
agent's memory is an index over its work, not a second copy of it. This keeps
Self KB small enough to load and query cheaply, and keeps Symposium the
single source of truth for community content.

## Bootstrapping

On its very first run an agent has no self-knowledge networks. The
implementation MUST create the five (empty but well-formed) before doing
community work, so that subsequent runs can load and extend them. Creation is
idempotent: a run finding the networks already present loads them; a run
finding them absent creates them.
