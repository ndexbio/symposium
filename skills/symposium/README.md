# The `symposium` skill

Symposium is a specification and toolchain for a community record: an append-only graph in which
the members of a scientific community publish immutable artifacts. The record and its files
live on a **Symposium Data server**. This skill is how every person works with it: root,
server admins, community admins and members alike run `/symposium <command>`, and the skill
does the rest through the `symposium-data` CLI. Nobody runs a tool script or a CLI command by hand, and nobody needs a
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

`setup` is the key command: everyone joins with an invite file, and the server assigns the
**access roles** the invite carries. Root starts with `admin-config` instead, and a server admin
opens a community with `bootstrap` or `use-community`. Every other command works in the
session one of these makes, and a command run before any says which one to run.

**Access roles** decide what each person may do: `server-root` and `server-admin` run the
server, `community-admin` runs a community (invites, roles, the gate), `gate-keeper` runs the
gate, `community-member` publishes, reads the record and works in its collections, and
`community-observer` reads. `community-member` and `community-observer` take a collection value: `:*` every
collection, `:` only your own, `:c1,c2` those named. `/symposium access` shows yours, and a
command your roles do not allow is refused with the grant it takes. The data server's runbook,
"Roles and access" (`toolchain/data-server/RUNBOOK.md` §8), covers them in full.

**Sessions are kept by the skill**, under `~/.symposium/`, so a command works from any
directory and nobody creates or enters one:

| Directory | What it is |
|---|---|
| `~/.symposium/admin/` | a server-level user's server-wide session (`admin-config` for root, `setup` for a server admin), and root's public key file `admin_pub_<handle>.key` |
| `~/.symposium/admin/<community>/` | a server-level user's session for a community: `bootstrap` or `use-community` makes it, and `bootstrap` writes the invite files there |
| `~/.symposium/member/<community>/<handle>/` | a community user's session (member, observer, gate-keeper or community admin): `setup` makes it from the invite |

Each holds the session's context (with the access the server resolved for it), its copy of the record (`record/`) and its event log. `setup`, `bootstrap` and `use-community` make the session they create the current one for the agent session that runs them; `/symposium use <community> <handle>` switches to another (`/symposium use <handle>` for a server-wide one), and `/symposium use` alone lists them all. Every other command works in the current session (or, when the agent session has chosen none, the machine's only one). Each agent session keeps its own choice, so several agents on one machine never change each other's. Every command names the session it worked in (`session` in its JSON, or a first line `session: <community>/<handle>`). A command the session's roles do not allow names the sessions on this machine that hold the grant it takes. Relative paths you give a command are read from the directory you are in.

- **Server admins:** `/symposium bootstrap --community-file community.json` creates the
  community with its first community admin, invites any members it lists, and writes their
  invite files, one `<community>-<handle>.invite` each, in `~/.symposium/admin/<community>/`,
  to hand over out of band (never through a chat). Run it again at any time: it invites only
  who is not invited yet, and rewrites the invite files of everyone still waiting.
- **Everyone invited:** `/symposium setup --invite-file <file>`. The invite carries the handle,
  the community and the server's URL; the roles it grants stay on the server. It is the only
  way to join, on a local server as on a remote one. Setup makes your private key file on your
  machine, registers its public key with the data server, and syncs `record/`, your copy of
  the community's record, in your session; its `messages_for_you` lists the Messages already
  addressed to you. Running it again is harmless. Once you've joined,
  `/symposium gen-api-key <label> --access community-member:*` in your session issues you an
  issued key for the data server (`/v1`), so a web app or service can read the record and
  publish as you.
- **Several agents on one machine** each have their own session, with their own invite.

Then the everyday commands. Each works in its session: `record/` there is the session's copy of
the community's record.

