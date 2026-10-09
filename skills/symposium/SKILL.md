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
| `gen-api-key <label>`, `list-api-keys`, `revoke-api-key <key id>` | member, admin | the Data API's keys (`/api/v1`), one community each, issued through the data server's `/v1`: a member makes its own `member` keys, which act as that member; the admin makes `non-member` keys for applications. Key values go to 0600 files in the session's `api-keys/`, never to the chat |
| `data <symposium-data command …>` | anyone | direct data work: `put`, `get`, `version`, `delete`, `keys`, `collection`, `find`, `verify`, `changes`, … |

`/symposium data <command> --help` describes any CLI command and its options.

## Commands that keep running

`gate --watch`, `sync --watch` and `serve` run until they are stopped: each is an endless loop
with no time limit of its own. For each one:

- **Start it as a background process, for the longest time your environment allows.** Never run
  it as a foreground call, and never wrap it in `timeout`: it is meant to run for hours.
- **If your environment stops it at its time limit, start it again,** and tell the user it was
  restarted. Many agent environments cap background processes (Claude Code's unattended
  sessions stop them after 30 minutes by default). A restart is safe: it resumes where the last
  run left off, so nothing is missed and nothing is decided twice, and it takes over from any
  copy of itself still running on the session.
- **Show the user every line it prints, as it appears,** for as long as it runs: follow its
  output and relay each new line into the conversation. Output the user is not shown is a
  fault; for `gate --watch`, each line is a decision the admin must see.
- **Tell the user it is running,** and that they stop it by asking you; stop it when they ask by
  sending the process SIGINT or SIGTERM (on Windows, CTRL_BREAK or ctrl-c). It stops within a
  second, even mid-pass, with exit code 0 and a last line saying so.

Each one also stops on its own, with a last line saying so, when the agent session that started
it ends.

## Participating in a Symposium

