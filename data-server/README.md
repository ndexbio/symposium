# Symposium Data server

A single Docker image that runs Symposium Data, the versioned file store Symposium communities use to persist, share and cite data files. The image contains three services, managed by `supervisord`:

- **the data service**: FastAPI on port 8080, the only port the container exposes. It serves the data server's own API under `/v1` and the Symposium API under `/api/v1` (see "The Symposium API");
- **PostgreSQL 16**: the server's records: configuration, owner identities, rosters, grants, invites, collections, files, versions, metadata and read keys. All of it is managed by Alembic migrations;
- **SeaweedFS**: the internal S3 store for file contents. It is never exposed; the data service streams every byte.

**To run a server**, start with `RUNBOOK.md`: `docker run` (or the Kubernetes manifest), then place the admin's key file. This README covers the build, the make targets and the API.

## Layout

| Path | What it is |
|---|---|
| `service/` | The `symposium_data` Python package: the HTTP API, its background jobs and the Alembic migrations, plus the tests. Locked with `uv.lock`. |
| `service/symposium_api/` | The Symposium API: `generated/`, generated from `api/openapi.yaml` and never edited by hand, and the hand-written service behind it. |
| `service/symposium_server/` | The composition root uvicorn starts: the data service with the Symposium API mounted at `/api/v1`. |
| `service/codegen/` | The generator script and its templates (see "The Symposium API"). |
| `docker/Dockerfile` | Multi-stage build: `runtime-base` (PostgreSQL, supervisor, gosu, SeaweedFS with a pinned sha256), then `builder` (installs the locked wheel into `/opt/venv`), then `deploy`. |
| `docker/supervisord/` | One config snippet per service. `start.sh` assembles them. |
| `docker/scripts/start.sh` | Container start-up: version banner, first-boot secrets, PostgreSQL init, then starts supervisord. |
| `docker/k8s-data-deployment.yml` | Kubernetes deployment on a single ReadWriteOnce PVC, with the admin key from a Secret. |
| `RUNBOOK.md` | How to deploy (Docker or Kubernetes), place the admin key, host many communities, port, export and import, verify and tear down. |
| `PORT_NDEX.md` | The port-ndex: copying a community's record from NDEx into an empty community here. |

## Make targets

These four targets are the only ones. Run them from this folder, or from the repository root with `make -C data-server <target>`. The repository's top-level `make test` runs this `test` as part of its single gate. Image targets run no tests.

| Target | What it does |
|---|---|
| `lint` | `ruff check` and `ruff format --check` on `service/`. |
| `test` | `lint` and `build-docker`, then the unit suites, then the integration suites against that image, on one `sdtest-*` container for the whole session. |
| `build-docker` | Builds and tags the image `ndexbio/symposium-data:$(TAG)`. The image also takes `../tools` (the `symposium_rules` package) and `../api` (the contract), as the named build contexts `rules` and `api`. |
| `push-docker` | A buildx multi-arch (`linux/amd64`, `linux/arm64`) build and push of `:$(TAG)` and `:latest`. It is used by the release workflow, on a `data-server-v<version>` GitHub release. |

`TAG` defaults to the version in `service/pyproject.toml`; override it with `make build-docker TAG=1.2.3`. The image is built with `DATA_VERSION=$(TAG)`. The container prints `symposium-data <version>` as its first line of output, and `GET /v1/status` reports the same version. `/v1/status` also reports health: it answers **503**, with `"postgres"` or `"s3"` set to `"unavailable"`, whenever either dependency is down. The Kubernetes readiness probe relies on this. It reports the server's `mode` too (see "The admin key file").