| Command | What it does |
|---|---|
| `/symposium use [<community> <handle>]` | Make that session this agent session's current one; every command after it works there, until the next `use`. Alone, list every session on this machine with the `use` command for each. |
| `/symposium publish [--role <role>] <artifact.json>` | `community-member`: submit one artifact to the gate. It syncs first (listing any Message addressed to you, as `sync` does), validates against the record as it stands (the same checks the gate runs), and submits only what passes; a rejection comes back as a reply that `sync` lists. `--role` is a publishing role, a limit on the Artifact types this session publishes: `--roles` lists them, `--roles <name>` prints one. Needs the data server: nothing validates offline. |
| `/symposium validate [--role <role>] <artifact.json>` | The same checks as `publish`, submitting nothing (`publish --check`). |
| `/symposium sync [--watch\|--messages]` | Bring the session's `record/` up to date from the record, in the server's order, and list the gate's replies addressed to you and each Message whose `recipients` include you, once. `--messages` then lists every Message addressed to you, newest first, marking the ones not listed before. `--watch` repeats every `SYMPOSIUM_POLL` seconds (default 30). |
| `/symposium gate [--dry-run\|--verify\|--rebuild\|--watch]` | `community-admin` or `gate-keeper`: decide every submission waiting in `inbox`: accept it into the record, where the server stamps its `created`, or reply to its submitter. Every `download` held on the data server is verified. `--dry-run` decides and changes nothing; `--verify` compares the session's `record/` with the record; `--rebuild` rebuilds the session's `record/`'s cursor and the gate's state from the server; `--watch` runs a pass every `SYMPOSIUM_POLL` seconds (default 30), reporting each one that accepts or rejects something, until stopped. |
| `/symposium serve [<record dir>] [--port N]` | Browse the session's `record/` (or the record directory given) at `http://localhost:8760` (or `--port`), rebuilt whenever it changes. It stops with an error when there is no the session's `record/`: run `sync` first. |
| `/symposium data <command> …` | Direct data work through the CLI: `put`, `get`, `version`, `delete`, `stat`, `versions`, `changes`, `find name\|hash\|meta`, `verify`, `collection list\|create\|set-public`, `owner whoami\|rotate`. `/symposium data <command> --help` shows its options. |
| `/symposium access` | Your access roles and grants in this session, and the six roles. |
| `/symposium invite --handle <h> --access <role>[:<collections>] --out <file> [--hours N]` | `community-admin` (in its community) or a server admin: one invite file, carrying access roles the server applies when `<h>` joins; root invites server admins with `--access server-admin`. `invite list --out-dir <dir>` writes every pending one. |
| `/symposium assign\|unassign (--handle <h>\|--api-key <id>) --access <role>[:<collections>]` | Add or remove access roles, or some collections of one: `community-admin` for any community role; a collection's owner for `community-observer` on its own collections, which is how it shares them read-only. |
| `/symposium users list` | Anyone in the community: its users, removed ones marked, each with its roles, and the server-level users; `--server`, a server admin's view of the server-level users. |
| `/symposium users remove --handle <h>` | `community-admin`, server admins: removing a user keeps it as a tombstone, its handle retired and its work kept, and deletes every key it issued. |
| `/symposium rebind-key --handle <h> --out <file>` | `community-admin`: a user's key is lost or compromised. Their keys are retired, and the new invite file lets them register a new one, with the same roles. |
| `/symposium suspect-after --handle <h> --at <instant>` | `community-admin`: flag everything the user writes after an instant (ISO 8601 with a timezone). The versions stay. |
| `/symposium purge --cite <citation>` | `community-admin`: free one version's content; it then answers that it was purged, with its metadata. |
| `/symposium export`, `/symposium import` | Server admins (`export` also a community admin): see section 4. |
| `/symposium admin-config …` | Root: see section 2. |
| `/symposium use-community <community>` | Server admins: a session for an existing community. |
| `/symposium gen-api-key <label> --access <role>[:<collections>] [--non-member] [--community <c>] [--expires-days N]` | An issued key for the data server (`/v1`), bound to one community (the session's, or `--community`), named by `<label>`, unique among your keys, and carrying the access roles `--access` names. **A member key** (the default) acts as you, never beyond your own grants: with `community-member:*` a web app holding it publishes, reads and writes as you. **With `--non-member`**, a key of its own for an application, carrying `community-observer` on the collections it names (yours, or any with `community-admin`). The key goes to a 0600 file in the session's `api-keys/`; only its id, community, roles, label and the file's path are printed. Hand the file to the app out of band. |
| `/symposium list-api-keys [--community <c>]` | The keys you issued, with their roles, written with their values to a 0600 file in the session's `api-keys/`, and printed without values. A community admin's listing shows every key of the community. |
| `/symposium revoke-api-key <key id> [--community <c>]` | Delete one of your keys, or with `community-admin` any key of the community: its next request answers 401. Removing a user deletes every key it issued. |

`publish`, `validate`, `sync`, `gate` and `serve` print a free-text report, and their exit code
is the result (0 = done; `serve`, `sync --watch` and `gate --watch` run until stopped). Every other command
prints one JSON object: `setup`, `bootstrap`, `use`, `use-community`, `access`, `port`, the
administration commands (`admin-config`, `invite`, `assign`, `unassign`, `users`,
`rebind-key`, `suspect-after`, `purge`, `export`, `import`), the key commands (`gen-api-key`,
`list-api-keys`, `revoke-api-key`) and `data …`.

**Commands that keep running** (`gate --watch`, `sync --watch`, `serve`): each runs until stopped,
with no time limit of its own. Your agent starts each one in the background and shows you every
line it prints as it appears, so you follow the gate's decisions, the copy's updates and the
browser's rebuilds in the conversation. Ask the agent to stop one: SIGINT, SIGTERM or, on
Windows, CTRL_BREAK stops it within a second, even mid-pass. Each also stops on its own, with a last
line saying so, when the agent session that started it ends: on macOS and Linux it finishes
cleanly, as with ctrl-c; on Windows it is ended at once, which is safe because every write is
atomic and the server holds every decision.

Agents limit how long a background process may run: Claude Code's unattended sessions (CI, the
Agent SDK, `claude -p`) stop one after 30 minutes by default, and 2 hours at most unless raised
with `BASH_DEFAULT_TIMEOUT_MS` and `BASH_MAX_TIMEOUT_MS`; interactive sessions set no limit. When
the limit stops a watch, the agent starts it again. A restart resumes where the last run left
off, and takes over from any copy of itself still running on the session, so exactly one runs.

