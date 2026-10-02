# Symposium Data server

A single Docker image that runs Symposium Data, the versioned file store Symposium communities use to persist, share and cite data files. The image contains three services, managed by `supervisord`:

- **the data service**: FastAPI on port 8080, the only port the container exposes;
- **PostgreSQL 16**: the server's records: configuration, owner identities, rosters, grants, invites, collections, files, versions, metadata and read keys. All of it is managed by Alembic migrations;
- **SeaweedFS**: the internal S3 store for file contents. It is never exposed; the data service streams every byte.

The design and requirements are in the spike on ndexbio/symposium#13. Its sections are referred to here as R-*.

## Layout

| Path | What it is |
|---|---|
| `service/` | The `symposium_data` Python package: the HTTP API, `data-admin` and the Alembic migrations, plus the tests. Locked with `uv.lock`. |
| `docker/Dockerfile` | Multi-stage build: `runtime-base` (PostgreSQL, supervisor, gosu, SeaweedFS with a pinned sha256), then `builder` (installs the locked wheel into `/opt/venv`), then `deploy`. |
| `docker/supervisord/` | One config snippet per service. `start.sh` assembles them. |
| `docker/scripts/start.sh` | Container start-up: version banner, first-boot secrets, PostgreSQL init, the one-time port when `PORT_NDEX_URL` is set, registration guard, then `exec supervisord`. |
| `docker/k8s-data-deployment.yml` | Kubernetes or Podman deployment on a single ReadWriteOnce PVC. |
| `docker/k8s-data-port-job.yml` | The one-time port-ndex bootstrap as a Kubernetes Job (`PORT_NDEX.md`). |
| `RUNBOOK.md` | How to run, initialize, verify and tear down. |
| `PORT_NDEX.md` | The one-time port-ndex bootstrap of a fresh server from an NDEx community. |

## Make targets

These four targets are the only ones. Run them from this folder, or from the repository root with `make -C data-server <target>`.

| Target | What it does |
|---|---|
| `lint` | `ruff check` and `ruff format --check` on `service/`. |
| `test` | `lint`, then the unit suites, then builds the image `ndexbio/symposium-data:$(TAG)`, then runs the integration suites against that image in throwaway `sdtest-*` containers. |
| `build-docker` | `test`, then confirms that the tested image `ndexbio/symposium-data:$(TAG)` exists. |
| `push-docker` | `build-docker`, then a buildx multi-arch (`linux/amd64`, `linux/arm64`) push of `:$(TAG)` and `:latest`. It is used by the release workflow. |

`TAG` defaults to the version in `service/pyproject.toml`; override it with `make build-docker TAG=1.2.3`. The image is built with `DATA_VERSION=$(TAG)`. The container prints `symposium-data <version>` as its first line of output, and `GET /v1/status` reports the same version. `/v1/status` also reports health: it answers **503**, with `"postgres"` or `"s3"` set to `"unavailable"`, whenever either dependency is down. The Kubernetes readiness probe relies on this.

