---
name: symposium
description: Work in a Symposium community on a Symposium Data server — join it as a member (setup), bring it up as its admin (bootstrap), publish artifacts and keep a copy of the record (publish, validate, sync, serve), decide submissions as its admin (gate), manage its members and data, and port, export or import a community. Use whenever the user mentions Symposium, a community record, an invite file, community.json, or the symposium-data CLI.
---

# Symposium

Symposium is a specification and toolchain for a **community record**: an append-only graph in
which members of a scientific community publish immutable artifacts, each connected to the
material it rests on. The record and its files live on a **Symposium Data server**; this skill
reaches it only through the `symposium-data` CLI, which ships inside it. The skill runs the CLI
in its own Python environment, which the first command of a session prepares; the host needs
only Python 3.9+.

Run every command as `/symposium <command>`, that is
`python3 <this skill>/scripts/main.py <command> [options]`. `publish`, `validate`, `sync`,
`gate` and `serve` print a free-text report, and their exit code is the result (0 = done);
every other command prints one JSON object. Never run a workflow tool or the CLI by hand: `/symposium` runs them. Never ask for or accept a password, key or invite in
the chat: they move only as files.

## First, in every agent session: `setup` or `bootstrap`

Every other command works in the **context** of one community, set in the session's working
directory. Run one of these first; a command run without a context says which.

- **Members:** `/symposium setup --invite-file <file>`. The invite file comes from the admin,
  out of band; it names the community, the handle and the server. Setup makes the member's key
  on this machine, registers it, and syncs the session's `record/`. Running it again is harmless.
- **Admins:** `/symposium bootstrap --community-file <community.json>`. It validates the file,
  checks the server and this machine's admin key, creates the community if needed, adds every
  handle to the roster, and writes one `<community>-<handle>.invite` file per pending invite,
  to hand over out of band. Running it again only adds.

Sessions are kept by the skill under `~/.symposium/` (`admin/<community>/` for the admin, `member/<community>/<handle>/` for a member), so commands work from any directory. `setup` and `bootstrap` make the session they create the current one for the agent session that runs them; `/symposium use <community> <handle>` switches to another, and `/symposium use` alone lists them all. Every other command works in the current session (or, when the agent session has chosen none, the machine's only one). Each agent session keeps its own choice, so several agents on one machine never change each other's. Every command names the session it worked in (`session` in its JSON, or a first line `session: <community>/<handle>`).

## Commands

| Command | Who | What |
|---|---|---|
| `setup --invite-file <file>` | member | join the community |
| `bootstrap --community-file <file>` | admin | bring the community up; write invite files |
| `use [<community> <handle>]` | anyone | make that session this agent session's current one; alone, list every session |
| `publish [--role <role>] <artifact.json>` | member, admin | sync, validate against the record as it stands, then submit to the gate; `--roles` lists the roles; the admin publishes as `operator` unless it gives `--role` (`--role none`: no limit) |
| `validate [--role <role>] <artifact.json>` | member, admin | the same checks as `publish`, submitting nothing (`publish --check`) |
| `sync [--watch]` | member, admin | bring the session's `record/`, its copy of the record, up to date; list the gate's replies to you; `--watch` keeps running (see below) |
| `gate [--dry-run\|--verify\|--rebuild\|--watch]` | admin | accept or reject the submissions waiting in `inbox`; `--verify` compares the session's `record/` with the record, `--rebuild` rebuilds the gate's caches from the server, `--watch` runs a pass every `SYMPOSIUM_POLL` seconds (default 30) and keeps running (see below) |
| `serve [<record dir>] [--port N]` | anyone | browse the session's `record/` (or the record directory given) at `http://localhost:8760`, rebuilt as it changes; keeps running (see below) |
| `admin-config --handle <h> --data-server-url <url> [--new-key]` | admin | make or reuse the server's admin key, and print where to place it |
| `roster list` | member, admin | the community's roster |
| `roster add\|remove`, `invite`, `rebind-key`, `suspect-after`, `purge`, `export`, `import` | admin | manage members and data |
| `port <ndex_credentials_file> <ndex_url>` | admin | port a community's record (port-ndex; see `reference/PORT_NDEX.md`) |
| `data <symposium-data command …>` | anyone | direct data work: `put`, `get`, `version`, `delete`, `keys`, `collection`, `find`, `verify`, `changes`, … |

`/symposium data <command> --help` describes any CLI command and its options.

## Commands that keep running

`gate --watch`, `sync --watch` and `serve` run until they are stopped. For each one:

- **Start it in the background**, so the conversation stays usable while it runs.
- **Show the user every line it prints, as it appears,** for as long as it runs: follow its
  output and relay each new line into the conversation. Output the user is not shown is a
  fault; for `gate --watch`, each line is a decision the admin must see.
- **Tell the user it is running,** and that they stop it by asking you; stop it when they ask.

Each one also stops on its own, with a last line saying so, when the agent session that started
it ends.

## What to read for the task in front of you

Read exactly one of these; they are long.

| Your task | Read |
|---|---|
| Act as a member and publish artifacts | [`toolchain/tools/MEMBER-AGENT-INSTRUCTIONS.md`](toolchain/tools/MEMBER-AGENT-INSTRUCTIONS.md) |
| Play a role (reader, analyst, critic, …) | [`toolchain/tools/roles/`](toolchain/tools/roles/README.md) |
| Follow a standing rule | [`toolchain/tools/policy/`](toolchain/tools/policy/) |
| Follow a procedure | [`toolchain/tools/sop/`](toolchain/tools/sop/) |
| Understand what the record is | [`toolchain/spec/symposium_specification.md`](toolchain/spec/symposium_specification.md) |
| See what correct and refused artifacts look like | [`toolchain/examples/`](toolchain/examples/README.md) |
| Check a record directory or artifacts against the specification | [`toolchain/tools/validate_record.py`](toolchain/tools/validate_record.py) (a record directory, in publication order) and [`toolchain/tools/check_refused.py`](toolchain/tools/check_refused.py) (artifacts that must be refused) |
| Check that this toolchain behaves as specified | [`toolchain/tools/conformance.py`](toolchain/tools/conformance.py), run from `toolchain/tools/` |
| Run or deploy a data server, port, export or import | [`README.md`](README.md) |
