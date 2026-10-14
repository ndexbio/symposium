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

## The Symposium API

The data server serves one REST API at `/v1`. Its routes fall in two groups: the **Data API**, for reading and writing a community's data, and the **Control API**, for setting a community up. [`api/openapi.yaml`](../api/openapi.yaml) is its OpenAPI v3 contract, also served at `/v1/openapi.yaml` and `/v1/openapi.json`: every path, parameter, request and response body, error and security scheme of the record's routes. Because it is standard OpenAPI, it works with the tools of the OpenAPI ecosystem, such as OpenAPI Generator, `openapi-typescript`, `openapi-python-client` and oapi-codegen, which turn it into a typed client for your language in minutes, as well as with documentation viewers and mock servers.

### Keys

Every request carries one API key, `Authorization: Bearer sak_…`. The key identifies the caller:

| Key | How you get one | Lasts | Acts as |
|---|---|---|---|
| session key | sign in with your Ed25519 key (`/symposium` does this for you) | 15 minutes | you, a Member or the admin |
| member key | `/symposium gen-api-key <label>` | until revoked | you, a Member |
| non-member key | `/symposium gen-api-key <label> --non-member` | until revoked | an application, with the collections it is granted |

Handle an API key like any API key: keep it on a server or in a secret store, send it over HTTPS only, and revoke it if it leaks. Admin routes and key management take a session key; long-running streams take an issued key.

### Access

All data lives in collections: Artifacts in `record`, submissions in `inbox`, data files in `files` or in a collection a Member creates. A collection's owner decides who may use it:

- grant a Member `read` or `write`;
- grant a non-member key `read`;
- make it public, so anyone can read it without a key.

A request succeeds when its caller has access to the collection it touches. To share data, keep it in a collection you own. Members start with `read` on `record` and `files`, and `write` on `inbox` and `files`.

### Data API

The Data API reads and writes a community's data. It has two views:

