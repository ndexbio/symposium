---
name: symposium
description: Work in a Symposium community on a Symposium Data server — join it as a member (setup), bring it up as its admin (bootstrap), publish artifacts and keep a copy of the record (publish, validate, sync, serve), decide submissions as its admin (gate), manage its members and data, and port, export or import a community. Use whenever the user mentions Symposium, a community record, an invite file, community.json, or the symposium-data CLI.
---

# Symposium

Symposium is a specification and toolchain for a **community record**: an append-only graph in
which members of a scientific community publish immutable artifacts, each connected to the
material it rests on. The record and its files live on a **Symposium Data server**; this skill
reaches it only through the `symposium-data` CLI, which must be on `PATH`.

Run every command as `/symposium <command>`, that is
`python3 <this skill>/scripts/main.py <command> [options]`. `publish`, `validate`, `sync`,
`gate` and `serve` print a free-text report, and their exit code is the result (0 = done);
every other command prints one JSON object. Never run a tool script or the CLI by hand, and never ask for or accept a password, key or invite in
the chat: they move only as files.

## First, in every agent session: `setup` or `bootstrap`

Every other command works in the **context** of one community, set in the session's working
directory. Run one of these first; a command run without a context says which.

- **Members:** `/symposium setup --invite-file <file>`. The invite file comes from the admin,
  out of band; it names the community, the handle and the server. Setup makes the member's key
  on this machine, registers it, and syncs `./record`. Running it again is harmless.
- **Admins:** `/symposium bootstrap --community <community.json>`. It validates the file,
  checks the server and this machine's admin key, creates the community if needed, adds every
  handle to the roster, and writes one `<community>-<handle>.invite` file per pending invite,
  to hand over out of band. Running it again only adds.

Several agents on one machine each work in their own directory, with their own context.

## Commands

| Command | Who | What |
|---|---|---|
| `setup --invite-file <file>` | member | join the community |
| `bootstrap --community <file>` | admin | bring the community up; write invite files |
| `publish [--role <role>] <artifact.json>` | member, admin | sync, validate against the record as it stands, then submit to the gate; `--roles` lists the roles |
| `validate [--role <role>] <artifact.json>` | member, admin | the same checks as `publish`, submitting nothing (`publish --check`) |
| `sync [--watch]` | member, admin | bring `./record`, this session's copy of the record, up to date; list the gate's replies to you |
| `gate [--dry-run\|--verify\|--rebuild]` | admin | accept or reject the submissions waiting in `inbox`; `--verify` compares `./record` with the record, `--rebuild` rebuilds the gate's caches from the server |
| `serve [--port N]` | anyone | browse `./record` at `http://localhost:8760`, rebuilt as it changes |
| `admin-config --handle <h> --data-server-url <url> [--new-key]` | admin | make or reuse the server's admin key, and print where to place it |
| `roster list` | member, admin | the community's roster |
| `roster add\|remove`, `invite`, `rebind-key`, `suspect-after`, `purge`, `export`, `import` | admin | manage members and data |
| `port <ndex_credentials_file> <ndex_url>` | admin | port a community's record (port-ndex; see `reference/PORT_NDEX.md`) |
| `data <symposium-data command …>` | anyone | direct data work: `put`, `get`, `version`, `delete`, `keys`, `collection`, `find`, `verify`, `changes`, … |

`/symposium data <command> --help` describes any CLI command and its options.

## What to read for the task in front of you

Read exactly one of these; they are long.

| Your task | Read |
|---|---|
| Act as a member and publish artifacts | [`toolchain/tools/MEMBER-AGENT-INSTRUCTIONS.md`](toolchain/tools/MEMBER-AGENT-INSTRUCTIONS.md) |
| Play a role (reader, analyst, critic, …) | [`toolchain/tools/roles/`](toolchain/tools/roles/README.md) |
| Follow a standing rule | [`toolchain/tools/policy/`](toolchain/tools/policy/) |
| Follow a procedure | [`toolchain/tools/sop/`](toolchain/tools/sop/) |
| Understand what the record is | [`toolchain/spec/symposium_specification.md`](toolchain/spec/symposium_specification.md) |
| Run or deploy a data server, port, export or import | [`README.md`](README.md) |
