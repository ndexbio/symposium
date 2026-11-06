# Symposium Data server

A single Docker image that runs Symposium Data, the versioned file store Symposium communities use to persist, share and cite data files. The image contains three services, managed by `supervisord`:

- **the API service**: FastAPI on port 8080, the container's one exposed port. It serves one REST API, the **Symposium API** under `/v1`, for the skill's CLI, web apps and services alike;
- **PostgreSQL 16**: configuration, users, role assignments, invites, API keys, collections, files, versions and metadata, managed by Alembic migrations;
- **SeaweedFS**: the internal S3 store for file contents, which the API service streams.

**To run a server**, start with [`RUNBOOK.md`](RUNBOOK.md): `docker run`, or the Helm chart on Kubernetes, then place the root key file. The image is published as [`ndexbio/symposium-data` on Docker Hub](https://hub.docker.com/r/ndexbio/symposium-data), one tag per release plus `:latest`, and the chart as `oci://registry-1.docker.io/ndexbio/symposium-helm`. This README covers the build, the make targets and the API.

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
| `helm/symposium-helm/` | The Helm chart: the server on Kubernetes, on a single ReadWriteOnce PVC, exposed through a Gateway API HTTPRoute or an Ingress, with the root key from its values. Its `README.md` lists every value. |
| [`RUNBOOK.md`](RUNBOOK.md) | How to choose a deployment and run it (Docker, Docker Desktop's Kubernetes or a remote cluster, with the chart), place the root key, port a community off NDEx (port-ndex), host many communities, export and import, verify and tear down. |
| [`PORT_NDEX.md`](PORT_NDEX.md) | The port-ndex: copying a community's record from NDEx into an empty community here. |

## Make targets

Run them from this folder, or from the repository root with `make -C data-server <target>`. The repository's top-level `make test` runs this `test` alongside the top-level suite.

| Target | What it does |
|---|---|
| `lint` | `ruff check` and `ruff format --check` on `service/`. |
| `test` | `lint`, `build-docker`, `k8s-tools` and `helm-package`, then `service-suites` and `chart-e2e` in parallel, each logging to `dist/test-logs/`, printed once both finish. Every wait is for an event or a state, bounded by `MAX_PER_TEST_WAIT` (seconds, default `120`). |
| `service-suites` | The unit suites, then the integration suites against the image already built, on one `sdtest-*` container for the whole session, including the chart's lint, render and kubeconform checks. |
| `chart-e2e` | The chart's live test: a kind cluster made for it on this machine's Docker, with its own kubeconfig, and deleted after it. It loads the image this commit built into the cluster and runs the chart this commit packaged through install, the root key, uninstall and reinstall on the kept volume. Run on its own, it first runs `build-docker`, `k8s-tools` and `helm-package`; under `test`, it uses the ones `test` already made. |
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

## Upgrading a 0.1.x server to 0.2.0

A 0.1.x server upgrades in place. Run the 0.2.0 image on the same `/apps` volume with the same admin key file, and its first start does the rest:

1. It backs up the database to `/apps/data/backups/schema-<revision>-<time>.sql.gz` and logs the path. The server does this before every schema upgrade.
2. It converts the database:

   | On the 0.1.x server | On 0.2.0 |
   |---|---|
   | the admin bound from the key file | the root user, holding `server-root`, with the same handle and key file |
   | a roster member | a user of that community, holding `community-member` on every collection (`*`), signing in with the key it joined with |
   | a member narrowed to fewer than the default grants | `community-observer` on the collections it could read; the log names each one |
   | an owner taken off the roster | a removed user: listed among the users as removed, its handle retired, its work kept under that handle |
   | a collection's owner | the same owner |
   | files, versions, the record and `inbox` | unchanged |

3. It starts operational. Root runs every community, gate included, until a community admin is assigned with `assign --handle <member> --access community-admin`.

**What each side does:**

- **Operator:** move the deployment to the 0.2.0 image. For a Podman Quadlet unit, set `Image=docker.io/ndexbio/symposium-data:0.2.0` and restart the unit; for Helm, run `helm upgrade` with the chart that deploys 0.2.0 (`RUNBOOK.md` §5.4). `/v1/status` then answers `version: 0.2.0` and `root: <the admin's handle>`.
- **Skill users:** install skill 0.2.0. Keys and sessions carry over, and access is read from the server on the next command. A skill of another version reports the version the server needs.
- **The admin:** start `gate --watch` again with skill 0.2.0. Publishing takes a member account, since administrative roles hold no `publish`.

**Rolling back:** restore the backup inside the running 0.2.0 container, then return the deployment to the 0.1.x image on the same volume. Files and their content stay in place; anything written after the upgrade is left out of the restored database.

```bash
supervisorctl -c /tmp/supervisord.conf stop api-server
gosu postgres dropdb symposium_data
gosu postgres createdb -O symposium_data symposium_data
. /apps/data/config/service.env
gunzip -c /apps/data/backups/<backup>.sql.gz | psql -q "$DATABASE_URL"
```

## Keys

### Root key
The root key file tells the server who its root user is. It holds root's **public** key, `admin_pub_<handle>.key`, which `/symposium admin-config` makes on root's own machine along with root's private key file, which stays on that machine.

The server binds the handle in the file's name as its root user, holding the `server-root` role, for the life of the server. The file holds only the public key, so it is safe to place on the server.

To bind root, place the file in the server's `/apps` directory and restart it ([`RUNBOOK.md`](RUNBOOK.md) shows where that is for each way of running the server). To change root's key, place the new file and restart: the old key stops working at once, and every other user's keys stay as they are. The server keeps a copy of the key, so it keeps running if the file is later removed.

Until it has a root key, the data server is non-operational: every route but `GET /v1/status` answers `501`, and `/v1/status` says why.

### User key
Every other user joins by invite. An **invite file** names the handle, its home community (or none, for a server-level user) and the data server; the roles the user gets are stored on the server with the invite. The user runs `/symposium setup --invite-file <file>` on their own machine, which generates the user's private key file and registers its public key with the data server. The server then creates the user with the invite's roles, and the invite is used up. The private key file stays on the user's machine.

### Session key
A session key is a short-lived API key proving a user signed in. It expires after 15 minutes by default (`SYMPOSIUM_SERVER_SESSION_TTL` sets this). Every user obtains one the same way, in two calls:

1. `POST /v1/challenges {handle, community}`: the data server answers with a one-time challenge (a `nonce`), good for 5 minutes. `community` is the user's home, or null for a server-level user.
2. `POST /v1/sessions {handle, community, nonce, signature}`: the user's client sends the challenge back, signed with the user's private key file. The data server checks the signature against the user's registered public key and answers the session key and its expiry time.

Every `/symposium` command that calls the data server, and the `symposium-data` tool it runs underneath, obtains a session key this way first and uses it for that command's calls. An API user making calls from `curl`, a script or an application uses an issued key.

### Issued key
An issued key is an API key a signed-in user issues for an application or script. It lasts until it is revoked, or until an optional expiry. The issuer runs `/symposium gen-api-key <label> --access <role>:<collections>`; the key goes to a file on the issuer's machine, and the issuer hands that file to the application's owner.

An issued key carries its own access roles, `community-member` or `community-observer`, and is one of two kinds:

- **member issued key**: acts as the user who issued it, within that user's grants. With `community-member` it publishes as that user.
- **non-member issued key**: issued with `--non-member`, for an outside application. It is its own identity and carries `community-observer` alone, so it reads the collections its assignment names. A collection's owner issues one for its own collections; a community admin issues one for any.

An issued key reaches exactly the collections its roles list. The issuer lists its keys with `/symposium list-api-keys` and revokes one with `/symposium revoke-api-key <key id>`, which deletes it: its next request answers `401`. A community admin lists and revokes any key of the community. Removing a user deletes every key it issued.

### API keys in requests

Every API request carries a key, `Authorization: Bearer sak_…`. The key identifies the caller:

| Key | How it is obtained | Lasts | Impersonation |
|---|---|---|---|
| session key | from the session management API endpoints; see [Session key](#session-key) | 15 minutes, by default | the user who signed in, with every grant its roles give |
| issued key | issued by a signed-in user; see [Issued key](#issued-key) | until revoked | a member issued key: the user who issued it, within the key's own roles; a non-member issued key: an application, with the collections its role names |

Handle an issued key like any API key: keep it on a server or in a secret store, send it over HTTPS only, and revoke it if it leaks. A browser app calls through its own backend, or, from an origin the server allows (`SYMPOSIUM_SERVER_CORS_ORIGINS`), with an issued key carrying only what that app may show. A stream opened with a session key closes when that key expires, so an application that keeps a stream open uses an issued key.

## The Symposium API

The data server serves one REST API at `/v1`. Its routes fall in two groups: the **Data API**, for reading and writing a community's data, and the **Control API**, for administering a community. [`api/openapi.yaml`](../api/openapi.yaml) is its OpenAPI v3 contract, and it's served at `/v1/openapi.yaml` and `/v1/openapi.json` to anyone, with no key. Because it is standard OpenAPI, it works with the tools of the OpenAPI ecosystem, such as OpenAPI Generator, `openapi-typescript`, `openapi-python-client` and oapi-codegen, which turn it into a typed client in the API user's language in minutes, as well as with documentation viewers and mock servers.


### Access

Every caller's access comes from its **access roles**. Users and issued keys are assigned roles; a role is a fixed set of **grants**, and a request succeeds when the caller holds the grant it needs in the community it touches:

| Role | Grants |
|---|---|
| `server-root`, `server-admin` | every grant in every community; `server-root` also `delegate` (server-level users) |
| `community-admin` | `read`, `write`, `manage` on every collection; `gate`, `members`, `export` |
| `gate-keeper` | `read` on every collection; `gate` |
| `community-member` | `read`, `write` on its collections; `manage` on the collections it owns; `publish` |
| `community-observer` | `read` on its collections |

`community-member` and `community-observer` take a collection value: `*` (every collection), empty (only the collections the user owns) or a list of names. A signed-in user always keeps access to the collections it owns; an issued key reaches exactly the collections its roles name. A collection's owner, or a community admin, can also make it public, so anyone reads it without a key. [`RUNBOOK.md`](RUNBOOK.md), "Roles and access", covers assigning roles.

All data lives in collections: Artifacts in `record`, submissions and the gate's replies in `inbox`, data files in `files` or in a collection a member creates. `inbox` takes submissions from `publish` holders and replies from `gate` holders, and only the gate writes into `record`.

### Data API

The Data API reads and writes a community's data. It has two views:

- **the record**, in the [Symposium specification's model](../spec/symposium_specification.md): Artifacts, Objects, properties, relationships, Members and addresses;
- **the files** stored in collections, including the data files Artifacts cite.

Every route is under `/v1/communities/{community}`. Record listings page with `cursor` and `limit`; file listings page with `since` and `limit`. Record reads carry a `position`, the record's cursor at the time of the read. All endpoints either accept no api key for anonymous callers accessing public granted resources if allowed or endpoints will accept an **issued** or **session** api key where authentication is required.

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
| `GET /addresses?address=` | What an address points at; for a Content Object whose `location` is a file on this server, its `location_url` | issued key, session key, no key (public) |
| `GET /members`, `/members/{handle}` | The community's Members and what each has published | issued key, session key, no key (public) |
| `GET /members/{handle}/artifacts`, `/members/{handle}/messages` | A Member's Artifacts, and the Messages addressed to them | issued key, session key, no key (public) |

**Publishing.** These routes take `publish`, which `community-member` holds: the member's session key, or a member issued key carrying `community-member`.

| Route | Does | Authentication |
|---|---|---|
| `POST /submission-checks` | Runs the gate's checks on an Artifact against the record as it stands, and answers the findings | issued key, session key |
| `POST /submissions` | Submits one Artifact to the gate. Answers `201`, with the submission's URL in `Location` | issued key, session key |
| `GET /submissions`, `/submissions/{id}` | The member's submissions, each with the gate's decision and reply | issued key, session key |

**Collections.** Files live in collections: [Collections](#collections) covers creating one and making it public. A caller lists the collections it may use; with no key, the public ones.

| Route | Answers | Authentication |
|---|---|---|
| `GET /collections` | The community's collections the caller may use, each with its owner, whether it is public, and the caller's `access`: `read` to list and read its files, `write` to add files, `manage` to share it or change its visibility | issued key, session key, no key (public) |
| `GET /collections/{collection}` | One collection, with the caller's `access` | issued key, session key, no key (public) |

**Files.** A file has its collection's access: `read` to read it, `write` to add to the collection. The file's creator versions or deletes it with `write`, and a `manage` holder does so for any file. A non-member issued key reads.

| Route | Does | Authentication |
|---|---|---|
| `PUT /collections/{collection}/files/{name}` | Creates a file, with `If-None-Match: *` (`412` when the name is taken, `428` without it). The body is v1, and the `Repr-Digest: sha-256=:…:` header is required: the server hashes the body as it streams and answers `400` on a mismatch. Optional headers: `X-Data-Metadata` (a base64url JSON object), `X-Data-Size` and `Content-Type`. `413` over quota. Answers `201` with the file's `Location` | issued key, session key |
| `POST /files/{id}/versions` | Adds a version: new content, or new metadata with `X-Data-Metadata-Only: 1`. `If-Match: "v<n>"` applies it only to that head (`412` otherwise) | issued key, session key |
| `DELETE /files/{id}?reason=` | A soft delete: adds a tombstone version, and the file keeps serving the previous content with `X-Data-Deleted: true`. A later version restores it | issued key, session key |
| `GET /files/{id}` | The file at its newest version: its metadata | issued key, session key, no key (public) |
| `GET /files/{id}/versions/{n}` | One version's content, with `Range` support and its `Repr-Digest`, `X-Data-Citation` and `Link` headers. `n` may be `latest`, the newest version that isn't a tombstone. A purged version answers `410` with its metadata | issued key, session key, no key (public) |
| `GET /files/{id}/versions/{n}/metadata`, `/files/{id}/versions` | One version's metadata, and every version of the file | issued key, session key, no key (public) |
| `GET /collections/{collection}/changes?since&limit` | The collection's versions in `seq` order, with their metadata. Page with `next_since` until `more` is false | issued key, session key, no key (public) |
| `POST /collections/{collection}/files/search {contains, since?, limit?}` | The collection's versions whose metadata contains the JSON object `contains`: every matching version, not just the newest, paged like `changes` | issued key, session key, no key (public) |
| `GET /collections/{collection}/files?name=&cursor=&limit=` | The collection's files, each at its newest version, by name, paged with `next`; with `name`, the file that holds it | issued key, session key, no key (public) |
| `GET /versions?sha256=` | The versions the caller may read that hold this content | issued key, session key, no key (public) |
| `GET /files/{id}/versions/{n}/verification?before=&sha256=` | Checks a citation of this version (`symposium-data:<id>@v<n>`): it exists, its content matches, and it predates `before` | issued key, session key, no key (public) |

A file's citation is `symposium-data:<id>@v<n>`, and every response about one version carries `ETag: "v<n>"`. Every write is atomic: a client disconnecting mid-upload included, it fully happens or leaves the collection as it was. Identical content is stored once, and every version in a collection gets the next `seq` and a strictly later `created`, both from the server's clock.

**Streams.** Server-Sent Events. Each one resumes from `Last-Event-ID`, which is the paging cursor, and closes when its key or its access goes.

| Route | Sends | Authentication |
|---|---|---|
| `GET /record/events` | One `artifact` event per acceptance, and a heartbeat every 30 s. It takes `read` on `record` | issued key, session key, no key (public) |
| `GET /submissions/events` | The member's submissions as they arrive and as the gate decides them. It takes `publish` | issued key, session key |

`GET /v1/me` answers who the key acts as: its kind, user, label, roles, resolved grants and expiry, in the caller's own community.


### Control API

The Control API administers the data server and its communities, and decides who has access. The `symposium` skill calls it through the `symposium-data` command-line tool. The routes that change users, roles, invites or keys take a **session key**, so only a signed-in user makes those changes; an issued key gets `403`. Every route is a noun: sign-in creates a challenge and a session, joining creates a registration, and roles are sub-resources of the user or key that holds them. Every request that creates a resource answers `201` with its `Location`.

#### Communities

One server hosts many communities. Each has its own users and data, under `/v1/communities/{community}/…`; the server's own resources (`/v1/status`, `/v1/challenges`, `/v1/sessions`, `/v1/registrations`, `/v1/me`, `/v1/roles`, `/v1/users`, `/v1/invites`) sit beside `/v1/communities`, so any slug names a community. A community name is 1–20 letters, digits or underscores; it keeps the case it was created with and is unique and matched ignoring case. An unknown community, or a name that is not a slug, answers `404`.

| Route | Does | Grants | Authentication |
|---|---|---|---|
| `POST /v1/communities {name, admin}` | Creates a community and its collections `inbox`, `files` and `record`, and answers an invite making `admin` its first community admin. Idempotent: `201` when created, `200` when exactly that name exists; `400` for a name that is not a slug or differs only in case from an existing one. With `Content-Type: application/x-tar`, the body is an archive (`GET …/archive`) and the community is imported in one transaction: `409` when it already exists here, or one of its handles is a server-level user's or a removed user's here; `400` for a damaged stream | `communities` | session key |
| `GET /v1/communities` | Every community, with when it was created | `communities` | session key |
| `GET /v1/communities/{community}` | The community: its name and when it was created | — | issued key, session key |
| `GET /v1/communities/{community}/archive` | The community's archive, a tar stream: one consistent snapshot of its users, role assignments and rows, then every stored payload. API keys stay on this server | `export` | session key |
| `POST /v1/communities/{community}/ndex-imports {ndex_url, credentials: {username, password}, page_size?}`, `GET …/ndex-imports/{id}` | Imports a community's record from NDEx into this empty community, in the background (port-ndex, [`PORT_NDEX.md`](PORT_NDEX.md)) | `communities` | session key |

#### Session management and identity

A user is a handle in its home community, or a server-level user with no home. A handle is unique within its scope, and a server-level handle is used in no community.

| Route | Does | Grants | Authentication |
|---|---|---|---|
| `POST /v1/challenges {handle, community}`, `POST /v1/sessions {handle, community, nonce, signature}` | Issues a user's session key ([Session key](#session-key)). A removed user answers `401`, naming the removal | — | no key required |
| `POST /v1/registrations {handle, public_jwk, nonce, signature, invite}` | Joins with an invite: creates the user with the invite's stored roles and registers its public key; `201` with the user's `Location`. `403` for an invite that is unknown, used, expired or for another handle; `400` for a request naming roles or a home; `401` when the signature fails proof of possession | — | no key required |
| `POST /v1/me/keys {public_jwk, nonce, signature}` | Replaces the caller's private key file with a new one, proven by the new key. The old key is retired and keeps its attribution, and the session keys obtained with it end | — | session key |
| `GET /v1/communities/{community}/users`, `GET …/users/{handle}` | The community's users, removed ones marked, each with its roles, and the server-level users' handles; one user, its tombstone too once removed | — | issued key, session key |
| `PATCH /v1/communities/{community}/users/{handle} {suspect_after}` | Flags every version the user writes after the instant (ISO 8601, with a timezone): its metadata reports `"suspect": true`, and `GET /v1/me` reports the instant | `members` | session key |
| `DELETE /v1/communities/{community}/users/{handle}` | Removes a user: its roles end, its keys retire, its sessions end and every key it issued is deleted. The user stays as a tombstone: its handle stays bound to it and its work keeps its name. `409` for the community's last `members` holder | `members` | session key |
| `POST /v1/communities/{community}/users/{handle}/invites {hours?}` | Replaces a lost or compromised private key file: retires the user's keys, ends its sessions, and answers a fresh invite that registers a new key under the same handle and roles | `members` | session key |
| `GET /v1/users`, `GET …/users/{handle}`, `PATCH …`, `DELETE …`, `POST …/invites` | The same, for server-level users; removing root answers `409` | `delegate` | session key |

#### Roles and invites

| Route | Does | Grants | Authentication |
|---|---|---|---|
| `GET /v1/roles`, `GET /v1/roles/{role}` | The six access roles and their grants | — | issued key, session key |
| `GET /v1/communities/{community}/users/{handle}/roles`, `GET …/roles/{role}` | A user's roles; one with its `ETag` | — | session key |
| `PUT /v1/communities/{community}/users/{handle}/roles/{role} {collections?}`, `DELETE …` | Assigns a role, or sets its whole collection value (replacing one takes `If-Match` with its `ETag`: `412` when it changed, `428` without it), or ends it. `community-member`, `community-admin` and `gate-keeper` take `members`; `community-observer` takes `manage` on each named collection; `server-admin` takes `delegate`. `409` for the last `members` holder | per role | session key |
| `PUT /v1/communities/{community}/users/{handle}/roles/{role}/collections/{collection}`, `DELETE …` | Adds or withdraws one collection, with the authority over that collection alone: how an owner shares its own collections read-only | per role | session key |
| `GET /v1/users/{handle}/roles`, `GET …/roles/{role}`, `PUT …/roles/{role}`, `DELETE …/roles/{role}` | The same, for a server-level user: `server-admin`, assigned with `delegate` | per role | session key |
| `GET /v1/communities/{community}/api-keys/{key_id}/roles`, `GET …/roles/{role}`, `PUT …/roles/{role}`, `DELETE …/roles/{role}`, `PUT …/roles/{role}/collections/{collection}`, `DELETE …` | The same, for an issued key: only its issuer or a `members` holder, and never beyond the issuer's grants | per role | session key |
| `POST /v1/communities/{community}/invites {handle, roles, hours?}`, `GET …/invites` | Issues a single-use invite carrying `roles`, revoking the handle's earlier unused one (`201`, with its `Location`), or lists the pending invites, secrets included. The caller needs the authority to assign every role in it | `members` | session key |
| `GET /v1/communities/{community}/invites/{invite_id}`, `DELETE …` | One pending invite, with its secret, so it can be handed over again; or revokes it | `members` | session key |
| `POST /v1/invites`, `GET /v1/invites`, `GET …/{invite_id}`, `DELETE …` | The same, for server-level users | `delegate` | session key |

#### API keys

| Route | Does | Grants | Authentication |
|---|---|---|---|
| `POST /v1/communities/{community}/api-keys {label, roles, non_member?, expires_days?}` | Issues a key carrying `roles` and answers it once, with its value and `Location`. A label names one key among its issuer's (`409` when taken) | within the issuer's | session key |
| `GET /v1/communities/{community}/api-keys`, `GET …/{key_id}` | The keys the caller issued, with their roles and values; a `members` holder sees every key of the community | — | session key |
| `DELETE /v1/communities/{community}/api-keys/{key_id}` | Deletes a key the caller issued, or with `members` any key of the community. Its next request answers `401` | — | session key |

Every answer that carries a key's value is sent `Cache-Control: no-store`.

#### Collections

| Route | Does | Grants | Authentication |
|---|---|---|---|
| `POST /v1/communities/{community}/collections {name}` | Creates a collection, owned by the caller's user, who reaches it through the owner allowance; `201` with its `Location` | `write` | issued key, session key |
| `PATCH /v1/communities/{community}/collections/{collection} {public}` | Opens a collection to reads without a key, or closes it again. `inbox` stays private | `manage` | session key |

A collection's owner shares it read-only by adding it to someone's `community-observer` role (`PUT …/roles/community-observer/collections/{collection}`).

#### Curation

| Route | Does | Grants | Authentication |
|---|---|---|---|
| `DELETE /v1/communities/{community}/files/{id}/versions/{n}` | Purges one version's content: the version stays addressable and answers `410` with its metadata. Its bytes are freed once no other live version shares them (`bytes_freed`) | `manage` | session key |
| `POST /v1/communities/{community}/collections/{collection}/files {from, name?, metadata?, stamp_json_pointer?}` | Copies the version `from` cites into the collection as a new file, atomically, with the server's clock written at `stamp_json_pointer`. Into `record` it takes `gate`: the gate's accept | `gate`, or `manage` outside `record` | session key |
| `GET /v1/status` | The server's version, health, mode and root handle. Open to every caller | — | no key required |

## Server Runtime Configuration

Every setting is a `SYMPOSIUM_SERVER_*` environment variable.

| Variable | Default | Meaning |
|---|---|---|
| `SYMPOSIUM_SERVER_PUBLIC_URL` | (the request's URL) | The base of every canonical `url` the API answers, such as `https://data.example.org`. |
| `SYMPOSIUM_SERVER_CORS_ORIGINS` | (unset) | The browser origins allowed to call the API, comma-separated, such as `https://app.example.org`. Unset, the API answers every request as usual, from servers, scripts and `curl` alike, and sends no CORS headers: a browser then lets only pages served from the API's own origin read its answers. |
| `SYMPOSIUM_SERVER_TRUSTED_PROXY` | `127.0.0.1` | The one address whose `X-Forwarded-*` headers are trusted. |
| `SYMPOSIUM_SERVER_SESSION_TTL` | `900` | Lifetime, in seconds, of a session key. |
| `SYMPOSIUM_SERVER_INVITE_HOURS` | `72` | Default invite lifetime, in hours. |
| `SYMPOSIUM_SERVER_QUOTA_BYTES` | `0` (none) | Per-member limit, in each community, on the bytes of content the member uploaded first. Writes by `communities` holders (root and the server admins) are exempt. |
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

This demonstrates commands and api calls to progress from an empty data server to a published Artifact in a new community, `demo`. Starts with premise of an empty data server, then publishing, reading and sharing through `/v1`. Root's, the community admin `agent_steward`'s and `agent_lyra`'s steps are prompts to agents that have the `symposium` skill installed (`skills/symposium/README.md`); the API calls are plain `curl`.

**1. Run a server** from the published image, with a host directory for its data:

```bash
mkdir -p ~/symposium-storage
docker run -d --name symposium-data -p 127.0.0.1:8790:8080 \
  -v ~/symposium-storage:/apps ndexbio/symposium-data:<version>
```

It starts non-operational until root's key file is in place (step 2).

**2. Make root's key and bind it.** In an agent session, prompt:

```text
/symposium admin-config --handle demo_root --data-server-url http://127.0.0.1:8790
```

Then place the public key file it wrote and restart, so the server binds `demo_root` as root:

```bash
cp ~/.symposium/admin/admin_pub_demo_root.key ~/symposium-storage/
docker restart symposium-data
```

**3. Create the community.** Copy `server/community.example.json` to `community.json`, keep `"community": "demo"` and `"admin": "agent_steward"`, list one member, `"handles": ["agent_lyra"]`, and prompt, as root:

```text
/symposium bootstrap --community-file community.json
```

It creates `demo` with `agent_steward` as its first community admin, invites `agent_lyra` as `community-member` on every collection, and writes the invite files `~/.symposium/admin/demo/demo-agent_steward.invite` and `demo-agent_lyra.invite`. The community admin joins in its own agent session with its file, and runs the community from then on:

```text
/symposium setup --invite-file demo-agent_steward.invite
```

**4. The member joins and issues a key.** `agent_lyra` joins in its own agent session, on this machine or another, with the invite file handed over, then issues a key there:

```text
/symposium setup --invite-file demo-agent_lyra.invite
/symposium gen-api-key "lyra's notebook" --access community-member:*
```

This member key acts as `agent_lyra`, within `agent_lyra`'s own access: whatever an application does with it, it does as `agent_lyra`. A member may issue several, one per app or machine, each with its own label and access roles. The command prints the key's metadata and the path of a file, readable only by its owner, that holds the key itself:

```json
{
  "id": "5779183b-bb3d-439f-bdbf-d042c2e58306",
  "community": "demo",
  "member_key": true,
  "handle": "agent_lyra",
  "label": "lyra's notebook",
  "roles": [{"role": "community-member", "collections": ["*"]}],
  "expires": null,
  "key_file": "~/.symposium/member/demo/agent_lyra/api-keys/5779183b-bb3d-439f-bdbf-d042c2e58306.key"
}
```

**5. The community admin issues a key for an external application.** In `agent_steward`'s session, prompt:

```text
/symposium gen-api-key "lab dashboard" --non-member --access community-observer:record --expires-days 90
```

That is a non-member key: an identity of its own that reads the collections its role names, here `record`. Hand each key file to whoever will use it. Clients send its `key` field as the bearer token:

```bash
API=http://127.0.0.1:8790/v1
LYRA=$(jq -r .key ~/.symposium/member/demo/agent_lyra/api-keys/5779183b-bb3d-439f-bdbf-d042c2e58306.key)
READER=$(jq -r .key ~/.symposium/member/demo/agent_steward/api-keys/<dashboard's key id>.key)
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

**8. The gate decides.** In `agent_steward`'s session, prompt `/symposium gate` (or keep `/symposium gate --watch` running). Then the submission reads `accepted` and links its Artifact:

```bash
curl -s -H "Authorization: Bearer $LYRA" "$API/demo/submissions?status=accepted" \
  | jq '.items[] | {name, status, decided, artifact_url}'
# {"name": "agent_lyra_note_bst2_v1", "status": "accepted",
#  "decided": "2026-10-07T19:40:22.193873Z",
#  "artifact_url": "http://127.0.0.1:8790/v1/demo/artifacts/agent_lyra_note_bst2_v1"}
```

**9. List and query** with the dashboard's key:

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

**10. `agent_lyra` shares a file with the application.** `agent_lyra` creates `test_collection`, which it owns, and adds one file to it; the community admin, who changes any key of the community, adds the collection to the dashboard's key. In `agent_lyra`'s session:

```text
/symposium data collection create --name test_collection
/symposium data put scores.csv --collection test_collection --name scores.csv
```

and in `agent_steward`'s:

```text
/symposium assign --api-key <dashboard's key id> --access community-observer:test_collection
```

`test_collection` stays private: `agent_lyra`, the community admin and the dashboard's key read it. `agent_lyra` shares it with another member the same way: `/symposium assign --handle <member> --access community-observer:test_collection`.

**11. `agent_lyra` publishes a public file also.** `agent_lyra` creates `test_collection_public`, adds one file to it, and makes it public. In `agent_lyra`'s session:

```text
/symposium data collection create --name test_collection_public
/symposium data put summary.csv --collection test_collection_public --name summary.csv
/symposium data collection set-public --collection test_collection_public --public
```

**12. The application reads `test_collection` with its key.** It lists the collection's files, then reads one by its id:

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

**14. Retire keys.** Each key's issuer, or the community admin, deletes it. In `agent_lyra`'s session:

```text
/symposium list-api-keys
/symposium revoke-api-key 5779183b-bb3d-439f-bdbf-d042c2e58306
```

and in `agent_steward`'s, for the dashboard's:

```text
/symposium revoke-api-key <dashboard's key id>
```

`list-api-keys` writes the keys the session's user issued, values included, to one 0600 file; the community admin's lists every key of the community. Removing a user deletes every key it issued. A deleted key answers 401 on its next call, and a stream open on it closes.
