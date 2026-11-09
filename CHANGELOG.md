# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
The Symposium Data server, its Helm chart (Symposium Helm) and the Symposium Skill are
versioned and released separately, each under its own heading.

## [Symposium Skill 0.2.0] - Unreleased

Works with Data Server 0.2.0. Connected to a server from another release, it stops and says
which skill that server needs.

### Added

- **Access roles.** Everyone works under an access role: root, server admin, community admin,
  gate-keeper, community member or community observer. Members and observers can be limited to
  particular collections. You can see your own roles and what they allow, and a command your
  roles don't allow is refused with an explanation of what it needs.
- **Delegated administration.** Root sets up the server and invites server admins. A server
  admin creates communities, each with its own community admin, who invites members, assigns
  roles and runs the gate. Root is not needed to run a community.
- **Managing people.** Commands to invite people with roles, assign and remove roles, list and
  remove users, and let a server admin work in any community. API keys carry roles too.
- **Messages addressed to you are shown** when you join, sync, publish or validate, each once,
  on one line that cannot pass itself off as a message from the gate or the server. Agents are
  asked to report them.
- **Record browser filters.** The overview can show and hide members, artifact types and kinds
  of links. Prose citations and messages start hidden. Each rebuild reports how long it took.

### Changed

- **Upgrading from 0.1 takes no steps.** Keys and sessions carry over, and nobody rejoins.
- **Several server admins can share one machine.** Root and each server admin keep their own
  sessions, so one never replaces another's. Commands that open a community's session work as
  whoever you are currently working as, and you can name another person instead. Existing
  sessions are moved into place by the first command.
- **A server admin can invite a community's admin without opening that community first,** by
  naming the community in the invite. Leaving it out explains what's missing instead of being
  refused for lack of a permission.
- **Joining with access to only some collections works.** You join and work without a local copy
  of the record.
- **A gate that runs continuously stops when its gate role is removed,** and says how to
  resume.
- **Research goals are recognised** as a type the profile defines. One that doesn't declare
  itself non-groundable gets a review note, which refuses nothing.
- **The claim map** opens its purpose and rationale on demand and can be expanded to the whole
  pane. The overview explains its layout, and its graph fills the window.
- **One document describes roles and access:** every role, what each permission allows, API
  keys, and who may change whose access. The other guides link to it. Every link in the skill
  package is checked each time the package is built.

### Fixed

- A reply from the gate is listed once, even when a continuous sync runs beside other commands.

## [Data Server 0.2.0] - Unreleased

A breaking release: it needs Symposium Skill 0.2.0, and clients of 0.1 can no longer connect.

### Added

- **Role-based access.** Six fixed roles, given to people and to API keys, decide what each may
  do. Members and observers can be limited to particular collections. A person always keeps
  access to the collections they created; an API key reaches only the collections it is given.
- **Delegated administration.** Root, set by the server's key file, appoints server admins.
  Server admins create communities, each with a first community admin who runs it.
- **People as users.** Everyone is a user of one community, or of the server as a whole.
  Removing someone keeps them on record as removed: their name is retired, their published work
  stays credited to them, their sign-ins end, and every API key they made stops working.
- **Invites carry roles.** The roles are kept on the server and given when the person joins.
  Pending invites can be listed, issued again and cancelled.
- **Automatic upgrade.** A 0.1 server upgrades itself on its first start as 0.2.0, after backing
  up its database, and the server backs up its database before every later upgrade too. The 0.1
  admin becomes root, members keep full access, and every collection keeps its owner.
- **Research goals are recognised** by the server's checks, as they are by the skill.

### Changed

- **The API is reorganised** into one consistent structure: each community's data sits under
  that community, and every address names a thing rather than an action. Any community name is
  allowed except "admin".
- **Community members always read their community's record,** which publishing checks against.
  The list of roles shows this alongside each role's permissions.
- **Creating a community names its first community admin.**
- **Sharing a collection** means giving someone read access to it.
- **The server's status shows who root is.**

## [Symposium Helm 0.1.2] - Unreleased

### Changed

- **Deploys Data Server 0.2.0,** which upgrades an existing server in place on its first start.
- **Allows up to 10 minutes for the first start of a new release,** time for the database
  backup and upgrade.
- **The public address setting is documented** as the address written into invite files.

## [Symposium Skill 0.1.3] - 2026-10-14

For Data Server 0.1.2.

### Added

- **`data collection list`**: the collections the member may use in the community, each with
  its owner, whether it is public, and the member's `read`, `write` and `manage` access.

### Changed

- **The CLI speaks Data Server 0.1.2.** Every command obtains a session key with the
  session's private key file and calls `/v1`; `owner whoami` reads `GET /v1/{community}/me`.