**Requirements:** Docker and [uv](https://docs.astral.sh/uv/). `uv` installs Python 3.11 and the locked dependencies itself.

## Releases

Pushing a tag `data-server-v<version>` from the `data-store` branch runs `.github/workflows/release.yml`. That workflow runs `make push-docker TAG=<version>`, which publishes `ndexbio/symposium-data:<version>` and `:latest`. It needs the repository secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`.

## Identity

The server provisions no accounts. Each member generates an Ed25519 key on their own machine, and the private key never leaves it. Registration binds a handle to the public key (R-D, Part 2 of the spike).

| Endpoint | Purpose |
|---|---|
| `POST /v1/auth/challenge {handle}` | A single-use nonce, valid for 5 minutes. |
| `POST /v1/auth/token {handle, nonce, signature}` | Sign the nonce with an active key to receive an EdDSA access token (15 minutes by default). |
| `POST /v1/owners {handle, community, public_jwk, nonce, signature, invite?}` | Register. Returns `503` before `data-admin init`, `403` for a handle not on the community's roster, `409` for a handle already registered, and `401` when the signature fails proof of possession. In `invite` mode a valid, unused invite bound to the handle is also required. |
| `POST /v1/owners/{handle}/keys {public_jwk, nonce, signature}` | Rotate your own key: authorized with your current token, proven by the new key. The old key is retired, not deleted, so attribution survives. |
| `GET /v1/whoami` | The caller's handle, key id, admin flag, communities with their grants, and `suspect_after`. |
| `PUT /v1/c/{community}/roster {handles}` | Admin only. Replaces the roster. New members get the default grants (write on `inbox` and `files`, read on `record` and `files`). Removed members lose every grant in the community but keep their identity. |

Requests authenticate with `Authorization: Bearer <token>`.

## Files and versions

Every community has three collections: `inbox` (submissions), `files` (stored data) and `record` (the accepted record). They are created when the admin first sets its roster. Files are immutable and versioned (R-A, R-B). The service streams every byte, both up and down.

| Endpoint | Purpose |
|---|---|
| `PUT /v1/c/{community}/{collection}/files/{name}` | Create a file; the body becomes v1. `Repr-Digest: sha-256=:<base64>:` is required, because the server hashes the body as it streams and rejects a mismatch with `400`, keeping nothing. Optional headers: `X-Data-Metadata` (a base64url JSON object), `X-Data-Size` and `Content-Type`. Returns `409` if the name is taken, including by an upload still in progress, `413` over quota. |
| `POST /v1/files/{id}/versions` | Append a version. With a body: new content, keeping the current metadata unless `X-Data-Metadata` is sent. With `X-Data-Metadata-Only: 1`: new metadata, reusing the content. Optional `If-Match: "v<n>"`: apply only if the head is still v<n>, otherwise `412`. |
| `DELETE /v1/files/{id}?reason=…` | Soft delete: appends a tombstone version that keeps serving the previous content with `X-Data-Deleted: true`. A later version un-deletes the file. Accepts `If-Match` like a new version. |
| `GET /v1/files/{id}/v/{n}` | Stream one version, with Range support. Headers: `Repr-Digest`, `X-Data-Citation`, `X-Data-Version`, `X-Data-Deleted`, `X-Data-File-Deleted`, and a `Link` header with `latest`, `prev` and `next`. A purged version answers `410` with its metadata. `latest` is the newest version that isn't a tombstone. |
| `GET /v1/files/{id}/v/{n}/stat` | Metadata only, never the content. Includes `sha256`, `size`, `created`, `seq`, `created_by`, `key_id`, `deleted`, `purged`, `suspect` and `integrity`. |
| `GET /v1/files/{id}/versions` | Every version of the file. |

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
| `POST /v1/c/{community}/collections {name}` | A roster member, or the admin, creates a collection and becomes its owner. The three default collections are owned by the admin. |
| `PUT /v1/c/{community}/{collection}/grants {handle, perm, granted}` | The owner (or the admin) grants or withdraws `read` or `write` for a roster member. |
| `PUT /v1/c/{community}/{collection}/public {public}` | The owner makes a collection readable without a token. `inbox` can never be public. |
| `POST /v1/c/{community}/{collection}/keys {label, file_id?, expires_hours?}` | Mint a read key for a non-member. The owner may key the whole collection or any file in it; a file's creator may key that file. `inbox` takes no keys. The secret (`sdr_…`) is returned only here and stored only as a hash. |
| `GET /v1/c/{community}/{collection}/keys` | List keys with their use count and last use, never their secrets. The owner sees all of them; others see only the keys they minted. |
| `DELETE /v1/keys/{id}` | Revoke a key (its minter, the owner, or the admin). It is refused from the very next request. |

**Read keys:**
- A key goes only in `Authorization: Bearer sdr_…`.
- A key can only read: it never writes and never acts as an identity.
- Every use is counted.

**Owners leaving the roster:** an owner removed from the roster loses control of their collections; the admin keeps it.

## Feed, lookups, promote and verify

| Endpoint | Purpose |
|---|---|
| `GET /v1/c/{community}/{collection}/changes?since&limit` | Every version written into the collection after seq `since`, in seq order, with its metadata. `limit` is 1–1000 (default 100). Page with `next_since` until `more` is false; nothing is silently capped. |
| `POST /v1/c/{community}/{collection}/query {contains, since?, limit?}` | Versions whose metadata contains `contains` (JSONB containment), paged like `changes`. |
| `GET /v1/c/{community}/{collection}/find?name` | The file holding a name, at its newest version. A deleted file still holds its name. |
| `GET /v1/sha256/{hash}` | Every version the caller may read that holds this content. |
| `POST /v1/files/{id}/v/{n}/promote {collection, name?, metadata?, stamp_json_pointer?}` | Admin only. Copies a version into a collection as a new file, atomically. The new file's metadata is the source's merged with `metadata`. With `stamp_json_pointer`, the content must be JSON, and the server writes the new version's own `created` at that pointer. A taken name returns 409, a tombstone 409, purged content 410, and a failure leaves nothing behind. |
| `GET /v1/verify?cite&before?&sha256?` | Checks a citation: the version exists, its sha256 matches, and it was created strictly before `before`. A version the caller cannot read reports `exists: false`, like one that never existed. Purged content fails with `content purged`. |

Listing a collection (`changes`, `query`, `find`) needs read access to it. A member listing `inbox` sees only their own submissions and the replies addressed to them; a file-scoped read key sees only its file.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SYMPOSIUM_DATA_REGISTRATION` | `invite` | `open`: a handle on the roster may register (for a server bound to localhost). `invite`: it also needs a single-use invite (for a server reachable by other machines). In `invite` mode the container refuses to start without `SYMPOSIUM_DATA_PUBLIC_BASE_URL`. |
| `SYMPOSIUM_DATA_PUBLIC_BASE_URL` | none | The public URL of the server. Required in `invite` mode; reported by `GET /v1/status`. |
| `SYMPOSIUM_DATA_TRUSTED_PROXY` | `127.0.0.1` | The only address whose `X-Forwarded-*` headers are trusted. |
| `SYMPOSIUM_DATA_TOKEN_TTL` | `900` | Access-token lifetime, in seconds. |
| `SYMPOSIUM_DATA_INVITE_HOURS` | `72` | Default invite lifetime, in hours. |
| `SYMPOSIUM_DATA_QUOTA_BYTES` | `0` (none) | Per-owner limit on the bytes of content the owner uploaded first. |
| `SYMPOSIUM_DATA_PENDING_TTL` | `86400` | Age, in seconds, after which the janitor removes an upload that never completed. |
| `SYMPOSIUM_DATA_JANITOR_INTERVAL` | `3600` | How often, in seconds, the janitor runs. |
| `SYMPOSIUM_DATA_SCRUB_INTERVAL` | `3600` | How often, in seconds, the integrity scrub runs. |
| `SYMPOSIUM_DATA_SCRUB_BATCH` | `50` | How many payloads each scrub pass re-hashes, least recently checked first. |

All state lives under `/apps` inside the container: one volume, or a PVC. Internal secrets are generated on first boot with mode 0600 and are never baked into the image.
