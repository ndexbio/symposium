# The `symposium` skill

Symposium is a specification and toolchain for a community record: an append-only graph in which
the members of a scientific community publish immutable artifacts. The record and its files
live on a **Symposium Data server**. This skill is how every person works with it: admins,
operators and members alike run `/symposium <command>`, and the skill does the rest through the
`symposium-data` CLI. Nobody runs a tool script or a CLI command by hand, and nobody needs a
shell on the server.

**Install** the skill and the CLI from the Symposium bundle: `make deploy-local` from a checkout
of the repository, or unzip a release's `Symposium_skill.zip` the same way. The skill goes into
`~/.claude/skills/symposium`, and the CLI into `~/.local/bin`, which must be on `PATH`.

## 1. Using the skill

`setup` (members) and `bootstrap` (admins) are the key commands. Run one first in every agent
session: it connects the session to one community on one data server, and every other command
works in that context. A command run before either says which one to run.

- **Admins:** `/symposium bootstrap --community community.json` creates the community if
  needed, adds its members to the roster and writes their invite files, one
  `<community>-<handle>.invite` each, to hand over out of band (never through a chat). Run it
  again at any time: it only adds, and it rewrites the invite files of everyone still waiting.
- **Members:** `/symposium setup --invite-file <file>`. The invite carries the community, the
  handle and the server's URL; it is the only way to join, on a local server as on a remote
  one. Setup makes your key on your machine (the private key never leaves it) and registers it.
  Running it again is harmless.
- **Several agents on one machine** each work in their own directory, with their own invite.

Then:

| Command | What it does |
|---|---|
| `/symposium data <command> …` | Direct data work through the CLI: `put`, `get`, `version`, `delete`, `stat`, `versions`, `changes`, `find name\|hash\|meta`, `verify`, `collection create\|grant-write\|set-public`, `keys mint\|list\|revoke`, `owner whoami\|rotate`. `/symposium data <command> --help` shows its options. |
| `/symposium roster list\|add --handle <h>\|remove --handle <h>` | Admin: the community's roster, one handle at a time. |
| `/symposium invite --handle <h> --out <file> [--hours N]` | Admin: one member's invite file. `invite list --out-dir <dir>` writes every pending one. |
| `/symposium rebind-key --handle <h> --out <file>` | Admin: a member's key is lost or compromised. Their keys are retired, and the new invite file lets them register a new one. |
| `/symposium suspect-after --handle <h> --at <instant>` | Admin: flag everything the member writes after an instant (ISO 8601 with a timezone). Nothing is deleted. |
| `/symposium purge --cite <citation>` | Admin: free one version's content; it then answers that it was purged, with its metadata. |
| `/symposium export`, `/symposium import` | Admin: see section 4. |
| `/symposium admin-config …` | Admin: see section 2. |

## 2. Deploying a data server

The skill never runs a data server; a person deploys one, once, and it can host many
communities.

- **Local**, for personal communities or ones you are comfortable running on your own machine:
  `docker run` of `ndexbio/symposium-data` with a named volume on `/apps`, reachable by agents
  on that machine (or your network):

  ```bash
  docker run -d --name symposium-data --restart unless-stopped \
    -p 127.0.0.1:8790:8080 -v symposium-data:/apps ndexbio/symposium-data:<version>
  ```

  It starts **non-operational**, until its admin key file is in place.
- **Remote**, for truly shared communities that peers anywhere can reach: a Kubernetes
  deployment of `ndexbio/symposium-data` (`data-server/docker/k8s-data-deployment.yml`: a PVC,
  and an Ingress with TLS) at a public HTTPS URL. The admin key comes from a Secret.
- **Admin setup, once per server:** run
  `/symposium admin-config --handle <admin> --data-server-url <url>`. It makes the admin key on
  your machine (or reuses it), writes the public key file `admin_pub_<admin>.key`, and prints
  its fingerprint and where to place it: `docker cp admin_pub_<admin>.key symposium-data:/apps/`
  then `docker restart symposium-data` locally, or the Secret on Kubernetes. The server's
  status then reports that fingerprint. One admin key serves every community on the server, and
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

The data server's own runbook (`data-server/RUNBOOK.md` in the repository) covers operating it.

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