## 2. Deploying a data server

The skill never runs a data server; a person deploys one, once, and it can host many
communities. The server is the published image [`ndexbio/symposium-data` on Docker Hub](https://hub.docker.com/r/ndexbio/symposium-data),
run with `docker run` or, on Kubernetes, with its Helm chart, so nothing is built locally.
`<version>` below is the image `/symposium --help` names (`data_server_image`): the version this
skill was built for. Every new server starts **non-operational**, until its root key is in place.

- **Local, with Docker**, for personal communities or ones you are comfortable running on your
  own machine: `docker run` with a directory of your machine mounted on `/apps`, reachable by
  agents on that machine (or your network):

  ```bash
  docker run -d --name symposium-data --restart unless-stopped \
    -p 127.0.0.1:8790:8080 -v /path/to/your/machine/symposium-storage:/apps \
    ndexbio/symposium-data:<version>
  ```

- **Kubernetes, with the Helm chart**: `oci://registry-1.docker.io/ndexbio/symposium-helm`,
  installed straight from Docker Hub with Helm 3.8 or later, or 4 (no `helm repo add`). The
  chart's `appVersion` is the image it deploys (`helm show chart … --version <chart version>`).
  Keep one `values.yaml` for the install and pass it to every `helm install` and `helm upgrade`:

  ```bash
  helm install symposium-data oci://registry-1.docker.io/ndexbio/symposium-helm \
    --version <chart version> -n symposium --create-namespace -f values.yaml
  ```

  - **Locally, on Docker Desktop's Kubernetes**, to rehearse a cluster deployment:
    `values.yaml` holds `service: {type: LoadBalancer, port: 8790}`, and the server is at
    `http://localhost:8790`.
  - **Remote**, for truly shared communities that peers anywhere can reach: the chart publishes
    the server at a public HTTPS URL through the cluster's Gateway (`expose.mode: gateway`, a
    Gateway API HTTPRoute) or its Ingress controller (`expose.mode: ingress`). The runbook's
    "On a remote cluster" explains both and gives their values.

  The chart also ships with the skill, in `toolchain/data-server/helm/symposium-helm/`.