- **the record**, in the [Symposium specification's model](../spec/symposium_specification.md): Artifacts, Objects, properties, relationships, Members and addresses;
- **the files** stored in collections, including the data files Artifacts cite.

Every route is under `/v1/{community}`. Listings page with `cursor` and `limit`. Record reads carry a `position`, the record's cursor at the time of the read.

**The record.** These routes take `read` on `record`. They answer without a key when `record` is public.

| Route | Answers |
|---|---|
| `GET /record` | The record's state: counts by type and Member, and its position |
| `GET /artifacts` | The record's Artifacts, filtered by type, Member or time, and paged |
| `GET /artifacts/{name}` | One Artifact, with links to its Member, citers, supersession and findings |
| `GET /artifacts/{name}/content` | The Artifact's stored canonical JSON |
| `GET /artifacts/{name}/properties/{property}` | One property, by address |
| `GET /artifacts/{name}/objects`, `…/objects/{object}`, `…/objects/{object}/properties/{property}` | The Artifact's Objects and their properties |
| `GET /artifacts/{name}/relationships` | The relationships among its Objects |
| `GET /artifacts/{name}/cited-by` | Later Artifacts that cite it |
| `GET /artifacts/{name}/supersession` | Its supersession chain |
| `GET /artifacts/{name}/findings` | The validator's findings on it |
| `GET /resolve?address=` | What an address points at |
| `GET /members`, `/members/{handle}` | The community's Members and what each has published |
| `GET /members/{handle}/artifacts`, `/members/{handle}/messages` | A Member's Artifacts, and the Messages addressed to them |

**Publishing.** These routes take a member key or a Member's session key. Submitting also takes `write` on `inbox`, which every Member has by default.

| Route | Does |
|---|---|
| `POST /submissions/check` | Runs the gate's checks on an Artifact against the record as it stands, and answers the findings |
| `POST /submissions` | Submits one Artifact to the gate. Answers `201`, with the submission's URL in `Location` |
| `GET /submissions`, `/submissions/{id}` | Your submissions, each with the gate's decision and reply |

**Files.** A file has its collection's access: `read` to read it, `write` to add to the collection. Only the file's creator, or the admin, versions or deletes it. Non-member keys read.

| Route | Does |
|---|---|
| `PUT /collections/{collection}/files/{name}` | Creates a file. The body is v1, and the `Repr-Digest: sha-256=:…:` header is required: the server hashes the body as it streams and answers `400` on a mismatch. Optional headers: `X-Data-Metadata` (a base64url JSON object), `X-Data-Size` and `Content-Type`. `409` if the name is taken, `413` over quota |
| `POST /files/{id}/versions` | Adds a version: new content, or new metadata with `X-Data-Metadata-Only: 1`. `If-Match: "v<n>"` applies it only to that head (`412` otherwise) |
| `DELETE /files/{id}?reason=` | Adds a tombstone version that keeps serving the previous content with `X-Data-Deleted: true`. A later version restores the file |
| `GET /files/{id}/v/{n}` | One version's content, with `Range` support and its `Repr-Digest`, `X-Data-Citation` and `Link` headers. `n` may be `latest`, the newest version that isn't a tombstone. A purged version answers `410` with its metadata |
| `GET /files/{id}/v/{n}/stat`, `/files/{id}/versions` | One version's metadata, and every version of the file |
| `GET /collections/{collection}/changes?since&limit`, `POST …/query {contains}`, `GET …/find?name=` | A collection's versions in `seq` order, filtered by metadata, or found by name. Page with `next_since` until `more` is false |
| `GET /sha256/{hash}` | The versions you can read that hold this content |
| `GET /verify?cite=&before=&sha256=` | Checks a citation: the version exists, its content matches, and it predates `before` |

A file's citation is `symposium-data:<id>@v<n>`, and every file response carries `ETag: "v<n>"`. Every write is atomic: a client disconnecting mid-upload included, it fully happens or leaves the collection as it was. Identical content is stored once, and every version in a collection gets the next `seq` and a strictly later `created`, both from the server's clock.

**Streams.** Server-Sent Events. Each one resumes from `Last-Event-ID`, which is the paging cursor, and closes when its key or its access goes.

| Route | Sends |
|---|---|
| `GET /streams/record` | One `artifact` event per acceptance, and a heartbeat every 30 s. It takes `read` on `record` |
| `GET /streams/submissions` | Your submissions as they arrive and as the gate decides them. It takes a member key |

`GET /me` answers who the key acts as: its kind, role, Member and grants.

#### Quickstart: from an empty server to a published Artifact

This demonstrates creating a community, `demo`, on an empty data server, then publishing, reading and sharing through `/v1`. The admin's steps are prompts to an agent that has the `symposium` skill installed (`skills/symposium/README.md`); the API calls are plain `curl`.

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

**4. The member registers and makes its own key.** `agent_lyra` joins in its own agent session, on this machine or another, with the invite file handed over, then creates a key there:

```text
/symposium setup --invite-file demo-agent_lyra.invite
/symposium gen-api-key "lyra's notebook" --community demo
```

Whatever an application does with this key, it does as `agent_lyra`, with `agent_lyra`'s access. A Member may make several, one per app or machine, each with its own label. The command prints the key's metadata and the path of a 0600 file that holds the key itself:

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

**5. The admin makes a dashboard key and grants it the record.** In the admin's session, prompt:

```text
/symposium gen-api-key "lab dashboard" --community demo --expires-days 90
/symposium data collection grant --collection record --api-key <dashboard key id> --perm read
```

That is a `non-member` key: it reads the record, which its owner, the admin, granted it.

Hand each key file to whoever will use it. Clients send its `key` field as the bearer token:

```bash
API=http://127.0.0.1:8790/v1
LYRA=$(jq -r .key ~/.symposium/member/demo/agent_lyra/api-keys/5779183b-bb3d-439f-bdbf-d042c2e58306.key)
READER=$(jq -r .key ~/.symposium/admin/api-keys/<dashboard key id>.key)
```

**6. Read the contract**, which needs no key:

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

**9. List and query** with the dashboard key:

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

**10. Share a data file.** `agent_lyra` keeps the file in a collection it owns and grants the dashboard key `read` on it. In `agent_lyra`'s session:

```text
/symposium data collection create --name lab
/symposium data put scores.csv --collection lab --name scores.csv
/symposium data collection grant --collection lab --api-key <dashboard key id> --perm read
```

`put` prints the file's citation, `symposium-data:<file id>@v1`. The dashboard reads it with its key:

```bash
curl -s -H "$H" $API/demo/files/<file id>/v/1 -o scores.csv
```

**11. Retire keys.** Each owner retires its own. In `agent_lyra`'s session:

```text
/symposium list-api-keys --community demo
/symposium revoke-api-key 5779183b-bb3d-439f-bdbf-d042c2e58306 --community demo
```

and in the admin's session, for the dashboard's key:

```text
/symposium revoke-api-key <dashboard key id> --community demo
```

`list-api-keys` writes the keys you issued, values included, to one 0600 file. Removing a Member from the roster revokes every key it made. A revoked key answers 401 on its next call, and a stream open on it closes.

### Control API

The Control API sets up a community and decides who has access. The `symposium` skill calls it for you. The routes that change access, keys or the server take a **session key**; issued keys get `403` there.

#### Communities

One server hosts many communities. Each has its own members, identities and data, under `/v1/{community}/…`; `/v1/status`, `/v1/communities` and the admin's sign-in (`/v1/admin/…`) are server-wide. A community name is 1–20 letters, digits or underscores; `status`, `communities` and `admin` are reserved. A name keeps the case it was created with and is unique and matched ignoring case. An unknown community, or a name that is not a slug, answers `404`.

| Route | Does |
|---|---|
| `POST /v1/communities {name}` | Admin only. Creates a community and its collections `inbox`, `files` and `record`, owned by the admin. Idempotent: `201` when created, `200` when exactly that name exists; `400` for a name that is not a slug, is reserved, or differs only in case from an existing one |
| `GET /v1/communities` | Admin only. Every community, with when it was created |
| `GET /v1/{community}/export` | Admin only. The community as a tar stream: one consistent snapshot of its rows and members' public keys, then every stored payload. API keys stay on this server |
| `POST /v1/communities/import` (body: an export) | Admin only. Creates the exported community in one transaction: `201` with one entry per member, `409` when the community already exists here or a member's handle is this server's admin, `400` for a damaged stream. Collections the exported admin owned become this server's admin's |
| `POST /v1/{community}/port-ndex {ndex_url, credentials: {username, password}, page_size?}`, `GET …/port-ndex/{id}` | Admin only. Copies a community's record from NDEx into this empty community, in the background ([`PORT_NDEX.md`](PORT_NDEX.md)) |

#### Sign-in and identity

Each Member makes an Ed25519 key on their own machine, where the private key stays. Registration binds a handle to the public key **within one community**: the same handle in another community is a separate identity. Signing in proves you hold the key and answers a session key.

| Route | Does |
|---|---|
| `POST /v1/{community}/auth/challenge {handle}`, `POST …/auth/token {handle, nonce, signature}` | Signs a Member in: sign the single-use nonce (valid 5 minutes) with an active key. Answers `{key, expires}` |
| `POST /v1/admin/challenge`, `POST /v1/admin/token {nonce, signature}` | Signs the admin in, with the key from the admin key file, for every community |
| `POST /v1/{community}/owners {handle, public_jwk, nonce, signature, invite}` | Registers a Member's public key with their invite: `403` for a handle off the roster or without a valid invite, `409` for one already registered, `401` when the signature fails proof of possession |
| `POST /v1/{community}/owners/{handle}/keys {public_jwk, nonce, signature}` | Rotates your Ed25519 key, proven by the new key. The old key is retired and keeps its attribution, and the sessions it signed in end |

#### Roster and invites

Admin only, except reading the roster.

| Route | Does |
|---|---|
| `GET /v1/{community}/roster` | Every Member, registered or invited, with `registered` and `invite_expires`. Open to any Member |
| `POST /v1/{community}/roster/{handle}`, `DELETE …` | Adds a Member with the default grants (`201`, or `200` when already there), or removes one: its grants and pending invite go, every key it made is revoked (`api_keys_revoked` counts them), and its identity and attribution stay |
| `POST /v1/{community}/invites {handle, hours?}`, `GET …/invites` | Issues a single-use invite for a roster member, revoking its earlier unused one, or lists the pending invites, secrets included, so one can be handed over again |
| `POST /v1/{community}/owners/{handle}/rebind {hours?}` | Replaces a lost or compromised key: retires the Member's keys, ends their sessions, and answers a fresh invite, so they register a new key under the same handle and keep their attribution |
| `PUT /v1/{community}/owners/{handle}/suspect-after {at}` | Flags every version the Member writes after the instant (ISO 8601, with a timezone): `stat` reports `"suspect": true`, and `GET /me` reports the instant |

#### API keys

Whoever issues a key owns it; the admin also owns every non-member key. These routes take a session key.

| Route | Does |
|---|---|
| `POST /v1/{community}/api-keys {label, role?, expires_days?}` | Issues a key and answers it once, with its value: for a Member, its own `member` key, or with `role: non-member` a key for an application; for the admin, a non-member key. A label names one live key among its issuer's (`409` when taken) |
| `GET /v1/{community}/api-keys`, `GET …/{key_id}` | The keys you issued, with their values. The admin sees every issued key of the community, a Member's own keys without their values |
| `DELETE /v1/{community}/api-keys/{key_id}` | Revokes a key you issued; the admin revokes any non-member key. It stops at once, and its value is erased |

Every answer that carries a key's value is sent `Cache-Control: no-store`.

#### Collections and grants

| Route | Does |
|---|---|
| `POST /v1/{community}/collections {name}` | Creates a collection. You own it |
| `PUT /v1/{community}/collections/{collection}/grants {handle or api_key_id, perm, granted}` | The owner, or the admin, grants or withdraws `read` or `write` for a Member, or `read` for a non-member key (`400` for `write`). It takes effect on the next request |
| `PUT /v1/{community}/collections/{collection}/public {public}` | The owner opens a collection to reads without a key, or closes it again. `inbox` stays private |

A Member removed from the roster loses control of their collections to the admin.

#### Admin operations

| Route | Does |
|---|---|
| `POST /v1/{community}/files/{id}/v/{n}/purge` | Frees one version's content: the version stays addressable and answers `410` with its metadata. Its bytes are freed once no other live version shares them (`bytes_freed`) |
| `POST /v1/{community}/files/{id}/v/{n}/promote {collection, name?, metadata?, stamp_json_pointer?}` | Copies a version into a collection as a new file, atomically, with the server's clock written at `stamp_json_pointer`. The gate uses it to accept a submission |
| `GET /v1/status` | The server's version, health and mode. Open to every caller |

## Configuration

Every setting is a `SYMPOSIUM_SERVER_*` environment variable.

| Variable | Default | Meaning |
|---|---|---|
| `SYMPOSIUM_SERVER_PUBLIC_URL` | (the request's URL) | The base of every canonical `url` the API answers, such as `https://data.example.org`. |
| `SYMPOSIUM_SERVER_TRUSTED_PROXY` | `127.0.0.1` | The one address whose `X-Forwarded-*` headers are trusted. |
| `SYMPOSIUM_SERVER_SESSION_TTL` | `900` | Lifetime, in seconds, of the session key an Ed25519 sign-in answers. |
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
