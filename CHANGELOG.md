# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
The Symposium Data server, its Helm chart (Symposium Helm) and the Symposium Skill are
versioned and released separately, each under its own heading.

## [Unreleased]

### Changed

- **One API, at `/v1`.** The record's routes, formerly the Symposium Data API at `/api/v1`,
  now sit beside the data server's own routes for communities, members, keys, collections
  and files, under one contract, [`api/openapi.yaml`](api/openapi.yaml).
- **One credential, the API key (`sak_…`), for every route.** An Ed25519 sign-in
  (`POST /v1/{community}/auth/token`, `POST /v1/admin/token`) answers a session key in
  `key`, in place of a JWT access token. Routes that change access, keys or the server take a
  session key.
- **Collections decide access, for every key.** The record's routes read the `record`
  collection: a key reads them while its holder may read `record`, by a grant or because it
  is public. Publishing takes the Member's `write` grant on `inbox`. A withdrawn grant is
  felt on the next request and closes an open stream.
- **Any Member issues keys for applications.** `gen-api-key <label> --non-member` makes a
  `non-member` key, which reads the collections its owner grants it with
  `data collection grant --collection <c> --api-key <id> --perm read`. The admin's keys are
  `non-member` keys, granted the same way.
- **`data collection grant`** grants a Member `read` or `write`, or a non-member key `read`,
  and withdraws with `--revoke`; it replaces `collection grant-write`. `data get
  --api-key-file` reads with a key file from `gen-api-key`.
- **Settings are `SYMPOSIUM_SERVER_*`:** `SYMPOSIUM_SERVER_SESSION_TTL`,
  `SYMPOSIUM_SERVER_INVITE_HOURS`, `SYMPOSIUM_SERVER_PUBLIC_URL`,
  `SYMPOSIUM_SERVER_MAX_STREAMS`, `SYMPOSIUM_SERVER_STREAM_HEARTBEAT` and
  `SYMPOSIUM_SERVER_CONTRACT`. The Helm chart's `publicUrl` sets
  `SYMPOSIUM_SERVER_PUBLIC_URL`.
- **`GET /v1/{community}/me`** reports the calling key: its kind, role, Member, label, grants
  and signing key. It replaces `whoami`.
- **Every refusal answers one body, `{detail, code}`.**
- **One contract for every route.** [`api/openapi.yaml`](api/openapi.yaml) now describes the
  data server's own routes too, files, communities, sign-in, the roster, keys and
  collections, each with the roles it allows; every route applies the rule the contract
  states.
- **A cited file is read on the same API.** Resolving a Content Object whose `location` is a
  `symposium-data:` citation, or reading the Object, answers its `location_url`, the file
  version's content, which its collection's access governs.

### Added

- **The 8 MiB limit on a request body is enforced** (413). A file's content and an import
  stream past it, bounded by the quota.
- **Browser apps**: `SYMPOSIUM_SERVER_CORS_ORIGINS` (the Helm chart's `corsOrigins`) lists the
  origins allowed to call the API.

### Removed

- **FastAPI's generated `/docs`, `/redoc` and `/openapi.json`.** The contract is served at
  `/v1/openapi.yaml` and `/v1/openapi.json`.
- **Read keys (`sdr_…`)** and their routes and commands (`keys mint|list|revoke`,
  `get --read-key-file`). A file has its collection's access: share it with a grant to a
  `non-member` key, or by making its collection public.
- **The JWT access token** and the server's token signing key.

## [Symposium Skill 0.1.2] - 2026-10-11

### Added

- **`serve --port 0` serves on any free port and prints which**, in its
  `serving  http://localhost:<port>/` line, so nothing else can take the port first. A serve
  started on a named port still takes over from one already serving there.

### Changed

- **Kubernetes deployments use the data server's Helm chart.** The README, `SKILL.md` and the
  steps `admin-config` prints now install the server with the chart
  (`oci://registry-1.docker.io/ndexbio/symposium-helm`) and give it the admin key with
  `helm upgrade --set-file adminKey.publicKey=<file>`, which restarts the server; there is
  no Secret to create and no `kubectl rollout restart`. The bundle ships the chart in
  `toolchain/data-server/helm/symposium-helm/`.
- **The data server's runbook is one flow from choice to a running server:** Docker on your
  machine, Kubernetes on Docker Desktop, or a remote cluster behind a Gateway (Gateway API)
  or an Ingress, then the admin key, the move off NDEx (port-ndex), and operating it.

### Removed

- **The raw Kubernetes manifest, `toolchain/data-server/docker/k8s-data-deployment.yml`.**
  The Helm chart replaces it.

### Fixed

- **A stop never splits one of the gate's decisions.** A ctrl-c or SIGTERM that reached
  `gate --watch` between the promote of an accepted submission and its bookkeeping could
  leave the artifact in the record without the gate counting, showing or caching the
  decision. A stop that arrives during a decision now waits for it to be whole, then stops
  the gate as before.

## [Symposium Skill 0.1.1] - 2026-10-09

### Changed

- **The watch loops are hardened to be stopped and resumed.** In the Python tools behind
  `gate --watch`, `sync --watch` and `serve`, the loop is endless by default. The agents that
  run them as background tasks typically won't let a process run past a fixed limit (in Claude
  Code, 30 minutes or more), so the loops now handle being stopped at any point and resumed
  by a restart: a stop by signal ends one cleanly, even mid-pass, every local write is atomic,
  and a restart picks up where the last run left off and takes over from any copy still
  running, so exactly one runs.