- **Root, once per server:** run
  `/symposium admin-config --handle <root> --data-server-url <url>`. It makes root's key on
  your machine (or reuses it), writes the public key file `admin_pub_<root>.key`, sets up
  root's server-wide session, and prints the key's fingerprint and how to place it; placing it
  restarts the server:

  ```bash
  # Docker
  cp ~/.symposium/admin/admin_pub_<root>.key /path/to/your/machine/symposium-storage/
  docker restart symposium-data
  # Kubernetes: add `adminKey: {handle: <root>}` to values.yaml, then (it restarts the server)
  helm upgrade symposium-data oci://registry-1.docker.io/ndexbio/symposium-helm \
    --version <chart version> -n symposium -f values.yaml \
    --set-file adminKey.publicKey=$HOME/.symposium/admin/admin_pub_<root>.key
  ```

  The server's status then reports `root` and that fingerprint. `--new-key` replaces root's
  key; placing the new file rebinds root, and every other user's keys stay as they are.
- **Delegating:** root invites server admins, who create and run communities from their own
  machines: `/symposium invite --handle <h> --access server-admin --out <h>.invite`. The
  runbook's "Roles and access" walks from an empty server to communities run by their own
  community admins.
- **Many communities on one server:** each community is a tenant with its own name (at most 20
  letters, digits or underscores), users and data; each gets its own `community.json` and
  `bootstrap`, and its own community admin.
- **Each community:** a server admin (or root) writes its `community.json` and runs
  `/symposium bootstrap` with it:

  ```json
  {"community": "demo", "admin": "steward", "handles": ["lyra", "vega"], "data-server-url": "http://127.0.0.1:8790"}
  ```

  `community` is its name; `admin` the handle of its first community admin, who joins with the
  invite file bootstrap writes and runs the community from then on; `handles`, optional, the
  members to invite now; `data-server-url` the server.

The data server's runbook, `toolchain/data-server/RUNBOOK.md` (`data-server/RUNBOOK.md` in a
clone of the repository), walks through choosing and running each deployment (Docker, Docker
Desktop's Kubernetes, a remote cluster), the root key and the server's modes, roles and
access, back-ups, and tearing it down.

## 3. Moving a community off NDEx (port-ndex)

`/symposium port <ndex_credentials_file> <ndex_url>` copies a community's record into a new, empty community on the data server (port-ndex).

- **Drain the gate first:** run it until nothing is waiting. A submission it has not decided is not ported.
- **The order:** a server admin's `bootstrap` creates the community and sets the context; `port` ports into it; `bootstrap` again writes the invites for the authors and reply recipients the port added as users.
- **The credentials file** holds the NDEx community admin's account as JSON `{"username": ..., "password": ...}`, mode 0600, for port-ndex. It is sent only to the data server, which holds it in memory for the length of the port; the data server itself connects to the source, so it needs outbound access to it (port-ndex).
- **What is ported** (port-ndex): the record and the gate's replies, with their exact bytes, names, original times and authors; not undecided submissions, accounts or passwords.
- **Members afterwards** join with the invite files from the second `bootstrap`, as in any community.

The detailed guide is [`reference/PORT_NDEX.md`](reference/PORT_NDEX.md).

## 4. Backing up and moving a community: export and import

- `/symposium export --out <file>` writes the whole community: its users with their public keys
  and access roles, removed ones included, and its files and versions with their bytes. API keys stay on the server
  that issued them: after an import, issue new ones there.
- `/symposium import --from <file> --community-file community.json` recreates it on another
  server, or the same one after a loss. It creates the community and is refused if it already
  exists, so it runs before any `bootstrap` for it. The export's community must be the one
  `community.json` names. Members obtain session keys again with the private key files they
  already hold. What the
  exported root owned becomes the new server's root's.
- Volume or PVC snapshots of the data server are the other backup.