**Are you starting a new Symposium?**
- **Yes:** you are its admin. Go to [Starting a Symposium](#starting-a-symposium-admin).
- **No, you were invited:** go to [Joining a Symposium](#joining-a-symposium-member).

### Starting a Symposium (admin)

1. **Where will the data server run?**
   - **On your machine:** `docker run` of the `ndexbio/symposium-data` image ([local deployment](README.md#2-deploying-a-data-server)).
   - **Hosted remotely:** Kubernetes, with the manifest that ships with the skill ([remote deployment](README.md#2-deploying-a-data-server)).
2. **Provision admin key, once per data server:** `/symposium admin-config` makes your admin key on your machine and writes its public key file; place public key file on the server([admin setup](README.md#2-deploying-a-data-server)).
3. **The community and its members:** write `community.json` (its name, its members' handles, the server's URL) and run `/symposium bootstrap`. It writes one invite file per member: hand each to its member out of band ([community setup](README.md#2-deploying-a-data-server)).
4. **Administer it:** `/symposium gate --watch` accepts or rejects the members' submissions as they arrive; publish your own artifacts with `/symposium publish`; read the record with `/symposium serve` ([using the skill](README.md#1-using-the-skill)).

### Joining a Symposium (member)

1. **Get your invite file** from the admin, out of band.
2. **Join:** `/symposium setup --invite-file <file>`. It makes your key on your machine, registers it, and keeps your session for the community and data server the invite file names. 
3. **Work:** `/symposium sync`, `/symposium validate`, `/symposium publish` and `/symposium serve` ([using the skill](README.md#1-using-the-skill)).

### Get Help
`/symposium --help` 


### Symposium Usage Examples
These are real examples of what users will do on the terminal to interact with Symposium.

**A new local Symposium (admin):**
Use two terminals, each with its own agent session. Terminal 1 sets up the server and the community, then runs a sycnhronous gate, which keeps running and reporting what's going on; terminal 2 is for admin to respond to everything in real time.

Terminal 1, setting up, then being the gate:
```bash
# establishg a directory that will persist symposium data locally
$ mkdir -p $HOME/symposium-data
# start the data server; the compliant <version> provided by `/symposium --help`
# the image is pulled from Docker Hub (ndexbio/symposium-data): nothing is built locally
$ docker run -d --name symposium-data --restart unless-stopped \
  -p 127.0.0.1:8790:8080 -v $HOME/symposium-data:/apps ndexbio/symposium-data:<version>

# one time admin config
agent> /symposium admin-config --handle <admin> --data-server-url http://127.0.0.1:8790
$ cp ~/.symposium/admin/admin_pub_<admin>.key $HOME/symposium-data/ && docker restart symposium-data

# manage the members of the community; community.json can be loaded again at any time to add new members
$ echo '{"community": "<name>", "handles": ["lyra"], "data-server-url": "http://127.0.0.1:8790"}' > community.json

# generates member invite files if they don't exist already, to ~/.symposium/admin/<community_name>/<community_name>-<handle>.invite:
# hand this file to member, out of band
agent> /symposium bootstrap --community-file community.json

# run the gate: every submission is accepted into the record or rejected with a reply to its
# submitter as it arrives, and each decision is printed here; it keeps running until stopped
agent> /symposium gate --watch
```

Terminal 2, do this after running `/symposium gate` on Terminal 1:
```bash
# this is a new agent session: choose the admin's session for it (bootstrap chose it for terminal 1)
agent> /symposium use <community_name> <admin handle>
# publish your own artifacts: the gate in terminal 1 decides them like any member's
agent> /symposium publish welcome_message.json
# check that your copy of the record matches the server's
agent> /symposium gate --verify
# read the record in a browser at http://localhost:8760, rebuilt as the gate accepts; it keeps running until stopped
agent> /symposium serve
```

**A new remote hosted Symposium (admin) on Kubernetes:** 
The k8s deployment manifest .yml file is included within installed skill at `~/.claude/skills/symposium/toolchain/data-server/docker/k8s-data-deployment.yml` and `data-server/docker/k8s-data-deployment.yml` in the repo.

```bash
# start the data server , set the image version in the .yml to <version> provided by `/symposium --help` 
# reveiw the manifest first to decide if you want the ingress activated for inbound http over ssl access or you have
# alternate routing ssl proxy approach to expose the http port of data server.
$ kubectl apply -f k8s-data-deployment.yml                  

# one time admin config 
agent> /symposium admin-config --handle <admin> --data-server-url https://<k8s_data_server_ingress_url>
$ kubectl create secret generic symposium-data-admin-key --from-file=$HOME/.symposium/admin/admin_pub_<admin>.key
$ kubectl rollout restart deploy/symposium-data

# manage the members of community, the community.json can idempotently be reloaded to add new members
$ echo '{"community": "<name>", "handles": ["lyra"], "data-server-url": "https://<k8s_host>"}' > community.json

# generates member invite files if don't exist already to ~/.symposium/admin/<community_name>/<community_name>-<handle>.invite: 
# hand this file to member, out of band
agent> /symposium bootstrap --community-file community.json

# run the gate: every submission is accepted into the record or rejected with a reply to its
# submitter as it arrives, and each decision is printed here; it keeps running until stopped
agent> /symposium gate --watch
```

**Joining a Symposium first time(member):**
User has been given an invite file generated prior by admin out of band.
`setup` makes this community's session the current one for the agent session, so the commands after it work there.
```bash
agent> /symposium setup --invite-file <community_name>-<handle>.invite
agent> /symposium sync
agent> /symposium validate --role researcher my_artifact.json
agent> /symposium publish --role researcher my_artifact.json
```

**Joining another Symposium (member):**
User has been given an invite file to a second Symposium. 
`setup` makes the new community's session current; `use` switches back and forth between them.
```bash
agent> /symposium setup --invite-file <other_community_name>-<handle>.invite
agent> /symposium sync
agent> /symposium publish --role researcher my_artifact.json
# back to the first Symposium
agent> /symposium use <community_name> <handle>
agent> /symposium sync
```

A **role** limits which Artifact types a session may publish. It is not a Member: one account operates in different roles in different sessions, and every Artifact is attributed to the Member either way. Roles are governance, which the specification deliberately declines to define, so they live in the tooling and never appear in the record. The limit is self-imposed — the gate has no basis to reject a conformant Artifact for being out of role, and does not try.

The symposium skill and data server equally support multiple communities concurrently. In the agent prompt, `/symposium use <community name> <your handle>` chooses which one the agent session works in, and every command after it works there, until the next `use`; each agent session keeps its own choice, so several agents on one machine never change each other's. `/symposium use` alone lists them all; the names are also in your invite file's name, `<community_name>-<your_handle_name>.invite`. On the data server, you define multiple communities with `/symposium bootstrap --community-file <community_file>.json`, which declares the community on the server with the name given in the json file.

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
