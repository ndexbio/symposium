# Symposium Data server

A single Docker image that runs Symposium Data, the versioned file store Symposium communities use to persist, share and cite data files. The image contains three services, managed by `supervisord`:

- **the data service**: FastAPI on port 8080, the only port the container exposes;
- **PostgreSQL 16**: the server's records: configuration, owner identities, rosters, grants, invites, collections, files, versions, metadata and read keys. All of it is managed by Alembic migrations;
- **SeaweedFS**: the internal S3 store for file contents. It is never exposed; the data service streams every byte.

**To run a server**, start with `RUNBOOK.md`: `docker run` (or the Kubernetes manifest), then place the admin's key file. This README covers the build, the make targets and the API.

## Layout

| Path | What it is |
|---|---|
| `service/` | The `symposium_data` Python package: the HTTP API, its background jobs and the Alembic migrations, plus the tests. Locked with `uv.lock`. |
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
| `build-docker` | Builds and tags the image `ndexbio/symposium-data:$(TAG)`. |
| `push-docker` | A buildx multi-arch (`linux/amd64`, `linux/arm64`) build and push of `:$(TAG)` and `:latest`. It is used by the release workflow, on a tag cut from a `data-store` commit that CI has tested. |

`TAG` defaults to the version in `service/pyproject.toml`; override it with `make build-docker TAG=1.2.3`. The image is built with `DATA_VERSION=$(TAG)`. The container prints `symposium-data <version>` as its first line of output, and `GET /v1/status` reports the same version. `/v1/status` also reports health: it answers **503**, with `"postgres"` or `"s3"` set to `"unavailable"`, whenever either dependency is down. The Kubernetes readiness probe relies on this. It reports the server's `mode` too (see "The admin key file").

**Requirements:** Docker and [uv](https://docs.astral.sh/uv/). `uv` installs Python 3.11 and the locked dependencies itself.

## Releases

Pushing a tag `data-server-v<version>` from the `data-store` branch runs `.github/workflows/release.yml`. That workflow runs `make push-docker TAG=<version>`, which publishes `ndexbio/symposium-data:<version>` and `:latest`. It needs the repository secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`.

## The admin key file

Nobody has a shell on the server (R-D7): every admin operation is an admin-only route. The admin's **public** key is a file on the volume, `/apps/admin_pub_<handle>.key`, holding the public JWK that Symposium's `admin-config` writes (mode 0644). The API reads it at every start-up (R-D4):

| At start-up | Result |
|---|---|
| Not yet initialized, exactly one key file | Binds that handle and key, and saves a backup, `/apps/data/config/admin_pub.backup`. |
| Initialized, the admin's file holds the bound key | Starts normally. |
| Initialized, the admin's file holds a different key | **Rebinds**: the old admin keys are retired, the new one is bound, the backup is updated, and it is logged. |
| Initialized, the admin's file missing, the backup present | Starts normally from the backup and logs a warning. Nothing is written to `/apps`. |
| A key file naming another handle | Ignored, with an error naming both handles: the admin handle never changes. |
| No key file, not initialized | Non-operational: `admin key not provided`. |
| Several key files, not initialized | Non-operational: `ambiguous admin key files`. |
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

All state lives under `/apps` inside the container: one volume, or a PVC. Internal secrets are generated on first boot with mode 0600 and are never baked into the image.