- **Any Member issues keys for applications.** `gen-api-key <label> --non-member` issues an
  non-member issued key (`role: non-member`), which reads the collections it is granted
  with `data collection grant --collection <c> --api-key <id> --perm read`, and any public
  collection. The admin's issued keys are non-member issued keys, granted the same way.
- **`data collection grant`** grants a Member `read` or `write`, or a non-member issued key
  `read`, and withdraws with `--revoke`; it replaces `collection grant-write`.
  `data get --api-key-file` reads with a key file from `gen-api-key`.

### Removed

- **`data keys mint|list|revoke` and `data get --read-key-file`**, with the server's read keys.

### Fixed

- **An option's value stays as given.** `data put scores.csv --name scores.csv` names the file
  `scores.csv` on the server, also when a local file shares that name.

## [Data Server 0.1.2] - 2026-10-14

### Changed

- **One API, at `/v1`.** The record's routes, formerly the Symposium Data API at `/api/v1`,
  now sit beside the data server's own routes for communities, members, keys, collections
  and files, under one contract, [`api/openapi.yaml`](api/openapi.yaml), which describes
  every route with the roles it allows; every route applies the rule the contract states.
- **One credential, the API key (`sak_…`), for every route.** It is either a session key or
  an issued key. The session management routes (`POST /v1/{community}/auth/token`,
  `POST /v1/admin/token`) answer a session key in `key`, obtained with the member's or the
  admin's private key file, in place of a JWT access token. Routes that change access, keys
  or the server take a session key.
- **Collections decide access, for every key.** The record's routes read the `record`
  collection: a key reads them while its holder may read `record`, by a grant or because it
  is public. Publishing takes the Member's `write` grant on `inbox`. A withdrawn grant is
  felt on the next request and closes an open stream.
- **Any Member issues a non-member issued key** (`role: non-member`), and a collection's
  owner, or the admin, grants it `read` (`PUT /v1/{community}/collections/{collection}/grants`
  with `api_key_id`).
- **Settings are `SYMPOSIUM_SERVER_*`:** `SYMPOSIUM_SERVER_SESSION_TTL`,
  `SYMPOSIUM_SERVER_INVITE_HOURS`, `SYMPOSIUM_SERVER_PUBLIC_URL`,
  `SYMPOSIUM_SERVER_MAX_STREAMS`, `SYMPOSIUM_SERVER_STREAM_HEARTBEAT` and
  `SYMPOSIUM_SERVER_CONTRACT`.
- **`GET /v1/{community}/me`** reports the calling key: its kind, role, Member, label, grants
  and the public key whose private key file obtained a session key. It replaces `whoami`.
- **Every refusal answers one body, `{detail, code}`.**
- **A cited file is read on the same API.** Resolving a Content Object whose `location` is a
  `symposium-data:` citation, or reading the Object, answers its `location_url`, the file
  version's content, which its collection's access governs.

### Added

- **The 8 MiB limit on a request body is enforced** (413). A file's content and an import
  stream past it, bounded by the quota.
- **Browser apps**: `SYMPOSIUM_SERVER_CORS_ORIGINS` lists the origins allowed to call the API.
- **`GET /v1/{community}/collections`** lists the collections the caller may use, with the
  caller's `read`, `write` and `manage` access on each; with no key, the public ones.

### Removed

- **FastAPI's generated `/docs`, `/redoc` and `/openapi.json`.** The contract is served at
  `/v1/openapi.yaml` and `/v1/openapi.json`.
- **Read keys (`sdr_…`)** and their routes. A file has its collection's access: share it with
  a grant to a non-member issued key, or by making its collection public.
- **The JWT access token** and the server's token signing key.

## [Symposium Helm 0.1.1] - 2026-10-14

### Changed

- **Deploys Data Server 0.1.2** (`appVersion`).
- **`publicUrl` sets `SYMPOSIUM_SERVER_PUBLIC_URL`**, the server's renamed setting.
- **`env` takes `SYMPOSIUM_SERVER_*` names only**, the server's renamed settings. Rename
  existing entries: `SYMPOSIUM_CONTROL_API_TOKEN_TTL` → `SYMPOSIUM_SERVER_SESSION_TTL`,
  `SYMPOSIUM_CONTROL_API_INVITE_HOURS` → `SYMPOSIUM_SERVER_INVITE_HOURS`,
  `SYMPOSIUM_DATA_API_MAX_STREAMS` → `SYMPOSIUM_SERVER_MAX_STREAMS`,
  `SYMPOSIUM_DATA_API_HEARTBEAT` → `SYMPOSIUM_SERVER_STREAM_HEARTBEAT`.
- **Ingress guidance** adds the request body size uploads need (runbook §5.2).

### Added

- **`corsOrigins`** sets `SYMPOSIUM_SERVER_CORS_ORIGINS`: the browser origins allowed to call
  the API.

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
