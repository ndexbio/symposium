# Symposium Data server

A single Docker image that runs Symposium Data, the versioned file store Symposium communities use to persist, share and cite data files. The image contains three services, managed by `supervisord`:

- **the API service**: FastAPI on port 8080, the container's one exposed port. It serves two REST APIs: the **Symposium Control API** under `/v1`, for the skill's CLI, and the **Symposium Data API** under `/api/v1`, for web apps and services;
- **PostgreSQL 16**: configuration, owner identities, rosters, grants, invites, collections, files, versions, metadata and read keys, managed by Alembic migrations;
- **SeaweedFS**: the internal S3 store for file contents, which the API service streams.

**To run a server**, start with [`RUNBOOK.md`](RUNBOOK.md): `docker run`, or the Helm chart on Kubernetes, then place the admin's key file. The image is published as [`ndexbio/symposium-data` on Docker Hub](https://hub.docker.com/r/ndexbio/symposium-data), one tag per release plus `:latest`, and the chart as `oci://registry-1.docker.io/ndexbio/symposium-helm`. This README covers the build, the make targets and both APIs.

## Layout

| Path | What it is |
|---|---|
| `service/` | The `symposium_data` Python package: the Symposium Control API (`/v1`), the storage both APIs read, its background jobs and the Alembic migrations, plus the tests. Locked with `uv.lock`. |
| `service/symposium_api/` | The Symposium Data API (`/api/v1`): `generated/`, generated from `api/openapi.yaml`, and the hand-written service behind it. |
| `service/symposium_server/` | The composition root uvicorn starts: the Control API's app with the Data API mounted at `/api/v1`. |
| `service/codegen/` | The Data API's generator script and its templates. After a change to `api/openapi.yaml`, run `uv run --project data-server/service python data-server/service/codegen/generate.py` and commit the result; the repository's `make lint` checks it. |
| `docker/Dockerfile` | Multi-stage build: `runtime-base` (PostgreSQL, supervisor, gosu, SeaweedFS with a pinned sha256), then `builder` (installs the locked wheel into `/opt/venv`), then `deploy`. |
| `docker/supervisord/` | One config snippet per service. `start.sh` assembles them. |
| `docker/scripts/start.sh` | Container start-up: version banner, first-boot secrets, PostgreSQL init, then starts supervisord. |
| `helm/symposium-helm/` | The Helm chart: the server on Kubernetes, on a single ReadWriteOnce PVC, exposed through a Gateway API HTTPRoute or an Ingress, with the admin key from its values. Its `README.md` lists every value. |
| [`RUNBOOK.md`](RUNBOOK.md) | How to choose a deployment and run it (Docker, Docker Desktop's Kubernetes or a remote cluster, with the chart), place the admin key, port a community off NDEx (port-ndex), host many communities, export and import, verify and tear down. |
| [`PORT_NDEX.md`](PORT_NDEX.md) | The port-ndex: copying a community's record from NDEx into an empty community here. |

## Make targets

Run them from this folder, or from the repository root with `make -C data-server <target>`. The repository's top-level `make test` runs this `test` alongside the top-level suite.

| Target | What it does |
|---|---|
| `lint` | `ruff check` and `ruff format --check` on `service/`. |
| `test` | `lint`, `build-docker`, `k8s-tools` and `helm-package`, then `service-suites` and `chart-e2e` in parallel, each logging to `dist/test-logs/`, printed once both finish. Every wait is for an event or a state, bounded by `MAX_PER_TEST_WAIT` (seconds, default `120`). |
| `service-suites` | The unit suites, then the integration suites against the image already built, on one `sdtest-*` container for the whole session, including the chart's lint, render and kubeconform checks. |
| `chart-e2e` | `helm-e2e`'s test on the image and package already made. |
| `build-docker` | Builds and tags the image `ndexbio/symposium-data:$(TAG)` locally. The build takes `../tools` (the `symposium_rules` package) and `../api` (the contract) as the named build contexts `rules` and `api`. |
| `push-docker` | A buildx multi-arch (`linux/amd64`, `linux/arm64`) build and push of `:$(TAG)` and `:latest`, run by the release workflow on a `data-server-v<version>` GitHub release. |
| `helm-package` | `helm lint --strict`, then `dist/symposium-helm-<version>.tgz`, the chart's version from `helm/symposium-helm/Chart.yaml`. |
| `helm-push` | Pushes that package to Docker Hub, as `oci://registry-1.docker.io/ndexbio/symposium-helm:<version>`. It requires `CHART_TAG` to equal the chart's version, the image it deploys (its `appVersion`) to be on Docker Hub, and `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`. Run by the release workflow on a `symposium-helm-v<version>` GitHub release. |
| `helm-attach` | Attaches that package to the `symposium-helm-v<version>` GitHub release (`gh`), with the same `CHART_TAG` check. |
| `helm-e2e` | The chart's live test: a kind cluster made for it on this machine's Docker, with its own kubeconfig, and deleted after it. It loads the image this commit built into the cluster and runs the chart this commit packaged through install, the admin key, uninstall and reinstall on the kept volume. |
| `k8s-tools` | Fetches the pinned `helm`, `kind` and `kubectl` for this machine (linux or darwin, amd64 or arm64) into `.tools/`, each checked against the sha256 its project publishes beside the download. The chart targets use these. |

`TAG` defaults to the version in `service/pyproject.toml`; override it with `make build-docker TAG=1.2.3`. The container prints `symposium-data <version>` as its first line of output, and `GET /v1/status` reports the same version, the server's `mode` (see "The admin key file") and its health: it answers **503**, with `"postgres"` or `"s3"` set to `"unavailable"`, when either dependency is down. The chart's readiness probe uses this.

**Requirements:** Docker and [uv](https://docs.astral.sh/uv/). `uv` installs Python 3.11 and the locked dependencies, and the chart targets fetch their own pinned tools.

## Releases

Publishing a GitHub release runs `.github/workflows/release.yml`, and the release tag's prefix selects the job. The data server has two releases, each versioned independently:

- **`data-server-v<version>`**, the docker image: the `push-image` job runs `make push-docker TAG=<version>`, which publishes `ndexbio/symposium-data:<version>` and `:latest`.
- **`symposium-helm-v<version>`**, the chart: the `push-chart` job runs `make helm-push helm-attach CHART_TAG=<version>`, which publishes `oci://registry-1.docker.io/ndexbio/symposium-helm:<version>` and attaches `symposium-helm-<version>.tgz` to the release. `<version>` is the chart's own `version`; its `appVersion` is the image it deploys, which a unit test keeps equal to `service/pyproject.toml`'s version, so each new image ships with a new chart.

Release the image first, then the chart, then the skill (`symposium-v<version>`). Both jobs need the repository secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`, an organization access token with push on `ndexbio/symposium-data` and `ndexbio/symposium-helm`.

## The admin key file

Every admin operation is an admin-only API route. The admin's **public** key is a file, `admin_pub_<handle>.key`, holding the public JWK that Symposium's `admin-config` writes (mode 0644). It goes in `/apps/` (copied into the host directory mounted there) or in `/apps/admin-key/` (where the Helm chart mounts the Secret holding it). The API reads it at every start-up:

| At start-up | Result |
|---|---|
| Not yet initialized, exactly one key file | Binds that handle and key, and saves a backup, `/apps/data/config/admin_pub.backup`. |
| Initialized, the admin's file holds the bound key | Starts normally. |
| Initialized, the admin's file holds a different key | **Rebinds**: the old admin keys are retired, the new one is bound, the backup is updated, and it is logged. |
| Initialized, the admin's file missing, the backup present | Starts normally from the backup and logs a warning. |
| A key file naming another handle | Ignored, with an error naming both handles: the admin handle is fixed once bound. |
| No key file, not initialized | Non-operational: `admin key not provided`. |
| Several key files, not initialized, or two for one handle (one in each place) | Non-operational: `ambiguous admin key files`. |
| The key file is not a usable public key (not JSON, not an Ed25519 public JWK, or a private key) | Non-operational: `admin key invalid`, with an error on the console saying why. |
| Initialized, with neither the file nor the backup | Non-operational: `admin key missing`, with an error on the console. |

**Non-operational mode:** every route except `GET /v1/status` answers **501**. `/v1/status` answers 200 with `mode` (`operational` or `non-operational`), the `reason` and the `server_id`; once operational it reports the admin's handle (`admin`) and key `fingerprint` (its RFC 7638 thumbprint) in place of a reason. To recover, fix the key file and restart the server.

## The Symposium Control API

The Symposium Control API, at `/v1`, is the API the skill's `symposium-data` CLI speaks. Clients authenticate with a member's or the server admin's Ed25519 private key, by a signed challenge and a short-lived token. It maps one to one onto the Symposium data model as the server stores it (communities, identities and rosters, collections, files and versions, grants and read keys), admin operations included. Web apps and services use the [Symposium Data API](#the-symposium-data-api).

### Communities

One server hosts many communities. Each has its own members, identities and data, under `/v1/{community}/…`; `/v1/status`, `/v1/communities` and the admin's sign-in (`/v1/admin/…`) are server-wide.

A community name is 1–20 letters, digits or underscores; `status`, `communities` and `admin` are reserved. A name keeps the case it was created with and is unique and matched ignoring case. An unknown community, or a name that is not a slug, answers `404`.

| Endpoint | Purpose |
|---|---|
| `POST /v1/communities {name}` | Admin only. Creates a community and its default collections. Idempotent: `201` when created, `200` when exactly that name exists; `400` for a name that is not a slug, is reserved, or differs only in case from an existing one. |
| `GET /v1/communities` | Admin only. Every community, with when it was created. |
| `POST /v1/communities/import` (body: an export) | Admin only. Creates the exported community in one transaction: `201` with one entry per member, `409` when the community already exists here or a member's handle is this server's admin, `400` for a damaged stream or a name that is not a slug. Collections the exported admin owned become this server's admin's; versions keep their recorded `created_by`. |
| `GET /v1/{community}/export` | Admin only. The community as a tar stream: one consistent snapshot of its rows, read keys (hashes only) and members' public keys, then every stored payload. |
| `POST /v1/{community}/port-ndex {ndex_url, credentials: {username, password}, page_size?}` | Admin only. Starts a port-ndex into this empty community in the background ([`PORT_NDEX.md`](PORT_NDEX.md)) and answers `202` with its id. `400` if the community holds files, `409` while another port-ndex runs anywhere on the server. |
| `GET /v1/{community}/port-ndex/{id}` | Admin only. A port-ndex's state (`running`, `ok`, or `failed` with a reason), who requested it, and its summary. |

### Identity

Each member generates an Ed25519 key on their own machine, where the private key stays. Registration binds a handle to the public key **within one community**: the same handle in another community is a separate identity, with its own key.

| Endpoint | Purpose |
|---|---|
| `POST /v1/{community}/auth/challenge {handle}` | A single-use nonce, valid for 5 minutes. |
| `POST /v1/{community}/auth/token {handle, nonce, signature}` | Sign the nonce with an active key to receive an EdDSA access token (15 minutes by default), valid only in this community. |
| `POST /v1/{community}/owners {handle, public_jwk, nonce, signature, invite?}` | Register. Members join by invite: a valid, unused invite bound to this handle and community is required. Returns `403` for a handle not on the community's roster or without a valid invite, `409` for a handle already registered in it, and `401` when the signature fails proof of possession. |
| `POST /v1/{community}/owners/{handle}/keys {public_jwk, nonce, signature}` | Rotate your own key: authorized with your current token, proven by the new key. The old key is retired and keeps its attribution. |
| `GET /v1/{community}/whoami` | The caller's handle, key id, community, admin flag, grants in this community, and `suspect_after`. |
| `GET /v1/{community}/roster` | Any member of the community, or the admin. Every handle on the roster, registered or not yet, with `registered` and `invite_expires` (its pending invite, or null). |
| `POST /v1/{community}/roster/{handle}` | Admin only. Adds one member with the default grants (write on `inbox` and `files`, read on `record` and `files`). Idempotent: `201` when added, `200` when already there. The admin's handle is refused (`400`). |
| `DELETE /v1/{community}/roster/{handle}` | Admin only. Removes one member: its grants and pending invite go, every Data API key it made is revoked (`api_keys_revoked` counts them), and its identity and attribution stay. `404` when not on the roster. |
| `POST /v1/{community}/invites {handle, hours?}` | Admin only. A single-use invite for a roster member (`403` otherwise), returned with its expiry. It revokes the handle's earlier unused invite. |
| `GET /v1/{community}/invites` | Admin only. The pending invites, secret included, so one can be handed over again. |
| `POST /v1/{community}/owners/{handle}/rebind {hours?}` | Admin only. A lost or compromised key: retires the member's keys and returns a fresh invite, so they register a new key under the same handle and keep their attribution. `404` when the handle is not on the roster. |
| `PUT /v1/{community}/owners/{handle}/suspect-after {at}` | Admin only. Flags every version the member writes after the instant (ISO 8601, with a timezone): `stat` reports `"suspect": true`, and `whoami` reports the instant. `404` for an unknown member. |

**The server admin** is server-wide. It signs in with `POST /v1/admin/challenge` and `POST /v1/admin/token {nonce, signature}`, signing with the key from the admin key file; its token works in every community, and every admin route needs it (no token `401`, a member's token or a read key `403`).

Requests authenticate with `Authorization: Bearer <token>`.

### Files and versions

Every community has three collections, created with it: `inbox` (submissions), `files` (stored data) and `record` (the accepted record). Files are immutable and versioned, and the service streams their content in both directions.

| Endpoint | Purpose |
|---|---|
| `PUT /v1/{community}/collections/{collection}/files/{name}` | Create a file; the body becomes v1. `Repr-Digest: sha-256=:<base64>:` is required: the server hashes the body as it streams and answers `400` on a mismatch. Optional headers: `X-Data-Metadata` (a base64url JSON object), `X-Data-Size` and `Content-Type`. Returns `409` if the name is taken, including by an upload in progress, `413` over quota. |
| `POST /v1/{community}/files/{id}/versions` | Append a version. With a body: new content, keeping the current metadata unless `X-Data-Metadata` is sent. With `X-Data-Metadata-Only: 1`: new metadata, reusing the content. Optional `If-Match: "v<n>"`: apply only if the head is still v<n>, otherwise `412`. |
| `DELETE /v1/{community}/files/{id}?reason=…` | Soft delete: appends a tombstone version that keeps serving the previous content with `X-Data-Deleted: true`. A later version un-deletes the file. Accepts `If-Match` like a new version. |
| `GET /v1/{community}/files/{id}/v/{n}` | Stream one version, with Range support. Headers: `Repr-Digest`, `X-Data-Citation`, `X-Data-Version`, `X-Data-Deleted`, `X-Data-File-Deleted`, and a `Link` header with `latest`, `prev` and `next`. A purged version answers `410` with its metadata. `latest` is the newest version that isn't a tombstone. |
| `GET /v1/{community}/files/{id}/v/{n}/stat` | Metadata only: `sha256`, `size`, `created`, `seq`, `created_by`, `key_id`, `deleted`, `purged`, `suspect` and `integrity`. |
| `GET /v1/{community}/files/{id}/versions` | Every version of the file. |
| `POST /v1/{community}/files/{id}/v/{n}/purge` | Admin only. Frees one version's content: the version stays addressable and answers `410` with its metadata. Its bytes are freed once no other live version shares them (`bytes_freed`). |

- **Citations** take the form `symposium-data:<file-id>@v<n>`. Every file response carries `ETag: "v<n>"`.
- **Atomic writes:** every write is atomic, a client disconnecting mid-upload included, and a racing duplicate name gets `409` at once.
- **Ordering:** every version in a collection gets the next `seq` and a strictly later `created`, both from the server's clock.
- **Deduplication:** identical content is stored once.
- **Who may write:**
  - A roster member may create files in `inbox` and `files`.
  - Only a file's creator or the admin may version or delete it.
  - A submission in `inbox` is readable only by its submitter, the admin, and the handles listed in its `recipients` metadata.

### Sharing

A member shares files by putting them in a collection they own, then granting another member read or write access to that collection. To share with someone outside the community, the owner mints a read key for the whole collection or for a single file and hands it over.

| Endpoint | Purpose |
|---|---|
| `POST /v1/{community}/collections {name}` | A roster member, or the admin, creates a collection and becomes its owner. The three default collections are owned by the admin. |
| `PUT /v1/{community}/collections/{collection}/grants {handle, perm, granted}` | The owner (or the admin) grants or withdraws `read` or `write` for a roster member. |
| `PUT /v1/{community}/collections/{collection}/public {public}` | The owner makes a collection readable without a token. `inbox` stays private. |
| `POST /v1/{community}/collections/{collection}/keys {label, file_id?, expires_hours?}` | Mint a read key for a non-member, on any collection but `inbox`. The owner may key the whole collection or any file in it; a file's creator may key that file. The secret (`sdr_…`) is returned once, here. |
| `GET /v1/{community}/collections/{collection}/keys` | List keys with their use count and last use. The owner sees all of them; others see the keys they minted. |
| `DELETE /v1/{community}/keys/{id}` | Revoke a key (its minter, the owner, or the admin). It is refused from the next request. |

**Read keys** go in `Authorization: Bearer sdr_…`, read only, and count every use.

**Owners leaving the roster:** control of their collections passes to the admin.

### Feed, lookups, promote and verify

| Endpoint | Purpose |
|---|---|
| `GET /v1/{community}/collections/{collection}/changes?since&limit` | Every version written into the collection after seq `since`, in seq order, with its metadata. `limit` is 1–1000 (default 100). Page with `next_since` until `more` is false. |
| `POST /v1/{community}/collections/{collection}/query {contains, since?, limit?}` | Versions whose metadata contains `contains` (JSONB containment), paged like `changes`. |
| `GET /v1/{community}/collections/{collection}/find?name` | The file holding a name, at its newest version. A deleted file still holds its name. |
| `GET /v1/{community}/sha256/{hash}` | Every version in this community the caller may read that holds this content. |
| `POST /v1/{community}/files/{id}/v/{n}/promote {collection, name?, metadata?, stamp_json_pointer?}` | Admin only. Copies a version into a collection as a new file, atomically. The new file's metadata is the source's merged with `metadata`. With `stamp_json_pointer`, the content must be JSON, and the server writes the new version's own `created` at that pointer. A taken name or a tombstone answers `409`, purged content `410`. |
| `GET /v1/{community}/verify?cite&before?&sha256?` | Checks a citation: the version exists, its sha256 matches, and it was created strictly before `before`. A version the caller cannot read reports `exists: false`. Purged content fails with `content purged`. |

Listing a collection (`changes`, `query`, `find`) needs read access to it. A member listing `inbox` sees their own submissions and the replies addressed to them; a file-scoped read key sees its file.

### API keys for the Data API

Data API keys are issued, listed and revoked here, per community, by their owner: a Member its own `member` keys, with its own Ed25519 token, and the admin the `non-member` keys for applications. The skill's `gen-api-key`, `list-api-keys` and `revoke-api-key` call these routes from the session they run in.

| Route | With a Member's own token | With the admin's token |
|---|---|---|
| `POST /v1/{community}/api-keys {label, expires_days?}` | Creates a `member` key bound to that Member's handle and answers it once, with its value: `201`. `403` once the Member is off the roster. | Creates a `non-member` key for an application: `201`. |
| `GET /v1/{community}/api-keys` | The Member's own keys, with their values, paged with `cursor` and `limit`. | Every key of the community: application keys with their values, Members' keys without. |
| `GET /v1/{community}/api-keys/{key_id}` | One of its own keys, or `404`. | Any key of the community, a Member's without its value. |
| `DELETE /v1/{community}/api-keys/{key_id}` | Revokes one of its own keys. | Revokes an application key; a Member's key answers `404`. |

A label names one live key among its owner's (`409` when taken). Every answer that carries
a key's value is sent `Cache-Control: no-store`. Removing a Member from the roster
(`DELETE /v1/{community}/roster/{handle}`) revokes every key it made.

## The Symposium Data API

The Symposium Data API, at `/api/v1`, is for remote web apps and services. They authenticate
with an API key provisioned by a member of the community, which grants them delegated read and write access to the community record.

`/api/v1` serves the community record at the level of the [Symposium Spec model](../spec/symposium_specification.md): Artifacts,
Objects, properties, relationships, Members and addresses, with paging, freshness, Server-Sent
Event streams and publishing.

**The API contract.** [`api/openapi.yaml`](../api/openapi.yaml) is the OpenAPI v3 specification of
the entire Data API: every path, parameter, request and response body, error and security
scheme. It is the contract clients build against. Because it is standard OpenAPI, it works
with the tools of the OpenAPI ecosystem, such as OpenAPI Generator, `openapi-typescript`,
`openapi-python-client` and oapi-codegen, which turn it into a typed client for your language
in minutes, as well as with documentation viewers and mock servers. The data server publishes
the same OpenAPI spec at `/api/v1/openapi.yaml` and `/api/v1/openapi.json`.

**Credentials.** The Data API takes API keys only, `Authorization: Bearer <api_key>`. Each API key is [issued by one member of a community](#api-keys-for-the-data-api) and the api key is given a role:

- **`member`**: a Member creates its own keys, as many as it needs, each with a label, with
  `/symposium gen-api-key <label>` in its own session. The key carries the Member's handle,
  and every Data API operation that needs a Member identity (publishing, reading its submissions)
  impersonates as that member handle. 
- **`non-member`**: the admin creates these for application usage. The API key names no Member and grants read only on the community record.

A request to the Data API endpoints that does not carry a valid, unrevoked key for the community named in its path is
refused with `401` or `403`.

### Data API Quickstart: from zero to published

This demonstrates creating a community, `demo` on an empty data server to publishing and reading data objects through
`/api/v1`. The admin's steps are prompts to an agent that has the `symposium` skill
installed (`skills/symposium/README.md`); the API calls are plain `curl`. The responses shown
are trimmed from a real run.

**1. Run a server** from the published image, with a host directory for its data:

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

**4. The member registers and makes its own key.** `agent_lyra` joins in its own agent
session, on this machine or another, with the invite file handed over, then creates a key
there:

```text
/symposium setup --invite-file demo-agent_lyra.invite
/symposium gen-api-key "lyra's notebook" --community demo
```

Whatever an application does with this key, it does as `agent_lyra`. A Member may make
several, one per app or machine, each with its own label. The command prints the key's
metadata and the path of a 0600 file that holds the key itself:

```json
{
  "id": "5779183b-bb3d-439f-bdbf-d042c2e58306",
  "community": "demo",
  "role": "member",
  "handle": "agent_lyra",
  "label": "lyra's notebook",
  "expires": null,
  "key_file": "~/.symposium/member/demo/agent_lyra/api-keys/5779183b-bb3d-439f-bdbf-d042c2e58306.key"
}
```

**5. The admin makes an application key.** In the admin's session, prompt:

```text
/symposium gen-api-key "lab dashboard" --community demo --expires-days 90
```

That is a `non-member` key, for read-only applications.

Hand each key file to whoever will use it. Clients send its `key` field as the bearer token:

```bash
API=http://127.0.0.1:8790/api/v1
LYRA=$(jq -r .key ~/.symposium/member/demo/agent_lyra/api-keys/5779183b-bb3d-439f-bdbf-d042c2e58306.key)
READER=$(jq -r .key ~/.symposium/admin/api-keys/<dashboard key id>.key)
```

**6. Read the contract**, which needs no key:

```bash
curl -s $API/openapi.json | jq '{openapi, title: .info.title}'
# {"openapi": "3.0.3", "title": "Symposium Data API"}
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

# validate first: the gate's own checks, against the record as it stands
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
naming rule)"}`, and `submissions` refuses the same Artifact with 422.

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

# the same Artifact's stored canonical JSON (its `links.content`)
curl -s -H "$H" $API/demo/artifacts/agent_lyra_note_bst2_v1/content | jq '.artifact.name'
# "agent_lyra_note_bst2_v1"

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

Every read answers a `position`; send its `cursor` as `Last-Event-ID` to resume the record
stream from there. The contract covers the rest: Objects, relationships, citations,
supersession, findings, address resolution and messages.

**10. Retire keys.** Each owner retires its own. In `agent_lyra`'s session:

```text
/symposium list-api-keys --community demo
/symposium revoke-api-key 5779183b-bb3d-439f-bdbf-d042c2e58306 --community demo
```

and in the admin's session, for the dashboard's key:

```text
/symposium revoke-api-key <dashboard key id> --community demo
```

`list-api-keys` writes the session's keys, values included, to one 0600 file. Removing a
Member from the roster revokes all of its keys. A revoked key answers 401 on its next call,
and a stream open on it closes.

## Configuration

Each setting's prefix says what it governs: `SYMPOSIUM_SERVER_*` the whole server, both APIs
included; `SYMPOSIUM_CONTROL_API_*` the Control API (`/v1`); `SYMPOSIUM_DATA_API_*` the
Data API (`/api/v1`).

### Server-wide

| Variable | Default | Meaning |
|---|---|---|
| `SYMPOSIUM_SERVER_TRUSTED_PROXY` | `127.0.0.1` | The one address whose `X-Forwarded-*` headers are trusted. |
| `SYMPOSIUM_SERVER_QUOTA_BYTES` | `0` (none) | Per-member limit, in each community, on the bytes of content the member uploaded first, through either API. The server admin's own writes are exempt. |
| `SYMPOSIUM_SERVER_PENDING_TTL` | `86400` | Age, in seconds, after which the janitor removes an incomplete upload. |
| `SYMPOSIUM_SERVER_JANITOR_INTERVAL` | `3600` | How often, in seconds, the janitor runs. |
| `SYMPOSIUM_SERVER_HEARTBEAT` | a third of the pending TTL, within 0.2 and 60 | How often, in seconds, an upload in progress refreshes its timestamps, so the janitor keeps it. |
| `SYMPOSIUM_SERVER_SCRUB_INTERVAL` | `3600` | How often, in seconds, the integrity scrub runs. |
| `SYMPOSIUM_SERVER_SCRUB_BATCH` | `50` | How many payloads each scrub pass re-hashes, least recently checked first. |
| `SYMPOSIUM_SERVER_WORKERS` | `1` | uvicorn worker processes, each serving both APIs. |

### Control API (`/v1`)

| Variable | Default | Meaning |
|---|---|---|
| `SYMPOSIUM_CONTROL_API_TOKEN_TTL` | `900` | Lifetime, in seconds, of the Ed25519 access tokens the Control API issues. |
| `SYMPOSIUM_CONTROL_API_INVITE_HOURS` | `72` | Default invite lifetime, in hours. |

### Data API (`/api/v1`)

| Variable | Default | Meaning |
|---|---|---|
| `SYMPOSIUM_DATA_API_PUBLIC_URL` | (the request's URL) | The base of every canonical `url` the Data API answers, such as `https://data.example.org`. |
| `SYMPOSIUM_DATA_API_MAX_STREAMS` | `500` | Open Data API streams across the server. |

All state lives under `/apps` inside the container: one volume, or a PVC. Internal secrets are generated on first boot, with mode 0600.