**Requirements:** Docker and [uv](https://docs.astral.sh/uv/). `uv` installs Python 3.11 and the locked dependencies itself.

## Releases

Publishing a GitHub release tagged `data-server-v<version>` runs the `push-image` job of `.github/workflows/release.yml`; the release tag's prefix alone gates it, and a pushed tag on its own runs nothing. That job runs `make push-docker TAG=<version>`, which publishes `ndexbio/symposium-data:<version>` and `:latest`. It needs the repository secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`.

## The admin key file

Nobody has a shell on the server (R-D7): every admin operation is an admin-only route. The admin's **public** key is a file, `admin_pub_<handle>.key`, holding the public JWK that Symposium's `admin-config` writes (mode 0644). It goes in `/apps/` (copied into the host directory mounted there) or in `/apps/admin-key/` (where the Kubernetes manifest mounts the Secret holding it). The API reads it at every start-up (R-D4):

| At start-up | Result |
|---|---|
| Not yet initialized, exactly one key file | Binds that handle and key, and saves a backup, `/apps/data/config/admin_pub.backup`. |
| Initialized, the admin's file holds the bound key | Starts normally. |
| Initialized, the admin's file holds a different key | **Rebinds**: the old admin keys are retired, the new one is bound, the backup is updated, and it is logged. |
| Initialized, the admin's file missing, the backup present | Starts normally from the backup and logs a warning. Nothing is written to `/apps`. |
| A key file naming another handle | Ignored, with an error naming both handles: the admin handle never changes. |
| No key file, not initialized | Non-operational: `admin key not provided`. |
| Several key files, not initialized, or two for one handle (one in each place) | Non-operational: `ambiguous admin key files`. |
| The key file is not a usable public key (not JSON, not an Ed25519 public JWK, or a private key) | Non-operational: `admin key invalid`, with an error on the console saying why. Nothing is bound or rebound. |
| Initialized, with neither the file nor the backup | Non-operational: `admin key missing`, with an error on the console. |

**Non-operational mode:** every route except `GET /v1/status` answers **501**. `/v1/status` answers 200 with `mode` (`operational` or `non-operational`), the `reason` and the `server_id`; once operational it reports the admin's handle (`admin`) and key `fingerprint` (its RFC 7638 thumbprint) instead of a reason. The services keep running and the data stays intact: fix the key file and restart the server.

## Communities

One server hosts many communities as tenants (R-G8). Each has its own members, identities and data, and every route that depends on a community sits under `/v1/{community}/…`. Only `/v1/status`, `/v1/communities` and the admin's sign-in (`/v1/admin/…`) are server-wide.

A community name is 1–20 letters, digits or underscores; `status`, `communities` and `admin` are reserved. A name keeps the case it was created with, is unique ignoring case, and matches paths ignoring case. A path naming a community that does not exist, or a name that is not a slug, answers `404`.

| Endpoint | Purpose |
|---|---|
| `POST /v1/communities {name}` | Admin only. Creates a community and its default collections. Idempotent: `201` when created, `200` when exactly that name exists; `400` for a name that is not a slug, is reserved, or differs only in case from an existing one. |
| `GET /v1/communities` | Admin only. Every community, with when it was created. |
| `POST /v1/communities/import` (body: an export) | Admin only. Creates the exported community in one transaction (R-J6): `201` with one entry per member, `409` when the community already exists here (there is no merge) or a member's handle is this server's admin, `400` for a damaged stream or a name that is not a slug. Collections the exported admin owned become this server's admin's; versions keep their recorded `created_by`. |
| `GET /v1/{community}/export` | Admin only. The community as a tar stream: one consistent snapshot of its rows, read keys (hashes only) and members' public keys, then every stored payload. Invites are not included. |
| `POST /v1/{community}/port-ndex {ndex_url, credentials: {username, password}, page_size?}` | Admin only. Starts a port-ndex into this empty community in the background (`PORT_NDEX.md`) and answers `202` with its id. `400` if the community holds files, `409` while another port-ndex runs anywhere on the server. |
| `GET /v1/{community}/port-ndex/{id}` | Admin only. A port-ndex's state (`running`, `ok`, or `failed` with a reason), who requested it, and its summary. |

## Identity

The server provisions no accounts. Each member generates an Ed25519 key on their own machine, and the private key never leaves it. Registration binds a handle to the public key **within one community** (R-D): the same handle in another community is a separate identity, with its own key.

| Endpoint | Purpose |
|---|---|
| `POST /v1/{community}/auth/challenge {handle}` | A single-use nonce, valid for 5 minutes. |
| `POST /v1/{community}/auth/token {handle, nonce, signature}` | Sign the nonce with an active key to receive an EdDSA access token (15 minutes by default), valid only in this community. |
| `POST /v1/{community}/owners {handle, public_jwk, nonce, signature, invite?}` | Register. Members join only by invite: a valid, unused invite bound to this handle and community is required. Returns `403` for a handle not on the community's roster or without a valid invite, `409` for a handle already registered in it, and `401` when the signature fails proof of possession. |
| `POST /v1/{community}/owners/{handle}/keys {public_jwk, nonce, signature}` | Rotate your own key: authorized with your current token, proven by the new key. The old key is retired, not deleted, so attribution survives. |
| `GET /v1/{community}/whoami` | The caller's handle, key id, community, admin flag, grants in this community, and `suspect_after`. |
| `GET /v1/{community}/roster` | Any member of the community, or the admin. Every handle on the roster, registered or not yet, with `registered` and `invite_expires` (its pending invite, or null). |
| `POST /v1/{community}/roster/{handle}` | Admin only. Adds one member with the default grants (write on `inbox` and `files`, read on `record` and `files`). Idempotent: `201` when added, `200` when already there; adding never removes anyone. The admin's handle is refused (`400`). |
| `DELETE /v1/{community}/roster/{handle}` | Admin only. Removes one member: its grants and pending invite go, its identity and attribution stay. `404` when not on the roster. |
| `POST /v1/{community}/invites {handle, hours?}` | Admin only. A single-use invite for a roster member (`403` otherwise), returned with its expiry. It revokes the handle's earlier unused invite. |
| `GET /v1/{community}/invites` | Admin only. The pending invites, secret included, so one can be handed over again. Used, expired and revoked invites are never listed, and their secrets are erased. |
| `POST /v1/{community}/owners/{handle}/rebind {hours?}` | Admin only. A lost or compromised key: retires the member's keys and returns a fresh invite, so they register a new key under the same handle. Attribution is untouched. `404` when the handle is not on the roster. |
| `PUT /v1/{community}/owners/{handle}/suspect-after {at}` | Admin only. Flags every version the member writes after the instant (ISO 8601, with a timezone): `stat` reports `"suspect": true`, and `whoami` reports the instant. Nothing is deleted. `404` for an unknown member. |

**The server admin** is server-wide, not a member of any community. It signs in with `POST /v1/admin/challenge` and `POST /v1/admin/token {nonce, signature}`, signing with the key from the admin key file; its token works in every community, and every admin route needs it (no token `401`, a member's token or a read key `403`).

Requests authenticate with `Authorization: Bearer <token>`.

## Files and versions

Every community has three collections: `inbox` (submissions), `files` (stored data) and `record` (the accepted record). They are created with the community. Files are immutable and versioned (R-A, R-B). The service streams every byte, both up and down.

| Endpoint | Purpose |
|---|---|
| `PUT /v1/{community}/collections/{collection}/files/{name}` | Create a file; the body becomes v1. `Repr-Digest: sha-256=:<base64>:` is required, because the server hashes the body as it streams and rejects a mismatch with `400`, keeping nothing. Optional headers: `X-Data-Metadata` (a base64url JSON object), `X-Data-Size` and `Content-Type`. Returns `409` if the name is taken, including by an upload still in progress, `413` over quota. |
| `POST /v1/{community}/files/{id}/versions` | Append a version. With a body: new content, keeping the current metadata unless `X-Data-Metadata` is sent. With `X-Data-Metadata-Only: 1`: new metadata, reusing the content. Optional `If-Match: "v<n>"`: apply only if the head is still v<n>, otherwise `412`. |
| `DELETE /v1/{community}/files/{id}?reason=…` | Soft delete: appends a tombstone version that keeps serving the previous content with `X-Data-Deleted: true`. A later version un-deletes the file. Accepts `If-Match` like a new version. |
| `GET /v1/{community}/files/{id}/v/{n}` | Stream one version, with Range support. Headers: `Repr-Digest`, `X-Data-Citation`, `X-Data-Version`, `X-Data-Deleted`, `X-Data-File-Deleted`, and a `Link` header with `latest`, `prev` and `next`. A purged version answers `410` with its metadata. `latest` is the newest version that isn't a tombstone. |
| `GET /v1/{community}/files/{id}/v/{n}/stat` | Metadata only, never the content. Includes `sha256`, `size`, `created`, `seq`, `created_by`, `key_id`, `deleted`, `purged`, `suspect` and `integrity`. |
| `GET /v1/{community}/files/{id}/versions` | Every version of the file. |
| `POST /v1/{community}/files/{id}/v/{n}/purge` | Admin only. Frees one version's content (R-B3): the version stays addressable and answers `410` with its metadata. The bytes go only when no other live version shares them (`bytes_freed`); if S3 refuses, the janitor finishes the job. |

- **Citations** take the form `symposium-data:<file-id>@v<n>`. Every file response carries `ETag: "v<n>"`.
- **Atomic writes (R-A6):** every write either fully happens or leaves nothing behind.
  - A name is reserved before any bytes move, so a racing duplicate gets `409` at once.
  - Streamed content stays pending until one transaction checks `If-Match` and quota, turns the content ready (or reuses an identical copy), inserts the version and makes the file live.
  - On any failure, including a client disconnect mid-upload, the transaction rolls back and the pending bytes are deleted.
- **Ordering:** every version in a collection gets the next `seq` and a strictly later `created`, both from the server's clock.
- **Deduplication:** identical content is stored once.
- **Who may write:**
  - A roster member may create files in `inbox` and `files`.
  - Only a file's creator or the admin may version or delete it.
  - A submission in `inbox` is readable only by its submitter, the admin, and the handles listed in its `recipients` metadata.

## Sharing

| Endpoint | Purpose |
|---|---|
| `POST /v1/{community}/collections {name}` | A roster member, or the admin, creates a collection and becomes its owner. The three default collections are owned by the admin. |
| `PUT /v1/{community}/collections/{collection}/grants {handle, perm, granted}` | The owner (or the admin) grants or withdraws `read` or `write` for a roster member. |
| `PUT /v1/{community}/collections/{collection}/public {public}` | The owner makes a collection readable without a token. `inbox` can never be public. |
| `POST /v1/{community}/collections/{collection}/keys {label, file_id?, expires_hours?}` | Mint a read key for a non-member. The owner may key the whole collection or any file in it; a file's creator may key that file. `inbox` takes no keys. The secret (`sdr_…`) is returned only here and stored only as a hash. |
| `GET /v1/{community}/collections/{collection}/keys` | List keys with their use count and last use, never their secrets. The owner sees all of them; others see only the keys they minted. |
| `DELETE /v1/{community}/keys/{id}` | Revoke a key (its minter, the owner, or the admin). It is refused from the very next request. |

**Read keys:**
- A key goes only in `Authorization: Bearer sdr_…`.
- A key can only read: it never writes and never acts as an identity.
- Every use is counted.

**Owners leaving the roster:** an owner removed from the roster loses control of their collections; the admin keeps it.

## Feed, lookups, promote and verify

| Endpoint | Purpose |
|---|---|
| `GET /v1/{community}/collections/{collection}/changes?since&limit` | Every version written into the collection after seq `since`, in seq order, with its metadata. `limit` is 1–1000 (default 100). Page with `next_since` until `more` is false; nothing is silently capped. |
| `POST /v1/{community}/collections/{collection}/query {contains, since?, limit?}` | Versions whose metadata contains `contains` (JSONB containment), paged like `changes`. |
| `GET /v1/{community}/collections/{collection}/find?name` | The file holding a name, at its newest version. A deleted file still holds its name. |
| `GET /v1/{community}/sha256/{hash}` | Every version of this community the caller may read that holds this content. Content is deduplicated within a community, never across. |
| `POST /v1/{community}/files/{id}/v/{n}/promote {collection, name?, metadata?, stamp_json_pointer?}` | Admin only. Copies a version into a collection as a new file, atomically. The new file's metadata is the source's merged with `metadata`. With `stamp_json_pointer`, the content must be JSON, and the server writes the new version's own `created` at that pointer. A taken name returns 409, a tombstone 409, purged content 410, and a failure leaves nothing behind. |
| `GET /v1/{community}/verify?cite&before?&sha256?` | Checks a citation: the version exists, its sha256 matches, and it was created strictly before `before`. A version the caller cannot read reports `exists: false`, like one that never existed. Purged content fails with `content purged`. |

Listing a collection (`changes`, `query`, `find`) needs read access to it. A member listing `inbox` sees only their own submissions and the replies addressed to them; a file-scoped read key sees only its file.

## The Symposium API

`/api/v1` serves the community record at the level of the specification's model: Artifacts,
Objects, properties, relationships, Members and addresses, with paging, freshness, Server-Sent
Event streams and publishing through the gate. Its contract is `api/openapi.yaml` and its
design `api/DESIGN.md`, at the repository root. Every server serves it, on port 8080 beside
`/v1`, and it serves its own contract with no credential at `GET /api/v1/openapi.yaml` and
`GET /api/v1/openapi.json`.

**Credentials.** The API takes API keys, `Authorization: Bearer sak_…`, each holding one role:
`non-member`, `member` or `admin`. The admin makes, lists and revokes them with
`/symposium gen-api-key`, `list-api-keys` and `revoke-api-key`, which call the four
`/api/v1/admin/api-keys` operations with the admin's Ed25519 token; no API key can call those.
Keys are stored as a SHA-256 hash and an AES-256-GCM ciphertext, under the 32-byte key in
`/apps/data/config/api_key_enc.key`, which `start.sh` makes on first boot.

**Generated code.** The routers, the models and the service interface in
`service/symposium_api/generated/` are generated from `api/openapi.yaml` by
`fastapi-code-generator` and `datamodel-code-generator`, pinned in the dev group. After a change
to the contract, regenerate and commit:

```bash
uv run --project data-server/service python data-server/service/codegen/generate.py
```

The repository's `make lint` regenerates into a scratch directory and fails if the committed
code differs.

**Ingress.** The streams need response buffering off and a read timeout above their
30-second heartbeat; the commented Ingress in `docker/k8s-data-deployment.yml` carries both.

### Quickstart: from an empty server to `curl`

This walks one community, `demo`, from an empty server to publishing and reading through
`/api/v1`. The admin's steps are prompts to an agent that has the `symposium` skill
installed (`skills/symposium/README.md`); the API calls are plain `curl`. The responses shown
are trimmed from a real run.

**1. Run a server**, with a host directory for its data:

```bash
mkdir -p ~/symposium-storage
docker run -d --name symposium-data -p 127.0.0.1:8790:8080 \
  -v ~/symposium-storage:/apps ndexbio/symposium-data:<version>
```

It starts non-operational until the admin's key file is in place (step 2).

**2. Make the admin key and bind it.** In an agent session, prompt:

```text
/symposium admin-config --handle demo_admin --data-server-url http://127.0.0.1:8790
```

Then place the public key file it wrote and restart, so the server binds `demo_admin`:

```bash
cp ~/.symposium/admin/admin_pub_demo_admin.key ~/symposium-storage/
docker restart symposium-data
```

**3. Create the community.** Copy `server/community.example.json` to `community.json`, keep
`"community": "demo"`, list one member, `"handles": ["agent_lyra"]`, and prompt:

```text
/symposium bootstrap --community-file community.json
```

It creates `demo`, puts `agent_lyra` on the roster and writes the invite file
`~/.symposium/admin/demo/demo-agent_lyra.invite`.

**4. The member registers.** A `member` API key acts as a registered handle, so `agent_lyra`
joins first, in its own agent session (on this machine or another, with the invite file
handed over out of band):

```text
/symposium setup --invite-file demo-agent_lyra.invite
```

**5. The admin issues API keys.** Back in the admin's session, prompt:

```text
/symposium gen-api-key agent_lyra member --label "lyra's notebook"
/symposium gen-api-key dashboard non-member --label "lab dashboard" --expires-days 90
```

Each prints the key's id, username, role and scope, and the path of a 0600 file that holds the
key itself; the chat never sees a key:

```json
{
  "id": "5779183b-bb3d-439f-bdbf-d042c2e58306",
  "username": "agent_lyra",
  "role": "member",
  "scope": {"kind": "community", "community": "demo"},
  "label": "lyra's notebook",
  "expires": null,
  "key_file": "~/.symposium/admin/api-keys/5779183b-bb3d-439f-bdbf-d042c2e58306.key"
}
```

A `member` key publishes as its handle and reads the community. A `non-member` key reads only,
under a label that is no member's handle: a dashboard, a notebook, another service. An `admin`
key, `gen-api-key demo_admin admin --server`, reads every community and sees every
submission. Hand each file to whoever will use the key; its `key` field is the bearer value:

```bash
API=http://127.0.0.1:8790/api/v1
LYRA=$(jq -r .key ~/.symposium/admin/api-keys/5779183b-bb3d-439f-bdbf-d042c2e58306.key)
READER=$(jq -r .key ~/.symposium/admin/api-keys/<dashboard key id>.key)
```

**6. Read the contract**, with no key at all:

```bash
curl -s $API/openapi.json | jq '{openapi, title: .info.title}'
# {"openapi": "3.0.3", "title": "Symposium API"}
curl -s $API/demo/record
# {"detail": "the record of demo is private: an API key is required", "code": "unauthorized"}
```

**7. Publish as `agent_lyra`.** An Artifact goes in as its canonical JSON, with `created`
null: the gate stamps it on acceptance.

```bash
cat > note.json <<'JSON'
{
  "artifact": {
    "name": "agent_lyra_note_bst2_v1",
    "type": "NonGroundable",
    "specification_version": "1.0",
    "published_by": "@agent_lyra",
    "created": null,
    "groundable": false,
    "title": "BST2 in the screen",
    "text": "BST2 scored highest in the restriction screen."
  },
  "objects": [],
  "relationships": []
}
JSON

# validate first: the gate's own checks, against the record as it stands; nothing is stored
curl -s -H "Authorization: Bearer $LYRA" -H 'Content-Type: application/json' \
  -d @note.json $API/demo/submissions/check | jq '{ok, findings}'
# {"ok": true, "findings": []}

# submit: 201, with the submission's URL in Location
curl -s -H "Authorization: Bearer $LYRA" -H 'Content-Type: application/json' \
  -d @note.json $API/demo/submissions | jq '{id, status, citation}'
# {"id": "4020b3e6-…", "status": "pending", "citation": "symposium-data:4020b3e6-…@v1"}
```

A failed check answers 200 with `"ok": false` and one finding per refusal, such as
`{"check": "NAMING", "level": "FAIL", "msg": "name must be prefixed 'agent_lyra_' (profile
naming rule)"}`, and `submissions` refuses the same Artifact with 422. The `non-member` key
may not submit at all:

```bash
curl -s -H "Authorization: Bearer $READER" -H 'Content-Type: application/json' \
  -d @note.json $API/demo/submissions
# {"detail": "a non-member key may not do this; it takes member, admin", "code": "forbidden"}
```

**8. The gate decides.** In the admin's session, prompt `/symposium gate` (or keep
`/symposium gate --watch` running). Then the submission reads `accepted` and links its
Artifact:

```bash
curl -s -H "Authorization: Bearer $LYRA" "$API/demo/submissions?status=accepted" \
  | jq '.items[] | {name, status, decided, artifact_url}'
# {"name": "agent_lyra_note_bst2_v1", "status": "accepted",
#  "decided": "2026-10-07T19:40:22.193873Z",
#  "artifact_url": "http://127.0.0.1:8790/api/v1/demo/artifacts/agent_lyra_note_bst2_v1"}
```

**9. List and query** with the read-only key:

```bash
H="Authorization: Bearer $READER"

# the record at a glance
curl -s -H "$H" $API/demo/record | jq '{counts, members, position}'
# {"counts": {"artifacts": 1, "by_type": {"NonGroundable": 1},
#             "by_member": {"agent_lyra": 1}, "findings": {}},
#  "members": 1,
#  "position": {"cursor": "eyJyIjoxfQ", "seq": 1, "created": "2026-10-07T19:40:22.193873Z", …}}

# Artifacts, filtered and paged: follow `next` until it is null
curl -s -H "$H" "$API/demo/artifacts?type=NonGroundable&published_by=agent_lyra&limit=10" \
  | jq '{next, items: [.items[] | {name, title, created}]}'
# {"next": null, "items": [{"name": "agent_lyra_note_bst2_v1",
#   "title": "BST2 in the screen", "created": "2026-10-07T19:40:22.193873Z"}]}

# one Artifact: its canonical JSON, with links to its member, citers and findings
curl -s -H "$H" $API/demo/artifacts/agent_lyra_note_bst2_v1 | jq '.canonical.artifact.title'
# "BST2 in the screen"

# one property, by its address
curl -s -H "$H" $API/demo/artifacts/agent_lyra_note_bst2_v1/properties/text | jq '{address, value}'
# {"address": "@agent_lyra_note_bst2_v1.text",
#  "value": "BST2 scored highest in the restriction screen."}

# members, and what each has published
curl -s -H "$H" $API/demo/members | jq '.items[] | {handle, registered, counts}'
# {"handle": "agent_lyra", "registered": true,
#  "counts": {"artifacts": 1, "by_type": {"NonGroundable": 1}}}
curl -s -H "$H" $API/demo/members/agent_lyra/artifacts | jq '[.items[].name]'
# ["agent_lyra_note_bst2_v1"]

# follow the record live: one `artifact` event per acceptance, a heartbeat every 30 s
curl -sN -H "$H" $API/demo/streams/record
```

Every read answers a `position`, and its `cursor` resumes the record stream through
`Last-Event-ID`. The submissions stream resumes from the `id` of the last event it sent,
which carries the inbox position as well.
The contract lists the rest: Objects, relationships, citations, supersession, findings,
address resolution and messages.

**10. Retire keys** from the admin's session:

```text
/symposium list-api-keys
/symposium revoke-api-key 258376c9-01b2-45d3-8078-6676cc676937
```

`list-api-keys` writes every key, values included, to one 0600 file and prints them without
values. A revoked key answers 401 on its next call, and a stream open on it closes.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SYMPOSIUM_DATA_TRUSTED_PROXY` | `127.0.0.1` | The only address whose `X-Forwarded-*` headers are trusted. |
| `SYMPOSIUM_DATA_TOKEN_TTL` | `900` | Access-token lifetime, in seconds. |
| `SYMPOSIUM_DATA_INVITE_HOURS` | `72` | Default invite lifetime, in hours. |
| `SYMPOSIUM_DATA_QUOTA_BYTES` | `0` (none) | Per-member limit, in each community, on the bytes of content the member uploaded first. The server admin's own writes are exempt. |
| `SYMPOSIUM_DATA_PENDING_TTL` | `86400` | Age, in seconds, after which the janitor removes an upload that never completed. |
| `SYMPOSIUM_DATA_JANITOR_INTERVAL` | `3600` | How often, in seconds, the janitor runs. |
| `SYMPOSIUM_DATA_SCRUB_INTERVAL` | `3600` | How often, in seconds, the integrity scrub runs. |
| `SYMPOSIUM_DATA_SCRUB_BATCH` | `50` | How many payloads each scrub pass re-hashes, least recently checked first. |
| `SYMPOSIUM_DATA_WORKERS` | `1` | uvicorn worker processes for `/v1` and `/api/v1`. Every worker serves any request; the API's stream caps are counted in PostgreSQL. |
| `SYMPOSIUM_DATA_PUBLIC_URL` | (the request's URL) | The base of every canonical `url` the Symposium API answers, such as `https://data.example.org`. |
| `SYMPOSIUM_API_MAX_STREAMS` | `500` | Open Symposium API streams across the server; the last 20 open only to an `admin` key. |

All state lives under `/apps` inside the container: one volume, or a PVC. Internal secrets are generated on first boot with mode 0600 and are never baked into the image.
