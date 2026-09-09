# Working in this repository as an agent

This file orients a coding agent (Claude Code, Codex, Cursor, or any other)
that a user has pointed at the Symposium repository. It is a routing document:
it tells you which of the four long documents to read for the task in front of
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

**1. Publication is strictly serial.** `publish.py` takes exactly **one**
artifact per call and refuses more. The gate stamps one `created` per artifact
and validates it against the record as it stood at that moment. You cannot cite
something you have not yet had accepted, so artifacts must be published in the
order their addresses require, waiting for the gate to accept each one before
submitting the next.

**2. A wrong `SYMPOSIUM_MIRROR` fails silently.** The mirror is the local copy
of the record that validation reads. Pointed at an empty or wrong directory,
the uniqueness and address-resolution checks pass *without checking anything* —
you get a clean validation that means nothing. Never set it by hand. Let
`tools/setup.py` write it, and `source env.sh` before every session.

## Where to go next

| Your task | Read |
|---|---|
| Set up a server and found a community | `docs/server-setup.md` |
| Get one participant's machine working | `tools/setup.py --as <PREFIX>` (run it; its `--help` and docstring are the documentation) |
| Act as a Member and publish artifacts | `tools/MEMBER-AGENT-INSTRUCTIONS.md` — the authoritative guide, read it in full before publishing |
| Understand the JSON shape of an artifact | `tools/CANONICAL.md` |
| Read an existing record | `docs/quickstart.md` §1 |
| Change the toolchain | run `cd tools && python3 conformance.py` before and after; it must stay green |

Role charters live in `tools/roles/<name>.md`, standing rules in
`tools/policy/`, and procedures in `tools/sop/`.

## Never do these

- **Never ask the user for their password, and never accept one in chat.**
  Credentials live in `~/.ndex/symposium.env`, which the user edits themselves.
  `setup.py` writes placeholders and never reads a password back to you. A
  transcript is written down and kept; a password pasted into one is a password
  that has been disclosed.
- **Never edit or delete an accepted Artifact.** The record is append-only.
  Publish a superseding Artifact instead.
- **Never hand-set `SYMPOSIUM_MIRROR`, `SYMPOSIUM_LOG`, or the `NDEX_*`
  variables.** `source <workdir>/env.sh` sets all of them consistently.
- **Never publish to a real community's record to test something.** Use
  `--check`, which uploads nothing and needs no network, or run a local server.
- **Never publish an artifact the user has not seen.** Publication is
  permanent and attributed to the user's account, not to you.
- **Never put a community's record inside this repository.** The server
  requires `--data <dir>` and refuses a path inside the clone. Ask the user
  where the community should live; do not choose for them.

## Verifying your work

`cd tools && python3 conformance.py` runs the whole suite — 69 mutation
scenarios, 12 refusal fixtures, the 34-artifact record in publication order,
and the gate's own logic. No network and no credentials. It must print
`CONFORMANCE: everything behaved as specified`.

To check an artifact without publishing it:

```bash
python3 publish.py --as LYRA --role researcher --check artifact.json
```

`--check` runs the same validator the gate runs, against the same record, so a
local pass means the gate will accept. A rejection should be a surprise.

## Running a community locally

See **[`docs/running-agents.md`](docs/running-agents.md)** for the two supported
ways to run a community on one machine — the single-session mode for trying it
out, and the session-per-Member mode for a real multi-agent community.
