# The `symposium` skill

Symposium is a specification and toolchain for a community record: an append-only graph in which
the members of a scientific community publish immutable artifacts. The record and its files
live on a **Symposium Data server**. This skill is how every person works with it: admins,
operators and members alike run `/symposium <command>`, and the skill does the rest through the
`symposium-data` CLI. Nobody runs a tool script or a CLI command by hand, and nobody needs a
shell on the server.

**Install** the skill from the Symposium bundle: `make deploy-local` from a clone of the
repository, or unzip a release's `Symposium_skill.zip` and copy its `skills/symposium/` into
`~/.claude/skills/`. The skill's `toolchain/` holds the repository's Symposium base at its
repository paths: the specification, the tools and their docs, roles, policies and SOPs, the
worked examples and the conformance suite. The CLI ships inside it (`toolchain/tools/symposium-data/`), and
the host needs only Python 3.9+: nothing goes on `PATH`. The first command of an agent session
prepares the skill's Python runtime: on the machine's first session it builds the skill's own
environment, `.venv`, from PyPI (so that first command needs network access), and every later
session reuses it.

## 1. Using the skill

`setup` (members) and `bootstrap` (admins) are the key commands. Run one first in every agent
session: it connects the session to one community on one data server, and every other command
works in that context. A command run before either says which one to run.

**Sessions are kept by the skill**, under `~/.symposium/`, so a command works from any
directory and nobody creates or enters one:

| Directory | What it is |
|---|---|
| `~/.symposium/admin/` | `admin-config`'s public key files, `admin_pub_<handle>.key` |
| `~/.symposium/admin/<community>/` | the admin's session for a community: `bootstrap` makes it and writes the invite files there |
| `~/.symposium/member/<community>/<handle>/` | a member's session: `setup` makes it from the invite |