## [Data Server 0.1.1] - 2026-10-11

### Added

- **`SYMPOSIUM_SERVER_HEARTBEAT`** sets how often an upload in progress refreshes its
  timestamps; by default a third of `SYMPOSIUM_SERVER_PENDING_TTL`, within 0.2 and 60 seconds,
  as before.

### Fixed

- **The janitor and a commit can no longer both act on one upload.** The janitor removed an
  expired upload's bytes and then its row as two separate steps, and a commit that reached the
  upload in between turned it ready with its bytes gone; a commit also succeeded on an upload
  the janitor had already removed. The janitor now holds the upload's row while it removes
  it, passing by one a commit holds, and a commit, or an upload's heartbeat, that finds its
  upload gone refuses it with a 409 to send again. It took an upload stalled for longer than
  the pending TTL (a day by default) to meet either case.

## [Symposium Helm 0.1.0] - 2026-10-11

### Added

- **The inaugural release of the data server's Helm chart**, `symposium-helm`, published as
  `oci://registry-1.docker.io/ndexbio/symposium-helm:0.1.0`, installable with Helm 3.8 or
  later, or 4, without `helm repo add`, and as `symposium-helm-0.1.0.tgz` on its GitHub
  release. It deploys `ndexbio/symposium-data:0.1.1` (its `appVersion`) as one replica on
  one ReadWriteOnce volume that `helm uninstall` keeps. It publishes the server through a
  Gateway API HTTPRoute (`expose.mode: gateway`) or an Ingress (`expose.mode: ingress`),
  with the Data API's streams kept open, and takes the admin's public key through its values
  (`--set-file adminKey.publicKey=<file>`), restarting the server when it changes. Start
  with [`data-server/RUNBOOK.md`](data-server/RUNBOOK.md), "Run it on Kubernetes with Helm";
  [`data-server/helm/symposium-helm/README.md`](data-server/helm/symposium-helm/README.md)
  lists every value.

## [Data Server 0.1.0] - 2026-10-07

### Added

- **The inaugural release of the Symposium Data server**, the image `ndexbio/symposium-data`.
  It runs PostgreSQL, SeaweedFS as the internal file store, and one API server with two REST
  APIs: the **Symposium Control API** (`/v1`), for the skill's CLI, authenticated with a
  member's or the admin's Ed25519 key; and the **Symposium Data API** (`/api/v1`), for web
  apps and services, authenticated with API keys. Start with
  [`data-server/README.md`](data-server/README.md).

## [Symposium Skill 0.1.0] - 2026-10-07

### Added

- **The inaugural release of the `symposium` skill**, the bundle `Symposium_skill.zip`,
  through which admins and members set up, publish to, gate and work with a community's
  record on a Symposium Data server. Start with
  [`skills/symposium/README.md`](skills/symposium/README.md).
  - **Install** Download from release artifact called `Symposium_skill.zip`, see - [Installing Symposium as agentic Skill](README.md#installing-symposium-as-agentic-skill).
