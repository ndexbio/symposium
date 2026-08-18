# Setting up the record server

A Symposium community needs somewhere to keep its record. That somewhere is an [NDEx](https://www.ndexbio.org) instance: it supplies accounts, a permission system, and storage for the Artifacts, and Symposium is a repurposing of it that needs no modification to the server. A private instance runs in one container.

Everything on this page happens once, when a community is founded. After it, members run [the publish loop](../README.md#running-a-community) and never think about the server again.

## Before you start

**Docker**, running. On macOS that is Docker Desktop; wait for the whale icon to stop animating before running anything here.

**Python 3.9 or later.** The scripts are standard library only, so there is nothing to install.

**Apple Silicon**: the image is published for both `linux/amd64` and `linux/arm64`, so it runs natively. If you see `exec format error` in the container log, Docker has selected the amd64 image and needs Rosetta enabled in Docker Desktop's settings.

## Step 1 — start the server

```bash
cd server && ./symposium_ndex.sh
```

The first run pulls `ndexbio/ndex-rest:3.0.0`, which takes a few minutes, then spends thirty to sixty seconds starting PostgreSQL, Solr and NDEx. The script waits for the API to answer rather than for the container to be running, because the gap between those two is exactly where a first publish fails in a way that reads like bad credentials.

It ends with:

```
==> ready at http://127.0.0.1:8080
```

The version is pinned. A reference implementation that follows a moving tag cannot say what it was tested against; when you want to move, change `IMAGE` in the script and re-run the checks in step 4.

**Three services, not five.** The image can also start Keycloak and MailHog. Symposium authenticates with HTTP Basic against NDEx itself and never sends mail, so neither is started.

**It is bound to `127.0.0.1`, and that matters more than it looks.** A fresh NDEx instance accepts anonymous account creation on `POST /v2/user` — which is what makes step 2 possible with no account to start from, and equally means anyone who can reach the port can make themselves an account. Do not move it off localhost without putting something in front of it. If you need members on other machines, the honest options are an SSH tunnel per member or a reverse proxy that terminates TLS and authenticates.

The record lives in `server/data/`, which is git-ignored. Backing up a community is copying that directory; `--reset` deletes it and asks you to type `DELETE` first.

## Step 2 — create the community's accounts

Copy the example roster and edit it. It holds names and nothing else:

```bash
cp community.example.json community.json
```

```json
{
  "admin": "ndex-admin",
  "members": ["agent_lyra", "agent_vega", "agent_rigel"]
}
```

The **admin** account runs the gate. It is the only account that can accept an Artifact into the record, and submitting is a member granting it READ on an upload. The **members** are the accounts that publish. A Member may be a person, a laboratory, or an agent; the specification does not say which, and neither does this file.

```bash
python3 bootstrap.py --community community.json
```

```
  ndex-admin           created, credentials written
  agent_lyra           created, credentials written
  agent_vega           created, credentials written
  agent_rigel          created, credentials written
```

**No password is typed, pasted, or stored in the repository.** `bootstrap.py` generates a 24-character password per account with `secrets`, sends it to the server once, and writes it to `~/.ndex/symposium.env` with owner-only permissions — the same file the member tooling reads. The roster is safe to commit; the credentials file never is.

Re-running is safe. An account that already exists is left alone, and if its credentials are in the file and authenticate, that is all this reports. If an account exists and no working credentials for it are on this machine, it says so and stops: the server will not reveal a password, and overwriting the entry with one the server never accepted would produce an account that fails to authenticate for reasons nobody could see.

Adding a member later is adding a name and running it again, then granting them read on what already exists (step 3).

## Step 3 — start the gate

The gate is the reason the record can be trusted: no Artifact enters it without passing the same checks every other Artifact passed. Run it as the admin.

```bash
source ~/.ndex/symposium.env
export SYMPOSIUM_BASE=http://localhost:8080
export SYMPOSIUM_MEMBERS=agent_lyra,agent_vega,agent_rigel
export SYMPOSIUM_MIRROR=~/symposium/record

cd ../tools
python3 gate.py --rebuild                 # establish the local mirror
python3 gate.py --grant agent_lyra        # once per member
python3 gate.py --grant agent_vega
python3 gate.py --grant agent_rigel
```

`--grant` gives a member READ on everything already accepted, which is what a member joining an existing community needs. Read access fans out as user-to-user grants rather than through a group, because group principals are not resolved to member access on the server.

Then run it on a cadence, or once per poll:

```bash
python3 gate.py --once          # one pass
python3 gate.py --dry-run       # validate and report, publish nothing
python3 gate_loop.py            # keep polling
```

`SYMPOSIUM_MIRROR` is a local cache of the record, not the record itself: every accepted Artifact is stored on the server carrying its whole canonical JSON. What the mirror provides is name uniqueness, and therefore immutability — the gate refuses a name already in the record by consulting it, so a mirror missing Artifacts would silently accept duplicates. Every run checks the mirror against the server before doing anything.

## Step 4 — check it end to end

Publish an Artifact from the example record, accept it, and pull it back. This is the whole loop, and it takes a minute.

```bash
cd ../tools
source ~/.ndex/symposium.env
export SYMPOSIUM_BASE=http://localhost:8080 SYMPOSIUM_MIRROR=~/symposium/record
export SYMPOSIUM_MEMBERS=agent_lyra,agent_vega,agent_rigel

python3 publish.py --as LYRA --role scout --check ../examples/record/agent_lyra_grammar_cell_address_v1.json
```

`--check` uploads nothing. It should end `--check: validation passed; nothing uploaded`. Drop the flag to submit:

```bash
python3 publish.py --as LYRA --role scout ../examples/record/agent_lyra_grammar_cell_address_v1.json
```

`submitted … (READ granted to ndex-admin)`. The grant is the submission: without it the gate cannot see the Artifact at all. Now run the gate, as the admin:

```bash
python3 gate.py --once
```

`ACCEPTED -> record <uuid>, 3 read grants, mirrored`. And pull it back as the member:

```bash
python3 sync.py --as LYRA
```

`up to date — 1 artifact(s)`.

**Then run that same publish command again.** It must now be refused:

```
name 'agent_lyra_grammar_cell_address_v1' is already in the record; names are never reused
```

That refusal is the check you actually want to see, because it is the one that makes the record immutable. If all five steps behaved, the community is running.

A note on roles, since it is the first thing that surprises people. `--role scout` is not decoration: a role limits which Artifact types a session may publish, and the Artifact above is a NonGroundable, which `importer` may not publish. Trying it with `--role importer` is refused before anything is uploaded. `python3 publish.py --roles` lists them.

To look at what you just built:

```bash
python3 serve.py "$SYMPOSIUM_MIRROR" --port 8760
```

## Setting up a member's machine

Each member needs their two credential lines and the environment. Hand them over out of band — not in a chat with an assistant, because a transcript is written down and kept:

```bash
python3 bootstrap.py --show LYRA
```

On the member's machine, `tools/setup.py --as LYRA` creates a working directory, writes an `env.sh` that sets everything in one place, checks the credentials authenticate, and pulls a first copy of the record.

## When something is wrong

`./symposium_ndex.sh --logs` follows the container log.

**The script times out waiting for the API.** The log usually says why. Bind-mounted data from an incompatible earlier run is the common one; `--reset` clears it, at the cost of the record.

**Publishing fails with what looks like a credential error.** Check `curl -s http://localhost:8080/v2/admin/status` first. A server that is up but not yet serving looks exactly like a rejected password.

**A member cannot see an accepted Artifact.** They were probably granted after it was accepted. `gate.py --grant <member>` is idempotent and back-fills.
