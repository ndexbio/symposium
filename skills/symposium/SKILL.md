---
name: symposium
description: Work in a Symposium community on a Symposium Data server — join it as a member (setup), bring it up as its admin (bootstrap), manage its members and data, and port, export or import a community. Use whenever the user mentions Symposium, a community record, an invite file, community.json, or the symposium-data CLI.
---

# Symposium

Symposium is a specification and toolchain for a **community record**: an append-only graph in
which members of a scientific community publish immutable artifacts, each connected to the
material it rests on. The record and its files live on a **Symposium Data server**; this skill
reaches it only through the `symposium-data` CLI, which must be on `PATH`.

Run every command as `/symposium <command>`, that is
`python3 <this skill>/scripts/main.py <command> [options]`. Each prints one JSON object. Never
run a tool script or the CLI by hand, and never ask for or accept a password, key or invite in
the chat: they move only as files.

## First, in every agent session: `setup` or `bootstrap`

Every other command works in the **context** of one community, set in the session's working
directory. Run one of these first; a command run without a context says which.

- **Members:** `/symposium setup --invite-file <file>`. The invite file comes from the admin,
  out of band; it names the community, the handle and the server. Setup makes the member's key
  on this machine and registers it. Running it again is harmless.
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
| `admin-config --handle <h> --data-server-url <url> [--new-key]` | admin | make or reuse the server's admin key, and print where to place it |
| `roster list\|add\|remove`, `invite`, `rebind-key`, `suspect-after`, `purge`, `export`, `import` | admin | manage members and data |
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
