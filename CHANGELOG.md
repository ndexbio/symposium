# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
The Symposium Data server, its Helm chart (Symposium Helm) and the Symposium Skill are
versioned and released separately, each under its own heading.

## [Symposium Skill 0.1.1] - 2026-10-09

### Changed

- **The watch loops are hardened to be stopped and resumed.** In the Python tools behind
  `gate --watch`, `sync --watch` and `serve`, the loop is endless by default. The agents that
  run them as background tasks typically won't let a process run past a fixed limit (in Claude
  Code, 30 minutes or more), so the loops now handle being stopped at any point and resumed
  by a restart: a stop by signal ends one cleanly, even mid-pass, every local write is atomic,
  and a restart picks up where the last run left off and takes over from any copy still
  running, so exactly one runs.
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

## [Symposium Helm 0.1.0] - 2026-10-10

### Added

- **The inaugural release of the data server's Helm chart**, `symposium-helm`, published as
  `oci://registry-1.docker.io/ndexbio/symposium-helm:0.1.0`, installable with Helm 3.8 or
  later, or 4, without `helm repo add`, and as `symposium-helm-0.1.0.tgz` on its GitHub
  release. It deploys `ndexbio/symposium-data:0.1.0` (its `appVersion`) as one replica on
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
