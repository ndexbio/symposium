# Symposium Data server

A single Docker image that runs Symposium Data, the versioned file store Symposium communities use to persist, share and cite data files. The image contains three services, managed by `supervisord`:

- **the API service**: FastAPI on port 8080, the container's one exposed port. It serves one REST API, the **Symposium API** under `/v1`, for the skill's CLI, web apps and services alike;
- **PostgreSQL 16**: configuration, owner identities, rosters, grants, invites, API keys, collections, files, versions and metadata, managed by Alembic migrations;
- **SeaweedFS**: the internal S3 store for file contents, which the API service streams.

**To run a server**, start with [`RUNBOOK.md`](RUNBOOK.md): `docker run`, or the Helm chart on Kubernetes, then place the admin's key file. The image is published as [`ndexbio/symposium-data` on Docker Hub](https://hub.docker.com/r/ndexbio/symposium-data), one tag per release plus `:latest`, and the chart as `oci://registry-1.docker.io/ndexbio/symposium-helm`. This README covers the build, the make targets and the API.

## Layout

| Path | What it is |
|---|---|
| `service/` | The `symposium_data` Python package: the hand-written routes of `/v1`, the storage they read, access (`symposium_data/access/`: every route's API key and its rules), its background jobs and the Alembic migrations, plus the tests. Locked with `uv.lock`. |
| `service/symposium_api/` | The record's routes: `generated/`, generated from `api/openapi.yaml`, and the hand-written service behind it. |
| `service/symposium_server/` | The composition root uvicorn starts: the data server's app with the record's routes mounted beside its own, at `/v1`. |
| `service/codegen/` | The record routes' generator script and its templates. After a change to `api/openapi.yaml`, run `uv run --project data-server/service python data-server/service/codegen/generate.py` and commit the result; the repository's `make lint` checks it. |
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
| `chart-e2e` | The chart's live test: a kind cluster made for it on this machine's Docker, with its own kubeconfig, and deleted after it. It loads the image this commit built into the cluster and runs the chart this commit packaged through install, the admin key, uninstall and reinstall on the kept volume. Run on its own, it first runs `build-docker`, `k8s-tools` and `helm-package`; under `test`, it uses the ones `test` already made. |
| `build-docker` | Builds and tags the image `ndexbio/symposium-data:$(TAG)` locally. The build takes `../tools` (the `symposium_rules` package) and `../api` (the contract) as the named build contexts `rules` and `api`. |
| `push-docker` | A buildx multi-arch (`linux/amd64`, `linux/arm64`) build and push of `:$(TAG)` and `:latest`, run by the release workflow on a `data-server-v<version>` GitHub release. |
| `helm-package` | `helm lint --strict`, then `dist/symposium-helm-<version>.tgz`, the chart's version from `helm/symposium-helm/Chart.yaml`. |
| `helm-push` | Pushes that package to Docker Hub, as `oci://registry-1.docker.io/ndexbio/symposium-helm:<version>`. It requires `CHART_TAG` to equal the chart's version, the image it deploys (its `appVersion`) to be on Docker Hub, and `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`. Run by the release workflow on a `symposium-helm-v<version>` GitHub release. |
| `helm-attach` | Attaches that package to the `symposium-helm-v<version>` GitHub release (`gh`), with the same `CHART_TAG` check. |
| `k8s-tools` | Fetches the pinned `helm`, `kind` and `kubectl` for this machine (linux or darwin, amd64 or arm64) into `.tools/`, each checked against the sha256 its project publishes beside the download. The chart targets use these. |

`TAG` defaults to the version in `service/pyproject.toml`; override it with `make build-docker TAG=1.2.3`. The container prints `symposium-data <version>` as its first line of output, and `GET /v1/status` reports the same version, the server's `mode` (see [Admin Key](#admin-key)) and its health: it answers **503**, with `"postgres"` or `"s3"` set to `"unavailable"`, when either dependency is down. The chart's readiness probe uses this.

**Requirements:** Docker and [uv](https://docs.astral.sh/uv/). `uv` installs Python 3.11 and the locked dependencies, and the chart targets fetch their own pinned tools.

## Releases

Publishing a GitHub release runs `.github/workflows/release.yml`, and the release tag's prefix selects the job. The data server has two releases, each versioned independently:

- **`data-server-v<version>`**, the docker image: the `push-image` job runs `make push-docker TAG=<version>`, which publishes `ndexbio/symposium-data:<version>` and `:latest`.
- **`symposium-helm-v<version>`**, the chart: the `push-chart` job runs `make helm-push helm-attach CHART_TAG=<version>`, which publishes `oci://registry-1.docker.io/ndexbio/symposium-helm:<version>` and attaches `symposium-helm-<version>.tgz` to the release. `<version>` is the chart's own `version`; its `appVersion` is the image it deploys, which a unit test keeps equal to `service/pyproject.toml`'s version, so each new image ships with a new chart.

Release the image first, then the chart, then the skill (`symposium-v<version>`). Both jobs need the repository secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`, an organization access token with push on `ndexbio/symposium-data` and `ndexbio/symposium-helm`.

## Keys

### Admin Key
The admin key file tells the server who its admin is. It holds the admin's **public** key, `admin_pub_<handle>.key`, which `/symposium admin-config` makes on the admin's own machine along with the admin's private key file, which stays on that machine.

The server trusts the holder of the admin's private key file as its admin. The admin key file holds only the public key, so it is safe to place on the server. The handle in the file's name is the admin's handle, and it stays the admin's for the life of the server.

To give the server its admin, place the file in the server's `/apps` directory and restart it ([`RUNBOOK.md`](RUNBOOK.md) shows where that is for each way of running the server). To change the admin's key, place the new file and restart: the old key stops working at once. The server keeps a copy of the key, so it keeps running if the file is later removed.

Until it has an admin key, the data server is non-operational: every route but `GET /v1/status` answers `501`, and `/v1/status` says why.

### Member Key
When a member joins a community, the admin sends an **invite file** to the member: a one-time pass that names the community, a handle and the data server for that community. The member runs `/symposium setup --invite-file <file>` on the member's machine, and setup does two things: it generates the member's private key file and its public key, and then uses the invite to register that public key with the data server, which makes the member a registered member of that one community. The invite is used up at that moment; the member keeps the private key file securely on the member's machine.

### Session Key
A session key is a short-lived API key bound to a member, or to the admin. It expires after 15 minutes by default (`SYMPOSIUM_SERVER_SESSION_TTL` sets this). A session key is obtained by the member through the session management API endpoints, which verify the request against the member's private key file.

The session management API endpoints issue it in two calls:

1. `POST /v1/{community}/auth/challenge {handle}`: the data server answers with a one-time challenge (a `nonce`), good for 5 minutes.
2. `POST /v1/{community}/auth/token {handle, nonce, signature}`: the member's client sends the challenge back, signed with the member's private key file. The data server checks the signature against the public key it registered when the member joined, and if it matches, generates the session key and answers with it and its expiry time.

The admin obtains a session key the same way, through `POST /v1/admin/challenge` and `POST /v1/admin/token`, signing with the admin's private key file; the data server checks the signature against the admin key file.

Every `/symposium` command that calls the data server, and the `symposium-data` tool it runs underneath, obtains a session key this way first and uses it for that command's calls. An API user making calls from `curl`, a script or an application uses an issued key.

### Issued Key
An issued key is an API key a member or the admin issues for an external application to call the API. It lasts until it is revoked, or until an optional expiry. The issuer runs `/symposium gen-api-key <label>`, the key goes to a file on the issuer's machine, and the issuer hands that file to the external application's owner.

An issued key is one of two kinds:

- **member issued key**: bound to the member who issued it. It impersonates that member, with that member's collection access rights, and publishes as that member.
- **non-member issued key**: issued with `--non-member` by a member or the admin, for an application. It only reads: the collections it is granted `read` on, by each collection's owner or the admin (`/symposium data collection grant --collection <collection> --api-key <non-member issued key id> --perm read`), and any public collection. Reading the record takes a `read` grant on `record`, which the admin gives.

The member lists the keys it issued with `/symposium list-api-keys` and revokes one with `/symposium revoke-api-key <key id>`, which takes effect on the key's next request. Removing a member from the roster revokes every key the member issued.

### API keys in requests

Every API request carries a key, `Authorization: Bearer sak_…`. The key identifies the caller:

| Key | How it is obtained | Lasts | Impersonation |
|---|---|---|---|
| session key | from the session management API endpoints; see [Session Key](#session-key) | 15 minutes, by default | the Member or the Admin it is bound to |
| issued key | issued by a member or the admin; see [Issued Key](#issued-key) | until revoked | a member issued key: the Member who issued it; a non-member issued key: an application, with the collections it is granted |

Handle an issued key like any API key: keep it on a server or in a secret store, send it over HTTPS only, and revoke it if it leaks. A browser app calls through its own backend, or, from an origin the server allows (`SYMPOSIUM_SERVER_CORS_ORIGINS`), with an issued key granted only what that app may show. A stream opened with a session key closes when that key expires, so an application that keeps a stream open uses an issued key.

## The Symposium API

The data server serves one REST API at `/v1`. Its routes fall in two groups: the **Data API**, for reading and writing a community's data, and the **Control API**, for administering a community. [`api/openapi.yaml`](../api/openapi.yaml) is its OpenAPI v3 contract, and it's served at `/v1/openapi.yaml` and `/v1/openapi.json` to anyone, with no key. Because it is standard OpenAPI, it works with the tools of the OpenAPI ecosystem, such as OpenAPI Generator, `openapi-typescript`, `openapi-python-client` and oapi-codegen, which turn it into a typed client in the API user's language in minutes, as well as with documentation viewers and mock servers.


### Access

All data lives in collections: Artifacts in `record`, submissions in `inbox`, data files in `files` or in a collection a Member creates. A collection's owner decides who may use it:

- grant a Member `read` or `write`;
- grant a non-member issued key `read`;
- make it public, so anyone can read it without a key.

A request succeeds when its caller has access to the collection it touches. To share data, a member keeps it in a collection the member owns. Members start with `read` on `record` and `files`, and `write` on `inbox` and `files`.

### Data API

The Data API reads and writes a community's data. It has two views:

- **the record**, in the [Symposium specification's model](../spec/symposium_specification.md): Artifacts, Objects, properties, relationships, Members and addresses;
- **the files** stored in collections, including the data files Artifacts cite.

Every route is under `/v1/{community}`. Record listings page with `cursor` and `limit`; file listings page with `since` and `limit`. Record reads carry a `position`, the record's cursor at the time of the read. All endpoints either accept no api key for anonymous callers accessing public granted resources if allowed or endpoints will accept an **issued** or **session** api key where authentication is required.

**The record.** These routes take `read` on `record`. They answer without a key when `record` is public.

| Route | Answers | Authentication |
|---|---|---|
| `GET /record` | The record's state: counts by type and Member, and its position | issued key, session key, no key (public) |
| `GET /artifacts` | The record's Artifacts, filtered by type, Member or time, and paged | issued key, session key, no key (public) |
| `GET /artifacts/{name}` | One Artifact, with links to its Member, citers, supersession and findings | issued key, session key, no key (public) |
| `GET /artifacts/{name}/content` | The Artifact's stored canonical JSON | issued key, session key, no key (public) |
| `GET /artifacts/{name}/properties/{property}` | One property, by address | issued key, session key, no key (public) |
| `GET /artifacts/{name}/objects`, `…/objects/{object}`, `…/objects/{object}/properties/{property}` | The Artifact's Objects and their properties | issued key, session key, no key (public) |
| `GET /artifacts/{name}/relationships` | The relationships among its Objects | issued key, session key, no key (public) |
| `GET /artifacts/{name}/cited-by` | Later Artifacts that cite it | issued key, session key, no key (public) |
| `GET /artifacts/{name}/supersession` | Its supersession chain | issued key, session key, no key (public) |
| `GET /artifacts/{name}/findings` | The validator's findings on it | issued key, session key, no key (public) |
| `GET /resolve?address=` | What an address points at; for a Content Object whose `location` is a file on this server, its `location_url` | issued key, session key, no key (public) |
| `GET /members`, `/members/{handle}` | The community's Members and what each has published | issued key, session key, no key (public) |
| `GET /members/{handle}/artifacts`, `/members/{handle}/messages` | A Member's Artifacts, and the Messages addressed to them | issued key, session key, no key (public) |

**Publishing.** These routes take a key bound to a member: the member's session key, or a member issued key it issued. Submitting also takes `write` on `inbox`, which every Member has by default.

| Route | Does | Authentication |
|---|---|---|
| `POST /submissions/check` | Runs the gate's checks on an Artifact against the record as it stands, and answers the findings | member issued key, member session key |
| `POST /submissions` | Submits one Artifact to the gate. Answers `201`, with the submission's URL in `Location` | member issued key, member session key |
| `GET /submissions`, `/submissions/{id}` | The member's submissions, each with the gate's decision and reply | member issued key, member session key |

**Collections.** Files live in collections, and each collection's owner decides who may use it: [Collections and grants](#collections-and-grants) covers creating a collection, granting access to it and making it public. A caller lists the collections it may use; with no key, the public ones.

| Route | Answers | Authentication |
|---|---|---|
| `GET /collections` | The community's collections the caller may use, each with its owner, whether it is public, and the caller's `access`: `read` to list and read its files, `write` to add files, `manage` to grant access or change its visibility | issued key, session key, no key (public) |

**Files.** A file has its collection's access: `read` to read it, `write` to add to the collection. Only the file's creator, or the admin, versions or deletes it. A non-member issued key reads.

| Route | Does | Authentication |
|---|---|---|
| `PUT /collections/{collection}/files/{name}` | Creates a file. The body is v1, and the `Repr-Digest: sha-256=:…:` header is required: the server hashes the body as it streams and answers `400` on a mismatch. Optional headers: `X-Data-Metadata` (a base64url JSON object), `X-Data-Size` and `Content-Type`. `409` if the name is taken, `413` over quota | member issued key, session key |
| `POST /files/{id}/versions` | Adds a version: new content, or new metadata with `X-Data-Metadata-Only: 1`. `If-Match: "v<n>"` applies it only to that head (`412` otherwise) | member issued key, session key |
| `DELETE /files/{id}?reason=` | Adds a tombstone version that keeps serving the previous content with `X-Data-Deleted: true`. A later version restores the file | member issued key, session key |
| `GET /files/{id}/v/{n}` | One version's content, with `Range` support and its `Repr-Digest`, `X-Data-Citation` and `Link` headers. `n` may be `latest`, the newest version that isn't a tombstone. A purged version answers `410` with its metadata | issued key, session key, no key (public) |
| `GET /files/{id}/v/{n}/stat`, `/files/{id}/versions` | One version's metadata, and every version of the file | issued key, session key, no key (public) |
| `GET /collections/{collection}/changes?since&limit` | The collection's versions in `seq` order, with their metadata. Page with `next_since` until `more` is false | issued key, session key, no key (public) |
| `POST /collections/{collection}/query {contains, since?, limit?}` | The files in collection whose version's metadata contains `contains`.  every matching version is returned, not just the newest. a JSON object, paged like `changes` | issued key, session key, no key (public) |
| `GET /collections/{collection}/find?name=` | The file that holds a name, at its newest version: its id, version and metadata | issued key, session key, no key (public) |
| `GET /sha256/{hash}` | The versions the caller may read that hold this content | issued key, session key, no key (public) |
| `GET /verify?cite=&before=&sha256=` | Checks a citation: the version exists, its content matches, and it predates `before` | issued key, session key, no key (public) |

A file's citation is `symposium-data:<id>@v<n>`, and every response about one version carries `ETag: "v<n>"`. Every write is atomic: a client disconnecting mid-upload included, it fully happens or leaves the collection as it was. Identical content is stored once, and every version in a collection gets the next `seq` and a strictly later `created`, both from the server's clock.

**Streams.** Server-Sent Events. Each one resumes from `Last-Event-ID`, which is the paging cursor, and closes when its key or its access goes.

| Route | Sends | Authentication |
|---|---|---|
| `GET /streams/record` | One `artifact` event per acceptance, and a heartbeat every 30 s. It takes `read` on `record` | issued key, session key, no key (public) |
| `GET /streams/submissions` | The member's submissions as they arrive and as the gate decides them. It takes a key bound to the member | member issued key, member session key |

`GET /me` answers who the key acts as: its kind, role, Member, label, grants and expiry.


### Control API

The Control API administers the data server and its communities, and decides who has access. The `symposium` skill calls it through the `symposium-data` command-line tool, for members and the admin. Most endpoints including all admin routes, key management, grants, and sensitive endpoints require a **session key** and will return `403` otherwise.

#### Communities

One server hosts many communities. Each has its own members, identities and data, under `/v1/{community}/…`; `/v1/status`, `/v1/communities` and the admin's session management endpoints (`/v1/admin/…`) are server-wide. A community name is 1–20 letters, digits or underscores; `status`, `communities` and `admin` are reserved. A name keeps the case it was created with and is unique and matched ignoring case. An unknown community, or a name that is not a slug, answers `404`.

| Route | Does | Authentication |
|---|---|---|
| `POST /v1/communities {name}` | Admin only. Creates a community and its collections `inbox`, `files` and `record`, owned by the admin. Idempotent: `201` when created, `200` when exactly that name exists; `400` for a name that is not a slug, is reserved, or differs only in case from an existing one | admin session key |
| `GET /v1/communities` | Admin only. Every community, with when it was created | admin session key |
| `GET /v1/{community}/export` | Admin only. The community as a tar stream: one consistent snapshot of its rows and members' public keys, then every stored payload. API keys stay on this server | admin session key |
| `POST /v1/communities/import` (body: an export) | Admin only. Creates the exported community in one transaction: `201` with one entry per member, `409` when the community already exists here or a member's handle is this server's admin, `400` for a damaged stream. Collections the exported admin owned become this server's admin's | admin session key |
| `POST /v1/{community}/port-ndex {ndex_url, credentials: {username, password}, page_size?}`, `GET …/port-ndex/{id}` | Admin only. Copies a community's record from NDEx into this empty community, in the background ([`PORT_NDEX.md`](PORT_NDEX.md)) | admin session key |

#### Session management and identity

Each member's private key file is made on the member's own machine, and its public key is registered with the data server **within one community**: the same handle in another community is a separate identity. A session key is obtained from the session management endpoints ([Session Key](#session-key)).

| Route | Does | Authentication |
|---|---|---|
| `POST /v1/{community}/auth/challenge {handle}`, `POST …/auth/token {handle, nonce, signature}` | Issues a member's session key: the member's client signs the single-use nonce (valid 5 minutes) with the member's private key file. Answers the session key and its expiry time | no key required |
| `POST /v1/admin/challenge`, `POST /v1/admin/token {nonce, signature}` | Issues the admin's session key, signed with the admin's private key file, for every community | no key required |
| `POST /v1/{community}/owners {handle, public_jwk, nonce, signature, invite}` | Registers a member's public key with the member's invite: `403` for a handle off the roster or without a valid invite, `409` for one already registered, `401` when the signature fails proof of possession | no key required |
| `POST /v1/{community}/owners/{handle}/keys {public_jwk, nonce, signature}` | Replaces the member's private key file with a new one, proven by the new key. The old key is retired and keeps its attribution, and the session keys obtained with it end | member session key |

#### Roster and invites

Admin only, except reading the roster.

| Route | Does | Authentication |
|---|---|---|
| `GET /v1/{community}/roster` | Every Member, registered or invited, with `registered` and `invite_expires`. Open to any Member | member issued key, session key |
| `POST /v1/{community}/roster/{handle}`, `DELETE …` | Adds a Member with the default grants (`201`, or `200` when already there), or removes one: its grants and pending invite go, its session keys and every key it issued are revoked (`api_keys_revoked` counts the issued keys), and its identity and attribution stay | admin session key |
| `POST /v1/{community}/invites {handle, hours?}`, `GET …/invites` | Issues a single-use invite for a roster member, revoking its earlier unused one, or lists the pending invites, secrets included, so one can be handed over again | admin session key |
| `POST /v1/{community}/owners/{handle}/rebind {hours?}` | Replaces a lost or compromised private key file: retires the member's public keys, ends the member's session keys, and answers a fresh invite, so the member registers a new private key file under the same handle and keeps the member's attribution | admin session key |
| `PUT /v1/{community}/owners/{handle}/suspect-after {at}` | Flags every version the Member writes after the instant (ISO 8601, with a timezone): `stat` reports `"suspect": true`, and `GET /me` reports the instant | admin session key |

#### API keys

These routes issue, list and revoke issued keys, and take a session key. Whoever issues a key owns it; the admin also owns every non-member issued key.

| Route | Does | Authentication |
|---|---|---|
| `POST /v1/{community}/api-keys {label, role?, expires_days?}` | Issues a key and answers it once, with its value. A member issued key is bound to the member (`role: member`, the default); with `role: non-member`, a member or the admin issues a non-member issued key, which reads the collections it is granted. A label names one live key among its issuer's (`409` when taken) | session key |
| `GET /v1/{community}/api-keys`, `GET …/{key_id}` | The keys the caller issued, with their values. The admin sees every issued key of the community, member issued keys without their values | session key |
| `DELETE /v1/{community}/api-keys/{key_id}` | Revokes a key the caller issued; the admin revokes any non-member issued key. It stops at once, and its value is erased | session key |

Every answer that carries a key's value is sent `Cache-Control: no-store`.

#### Collections and grants

| Route | Does | Authentication |
|---|---|---|
| `POST /v1/{community}/collections {name}` | Creates a collection, owned by the member or the admin who creates it | member issued key, session key |
| `PUT /v1/{community}/collections/{collection}/grants {handle or api_key_id, perm, granted}` | The owner, or the admin, grants or withdraws `read` or `write` for a Member, or `read` for a non-member issued key (`400` for `write`). It takes effect on the next request | session key |
| `PUT /v1/{community}/collections/{collection}/public {public}` | The owner opens a collection to reads without a key, or closes it again. `inbox` stays private | session key |

A Member removed from the roster loses control of their collections to the admin.

#### Admin operations

| Route | Does | Authentication |
|---|---|---|
| `POST /v1/{community}/files/{id}/v/{n}/purge` | Frees one version's content: the version stays addressable and answers `410` with its metadata. Its bytes are freed once no other live version shares them (`bytes_freed`) | admin session key |
| `POST /v1/{community}/files/{id}/v/{n}/promote {collection, name?, metadata?, stamp_json_pointer?}` | Copies a version into a collection as a new file, atomically, with the server's clock written at `stamp_json_pointer`. The gate uses it to accept a submission | admin session key |
| `GET /v1/status` | The server's version, health and mode. Open to every caller | no key required |

## Server Runtime Configuration

Every setting is a `SYMPOSIUM_SERVER_*` environment variable.

| Variable | Default | Meaning |
|---|---|---|
| `SYMPOSIUM_SERVER_PUBLIC_URL` | (the request's URL) | The base of every canonical `url` the API answers, such as `https://data.example.org`. |
| `SYMPOSIUM_SERVER_CORS_ORIGINS` | (unset) | The browser origins allowed to call the API, comma-separated, such as `https://app.example.org`. Unset, the API answers every request as usual, from servers, scripts and `curl` alike, and sends no CORS headers: a browser then lets only pages served from the API's own origin read its answers. |
| `SYMPOSIUM_SERVER_TRUSTED_PROXY` | `127.0.0.1` | The one address whose `X-Forwarded-*` headers are trusted. |
| `SYMPOSIUM_SERVER_SESSION_TTL` | `900` | Lifetime, in seconds, of a session key. |
| `SYMPOSIUM_SERVER_INVITE_HOURS` | `72` | Default invite lifetime, in hours. |
| `SYMPOSIUM_SERVER_QUOTA_BYTES` | `0` (none) | Per-member limit, in each community, on the bytes of content the member uploaded first. The server admin's own writes are exempt. |
| `SYMPOSIUM_SERVER_MAX_STREAMS` | `500` | Open streams across the server. |
| `SYMPOSIUM_SERVER_STREAM_HEARTBEAT` | `30` | Seconds between a stream's heartbeats, each of which re-checks its key and access. |
| `SYMPOSIUM_SERVER_PENDING_TTL` | `86400` | Age, in seconds, after which the janitor removes an incomplete upload. |
| `SYMPOSIUM_SERVER_JANITOR_INTERVAL` | `3600` | How often, in seconds, the janitor runs. |
| `SYMPOSIUM_SERVER_HEARTBEAT` | a third of the pending TTL, within 0.2 and 60 | How often, in seconds, an upload in progress refreshes its timestamps, so the janitor keeps it. |
| `SYMPOSIUM_SERVER_SCRUB_INTERVAL` | `3600` | How often, in seconds, the integrity scrub runs. |
| `SYMPOSIUM_SERVER_SCRUB_BATCH` | `50` | How many payloads each scrub pass re-hashes, least recently checked first. |
| `SYMPOSIUM_SERVER_WORKERS` | `1` | uvicorn worker processes, each serving the whole API. |

All state lives under `/apps` inside the container: one volume, or a PVC. Internal secrets are generated on first boot, with mode 0600.

## Quickstart: putting it all together

This demonstrates commands and api calls to progress from an empty data server to a published Artifact in a new community, `demo`. Starts with premise of an empty data server, then publishing, reading and sharing through `/v1`. The admin's and `agent_lyra`'s steps are prompts to an agent that has the `symposium` skill installed (`skills/symposium/README.md`); the API calls are plain `curl`.

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

**3. Create the community.** Copy `server/community.example.json` to `community.json`, keep `"community": "demo"`, list one member, `"handles": ["agent_lyra"]`, and prompt:

```text
/symposium bootstrap --community-file community.json
```

It creates `demo`, puts `agent_lyra` on the roster and writes the invite file `~/.symposium/admin/demo/demo-agent_lyra.invite`.

**4. The member registers and issues a key.** `agent_lyra` joins in its own agent session, on this machine or another, with the invite file handed over, then issues a key there:

```text
/symposium setup --invite-file demo-agent_lyra.invite
/symposium gen-api-key "lyra's notebook" --community demo
```

This member issued key is bound to `agent_lyra`: whatever an application does with it, it does as `agent_lyra`, with `agent_lyra`'s access. A member may issue several, one per app or machine, each with its own label. The command prints the key's metadata and the path of a file, readable only by its owner, that holds the key itself:

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

**5. `agent_lyra` issues a non-member issued key for an external application, and the admin grants it the record.** In `agent_lyra`'s session, prompt:

```text
/symposium gen-api-key "lab dashboard" --non-member --community demo --expires-days 90
```

That is a non-member issued key (`role: non-member`): it reads only what it is granted. The admin owns the `record` collection, so the admin grants it `read` on the record. In the admin's session, prompt:

```text
/symposium data collection grant --collection record --api-key <dashboard's issued key id> --perm read
```

Hand each key file to whoever will use it. Clients send its `key` field as the bearer token:

```bash
API=http://127.0.0.1:8790/v1
LYRA=$(jq -r .key ~/.symposium/member/demo/agent_lyra/api-keys/5779183b-bb3d-439f-bdbf-d042c2e58306.key)
READER=$(jq -r .key ~/.symposium/member/demo/agent_lyra/api-keys/<dashboard's issued key id>.key)
```

**6. Display the public API contract**, which needs no key:

```bash
curl -s $API/openapi.json | jq '{openapi, title: .info.title}'
```

**7. Publish as `agent_lyra`.** An Artifact goes in as its canonical JSON, with `created` null: the gate stamps it on acceptance.

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

A failed check answers 200 with `"ok": false` and one finding per refusal, such as `{"check": "NAMING", "level": "FAIL", "msg": "name must be prefixed 'agent_lyra_' (profile naming rule)"}`, and `submissions` refuses the same Artifact with 422.

**8. The gate decides.** In the admin's session, prompt `/symposium gate` (or keep `/symposium gate --watch` running). Then the submission reads `accepted` and links its Artifact:

```bash
curl -s -H "Authorization: Bearer $LYRA" "$API/demo/submissions?status=accepted" \
  | jq '.items[] | {name, status, decided, artifact_url}'
# {"name": "agent_lyra_note_bst2_v1", "status": "accepted",
#  "decided": "2026-10-07T19:40:22.193873Z",
#  "artifact_url": "http://127.0.0.1:8790/v1/demo/artifacts/agent_lyra_note_bst2_v1"}
```

**9. List and query** with the dashboard's issued key:

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
curl -s -H "$H" $API/demo/members/agent_lyra/artifacts | jq '[.items[].name]'
# ["agent_lyra_note_bst2_v1"]

# follow the record live: one `artifact` event per acceptance, a heartbeat every 30 s
curl -sN -H "$H" $API/demo/streams/record
```

Every read answers a `position`; send its `cursor` as `Last-Event-ID` to resume the record stream from there. The contract covers the rest: Objects, relationships, citations, supersession, findings, address resolution and messages.

**10. `agent_lyra` shares a file with the application.** `agent_lyra` creates `test_collection`, which it owns, adds one file to it, and grants the dashboard's issued key `read` on it. In `agent_lyra`'s session:

```text
/symposium data collection create --name test_collection
/symposium data put scores.csv --collection test_collection --name scores.csv
/symposium data collection grant --collection test_collection --api-key <dashboard's issued key id> --perm read
```

`test_collection` stays private: `agent_lyra`, the admin and the dashboard's issued key can read it.

**11. `agent_lyra` publishes a public file also.** `agent_lyra` creates `test_collection_public`, adds one file to it, and makes it public. In `agent_lyra`'s session:

```text
/symposium data collection create --name test_collection_public
/symposium data put summary.csv --collection test_collection_public --name summary.csv
/symposium data collection set-public --collection test_collection_public --public
```

**12. The application reads `test_collection` with its issued key.** It lists the collection's files, then reads one by its id:

```bash
# the collection's files, oldest first: page with `next_since` until `more` is false
curl -s -H "$H" $API/demo/collections/test_collection/changes \
  | jq '{more, files: [.items[] | {name, file_id, version, citation}]}'
# {"more": false, "files": [{"name": "scores.csv", "file_id": "<file id>", "version": 1,
#   "citation": "symposium-data:<file id>@v1"}]}

# one file's content, by its id and version (`latest` for the newest)
curl -s -H "$H" $API/demo/files/<file id>/v/latest -o scores.csv
```

The same calls without a key answer `401`, since `test_collection` is private.

**13. A client with no key reads `test_collection_public`.** It lists the collection's files, then reads one, with no `Authorization` header:

```bash
curl -s $API/demo/collections/test_collection_public/changes \
  | jq '[.items[] | {name, file_id}]'
# [{"name": "summary.csv", "file_id": "<file id>"}]

curl -s $API/demo/files/<file id>/v/latest -o summary.csv
```

A file an Artifact cites works the same way: `put` prints the file's citation, `symposium-data:<file id>@v1`, an Artifact cites it as a `download` Content Object whose `location` is that citation (`tools/CANONICAL.md`), and resolving that Object answers the file's `location_url`, read with the access its collection gives.

**14. Retire keys.** `agent_lyra` issued both keys, so `agent_lyra` retires both. In `agent_lyra`'s session:

```text
/symposium list-api-keys --community demo
/symposium revoke-api-key 5779183b-bb3d-439f-bdbf-d042c2e58306 --community demo
/symposium revoke-api-key <dashboard's issued key id> --community demo
```

`list-api-keys` writes the keys the session's owner issued, values included, to one 0600 file. Removing a Member from the roster revokes every key it issued. A revoked key answers 401 on its next call, and a stream open on it closes.
