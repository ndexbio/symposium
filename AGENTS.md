# Working in this repository as an agent

This file orients a coding agent (Claude Code, Codex, Cursor, or any other)
that a user has pointed at the Symposium repository. It is a routing document:
it tells you which of the long documents to read for the task in front of
you, and it records the two things that most often go wrong.

Read this first, then read exactly one of the documents in **Where to go next**.
Do not read all of them; they are long and only one is relevant to any one task.

## What this repository is

Symposium is a specification and toolchain for a **CommunityRecord**: an
append-only graph in which members of a scientific community publish immutable
Artifacts, and every claim is connected to the material it rests on. Nothing is
ever edited or deleted. A correction is a new Artifact that supersedes the old
one, and the old one stays.

`spec/symposium_specification.md` is the normative document. Everything under
`tools/` is the reference implementation.

## Two things that will bite you

**1. Publication is strictly serial.** `/symposium publish` takes exactly **one**
artifact per call and refuses more. The gate stamps one `created` per artifact
and validates it against the record as it stood at that moment. You cannot cite
something you have not yet had accepted, so artifacts must be published in the
order their addresses require, waiting for the gate to accept each one before
submitting the next.

**2. Every command works in the current directory.** `/symposium setup` (a
member) or `/symposium bootstrap` (the admin) sets the session's context in its
working directory, and `./record` beside it is that session's copy of the
record. Run a command from another directory and it works for another session,
or stops and names `setup` and `bootstrap`. Each agent session keeps to its own
directory.

## Where to go next

| Your task | Read |
|---|---|
| Set up a server and found a community | [`skills/symposium/README.md`](skills/symposium/README.md) §2, then [`data-server/RUNBOOK.md`](data-server/RUNBOOK.md) |
| Get one participant's machine working | Install the `symposium` skill (`make deploy-local`), then `/symposium setup --invite-file <file>`; see [`skills/symposium/`](skills/symposium/README.md) |
| Act as a Member and publish artifacts | `tools/MEMBER-AGENT-INSTRUCTIONS.md` — the authoritative guide, read it in full before publishing |
| Work out what a dataset can support, before anyone argues from it | `tools/roles/reader.md` — run it after the import and before the analysis |
| Understand the JSON shape of an artifact | `tools/CANONICAL.md` |
| Run the gate as the admin | `/symposium gate`, once per submission it is told about, or `/symposium gate --watch` to keep deciding until stopped |
| Read an existing record | `/symposium serve <record dir>`, for example `examples/record` |
| Change the toolchain | run `make lint` before and after; it must stay green |
| Understand `examples/` | [`examples/README.md`](examples/README.md) — these are test fixtures, not samples |

Role charters live in `tools/roles/<name>.md`, standing rules in
`tools/policy/`, and procedures in `tools/sop/`.

## Never do these

- **Never ask the user for a key, an invite or a credential, and never accept
  one in chat.** A member's key is made on their machine by `/symposium setup`
  and stays in its keystore; invite files and credentials files move only as
  files. A transcript is written down and kept; a secret pasted into one has
  been disclosed.
- **Never edit or delete an accepted Artifact.** The record is append-only.
  Publish a superseding Artifact instead.
- **Never edit `./.symposium/context.json` or `./record` by hand.** `setup` or
  `bootstrap` writes the context, and `sync` (or the gate) keeps the record copy.
- **Never publish to a real community's record to test something.** Use
  `/symposium validate`, which uploads nothing, or a community on a local data
  server.
- **Never publish an artifact the user has not seen.** Publication is
  permanent and attributed to the user's account, not to you.
- **Never delete or edit anything under `examples/`.** Despite the name it is
  the conformance suite's fixture data: `examples/record/` is validated in
  publication order and `examples/refused/` holds Artifacts that must be
  refused for named reasons. Copy them elsewhere to experiment.
- **Never run a community's sessions inside this repository.** Each session
  works in its own directory, which holds its context and its copy of the
  record. Ask the user where the sessions should live; do not choose for them.

## Verifying your work

`make lint` runs the conformance suite — the mutation scenarios, the refusal
fixtures, the example record in publication order, the gate's ordering and the
record browser. No network and no credentials. It must print
`CONFORMANCE: everything behaved as specified`.

To check an artifact without publishing it:

```bash
/symposium validate --role researcher artifact.json
```

It runs the same validator the gate runs, against the current record, so a
pass means the gate will accept. A rejection should be a surprise.

## Running a community

The skill's [`README.md`](skills/symposium/README.md) covers deploying a data
server, bringing a community up as its admin, joining it as a member, and the
everyday commands. Each agent session works in its own directory.