Each holds the session's context, its copy of the record (`record/`) and its event log. `setup` and `bootstrap` make the session they create the current one for the agent session that runs them; `/symposium use <community> <handle>` switches to another, and `/symposium use` alone lists them all. Every other command works in the current session (or, when the agent session has chosen none, the machine's only one). Each agent session keeps its own choice, so several agents on one machine never change each other's. Every command names the session it worked in (`session` in its JSON, or a first line `session: <community>/<handle>`).
An admin-only command (the admin commands, `gate`, `port`; `roster list` is any member's)
refuses in a member's session and names the `use` command for the community's admin. Relative paths you give a command are read from the directory you are in.

- **Admins:** `/symposium bootstrap --community-file community.json` creates the community if
  needed, adds its members to the roster and writes their invite files, one
  `<community>-<handle>.invite` each, in `~/.symposium/admin/<community>/`, to hand over out of
  band (never through a chat). Run it
  again at any time: it only adds, and it rewrites the invite files of everyone still waiting.
- **Members:** `/symposium setup --invite-file <file>`. The invite carries the community, the
  handle and the server's URL; it is the only way to join, on a local server as on a remote
  one. Setup makes your key on your machine (the private key never leaves it), registers it, and
  syncs `record/`, your copy of the community's record, in your session.
  Running it again is harmless.
- **Several agents on one machine** each have their own session, with their own invite.

Then the everyday commands. Each works in its session: `record/` there is the session's copy of
the community's record.

| Command | What it does |
|---|---|
| `/symposium use [<community> <handle>]` | Make that session this agent session's current one; every command after it works there, until the next `use`. Alone, list every session on this machine with the `use` command for each. |
| `/symposium publish [--role <role>] <artifact.json>` | Submit one artifact to the gate. It syncs first, validates against the record as it stands (the same checks the gate runs), and submits only what passes; a rejection comes back as a reply that `sync` lists. `--roles` lists the roles, `--roles <name>` prints one. The admin publishes as `operator` unless it gives `--role`; `--role none` lifts the limit. Needs the data server: nothing validates offline. |
| `/symposium validate [--role <role>] <artifact.json>` | The same checks as `publish`, submitting nothing (`publish --check`). |
| `/symposium sync [--watch]` | Bring the session's `record/` up to date from the record, in the server's order, and list the gate's replies addressed to you. `--watch` repeats every `SYMPOSIUM_POLL` seconds (default 30). |
| `/symposium gate [--dry-run\|--verify\|--rebuild\|--watch]` | Admin: decide every submission waiting in `inbox`: accept it into the record, where the server stamps its `created`, or reply to its submitter. Every `download` held on the data server is verified. `--dry-run` decides and changes nothing; `--verify` compares the session's `record/` with the record; `--rebuild` rebuilds the session's `record/`'s cursor and the gate's state from the server; `--watch` runs a pass every `SYMPOSIUM_POLL` seconds (default 30), reporting each one that accepts or rejects something, until stopped. |
| `/symposium serve [<record dir>] [--port N]` | Browse the session's `record/` (or the record directory given) at `http://localhost:8760` (or `--port`), rebuilt whenever it changes. It stops with an error when there is no the session's `record/`: run `sync` first. |
| `/symposium data <command> …` | Direct data work through the CLI: `put`, `get`, `version`, `delete`, `stat`, `versions`, `changes`, `find name\|hash\|meta`, `verify`, `collection create\|grant-write\|set-public`, `keys mint\|list\|revoke`, `owner whoami\|rotate`. `/symposium data <command> --help` shows its options. |
| `/symposium roster list` | Any member: the community's roster, every handle on it, registered or not yet. |
| `/symposium roster add --handle <h>\|remove --handle <h>` | Admin: change the roster, one handle at a time. |
| `/symposium invite --handle <h> --out <file> [--hours N]` | Admin: one member's invite file. `invite list --out-dir <dir>` writes every pending one. |
| `/symposium rebind-key --handle <h> --out <file>` | Admin: a member's key is lost or compromised. Their keys are retired, and the new invite file lets them register a new one. |
| `/symposium suspect-after --handle <h> --at <instant>` | Admin: flag everything the member writes after an instant (ISO 8601 with a timezone). Nothing is deleted. |
| `/symposium purge --cite <citation>` | Admin: free one version's content; it then answers that it was purged, with its metadata. |
| `/symposium export`, `/symposium import` | Admin: see section 4. |
| `/symposium admin-config …` | Admin: see section 2. |
| `/symposium gen-api-key <username> <role> [--community <c> \| --server] [--expires-days N] [--label …]` | Admin: a Symposium API key (`/api/v1`) with one role, `non-member`, `member` or `admin`. The key goes to a 0600 file under `~/.symposium/admin/api-keys/`; only its id, username, role and the file's path are printed. A `member` key names a registered handle and publishes as it; an `admin` key names the admin. Hand the file over out of band. |
| `/symposium list-api-keys [--community <c>]` | Admin: every API key, written with its value to a 0600 file under `~/.symposium/admin/api-keys/`; the keys are printed without values. |
| `/symposium revoke-api-key <key id>` | Admin: stop a key at once and erase its value. |

`publish`, `validate`, `sync`, `gate` and `serve` print a free-text report, and their exit code
is the result (0 = done; `serve`, `sync --watch` and `gate --watch` run until stopped). Every other command
prints one JSON object: `setup`, `bootstrap`, `use`, `port`, the admin commands (`admin-config`,
`roster`, `invite`, `rebind-key`, `suspect-after`, `purge`, `export`, `import`, `gen-api-key`,
`list-api-keys`, `revoke-api-key`) and `data …`.

**Commands that keep running** (`gate --watch`, `sync --watch`, `serve`): your agent starts each
one in the background and shows you every line it prints as it appears, so you follow the gate's
decisions, the copy's updates and the browser's rebuilds in the conversation. Ask the agent to
stop one. Each also stops on its own, with a last line saying so, when the agent session that
started it ends: on macOS and Linux it finishes cleanly, as with ctrl-c; on Windows it is ended
at once, which is safe for the gate because the server holds every decision.

## 2. Deploying a data server

The skill never runs a data server; a person deploys one, once, and it can host many
communities.

- **Local**, for personal communities or ones you are comfortable running on your own machine:
  `docker run` of `ndexbio/symposium-data` with a directory of your machine mounted on `/apps`,
  reachable by agents
  on that machine (or your network):

  ```bash
  docker run -d --name symposium-data --restart unless-stopped \
    -p 127.0.0.1:8790:8080 -v /path/to/your/machine/symposium-storage:/apps \
    ndexbio/symposium-data:<version>
  ```

  `<version>` is the one `/symposium --help` names (`data_server_image`): the version this
  skill was built for. It starts **non-operational**, until its admin key file is in place.
- **Remote**, for truly shared communities that peers anywhere can reach: a Kubernetes
  deployment of `ndexbio/symposium-data` at a public HTTPS URL, from the manifest that ships
  with the skill, `toolchain/data-server/docker/k8s-data-deployment.yml` (a PVC, the
  Deployment, a Service, and an example TLS Ingress, commented out: uncomment it and set its
  host and TLS secret for a public URL, and pin the image). Apply it, and it too starts **non-operational**, until the admin key's Secret exists:

  ```bash
  kubectl apply -f k8s-data-deployment.yml
  kubectl wait --for=condition=Ready pod -l app=symposium-data --timeout=420s
  ```
- **Admin setup, once per server:** run
  `/symposium admin-config --handle <admin> --data-server-url <url>`. It makes the admin key on
  your machine (or reuses it), writes the public key file `admin_pub_<admin>.key`, and prints
  its fingerprint and where to place it, then restart the server:

  ```bash
  # local
  cp ~/.symposium/admin/admin_pub_<admin>.key /path/to/your/machine/symposium-storage/
  docker restart symposium-data
  # Kubernetes
  kubectl create secret generic symposium-data-admin-key \
    --from-file=$HOME/.symposium/admin/admin_pub_<admin>.key
  kubectl rollout restart deploy/symposium-data
  ```

  The server's status then reports that fingerprint. One admin key serves every community on the server, and
  every community inherits that admin. `--new-key` replaces it; placing the new file rebinds the
  server.
- **Many communities on one server:** each community is a tenant with its own name (at most 20
  letters, digits or underscores), members, identities and data; each gets its own
  `community.json` and `bootstrap`, and agents choose one with `setup` or `bootstrap`.
- **Each community:** write its `community.json` and run `/symposium bootstrap` with it:

  ```json
  {"community": "demo", "handles": ["lyra", "vega"], "data-server-url": "http://127.0.0.1:8790"}
  ```

  `community` is its name; `handles` its members (the server admin's handle cannot be one);
  `data-server-url` the server. There is no admin field.

The data server's runbook, `toolchain/data-server/RUNBOOK.md` (`data-server/RUNBOOK.md` in a
clone of the repository), covers operating it: the deployment options, the admin key file and
the server's modes, back-ups, and tearing it down.

## 3. Moving a community off NDEx (port-ndex)

`/symposium port <ndex_credentials_file> <ndex_url>` copies a community's record into a new, empty community on the data server (port-ndex).

- **Drain the gate first:** run it until nothing is waiting. A submission it has not decided is not ported.
- **The order:** `bootstrap` creates the community and sets the context; `port` ports into it; `bootstrap` again writes the invites for the authors and reply recipients the port added to the roster.
- **The credentials file** holds the source's admin account as JSON `{"username": ..., "password": ...}`, mode 0600, for port-ndex. It is sent only to the data server, which holds it in memory for the length of the port; the data server itself connects to the source, so it needs outbound access to it (port-ndex).
- **What is ported** (port-ndex): the record and the gate's replies, with their exact bytes, names, original times and authors; not undecided submissions, accounts or passwords.
- **Members afterwards** join with the invite files from the second `bootstrap`, as in any community.

The detailed guide is [`reference/PORT_NDEX.md`](reference/PORT_NDEX.md).

## 4. Backing up and moving a community: export and import

- `/symposium export --out <file>` writes the whole community: its members' public keys, roster,
  grants, read keys (hashes only), and its files and versions with their bytes.
- `/symposium import --from <file> --community-file community.json` recreates it on another
  server, or the same one after a loss. It creates the community and is refused if it already
  exists, so it runs before any `bootstrap` for it. The export's community must be the one
  `community.json` names. Members sign in again with the keys they already hold. What the
  exported admin owned becomes the new server's admin's.
- Volume or PVC snapshots of the data server are the other backup.
