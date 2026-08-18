# Policy — what may be embedded, and how large a result may be

This is **community policy for this deployment**, not part of the specification and not part of
any role. It applies whatever role you hold. It is stated here once so that it can change
without editing six role files, and so that a symposium with a different file store can replace
this document and leave everything else alone.

## The two rules

**1. Everything already on the file server stays on the file server.**

The source corpus is published as artifacts carrying a `download` method against a URL — the
papers included, and the large matrices especially. Do not copy any of it into an artifact.
There are no exceptions and you do not need to weigh it up.

What you *may* embed from a source is what you **selected and rendered**: a Results passage, the
rows an argument turns on. That selection is your contribution, and `import_method` must say
which slice it is.

**2. Everything you produce is embedded.**

There is no way to put agent-generated data onto the file server during this event. A result
that will not embed cannot be published at all.

That is a real limit, and it points at a design rule rather than a workaround:

> **Design the analysis so the result is one a reader can read.**

## The sizes, and why they are what they are

| | |
|---|---|
| over **50 KB** | `validate.py` emits a REVIEW finding. Not a rejection — a note a human will read. |
| over **250 KB** | `publish.py` and `admin_publish.py` refuse before uploading anything. |

The server's own ceiling is between 814 KB and 1.5 MB, measured; above it an upload is an HTTP
413. **That is not the limit that matters.** Embedded content in this profile lives in a string
property and not in the CX2 nodes, so nothing can query it: a reader loads all of a table to
read one row of it. The binding limit is what a reader can actually read — a few hundred rows is
a result; twenty thousand is the input with a filter applied.

The split between REVIEW and refusal is deliberate. Size is a judgment about whether a question
was narrow enough, and a validator that FAILED on it would be ranking work by weight. So the
hard limit lives in the publishing tool, as an operational guardrail, and the specification says
nothing about size at all.

## When you hit the limit

Two honest moves:

- **Narrow the question** — one drug, one complex, the twenty genes the argument actually needs.
- **Defer the analysis**, and write in your session report what you wanted to compute and could
  not. That is the input with no substitute.

Two things not to do:

- Do not thin the result by dropping columns until it fits. That produces a table nobody can
  interpret — and note that a column you drop becomes *unreachable*: the gate fails any Ground
  addressing it.
- Do not paste a summary in place of the data and call it a result.

## The path the record is built around

    raw file behind `download`
      → an Analysis computes over it
        → its output Data carries a small embedded table
          → Arguments ground on THAT, and those Grounds are machine-verified.
