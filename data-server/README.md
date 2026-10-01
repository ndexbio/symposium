# Symposium Data server

A single Docker image that runs Symposium Data, the versioned file store Symposium communities use to persist, share and cite data files. The image contains three services, managed by `supervisord`:

- **the data service**: FastAPI on port 8080, the only port the container exposes;
- **PostgreSQL 16**: the server's records. Today that means its configuration and owner identities, managed by Alembic migrations;
- **SeaweedFS**: the internal S3 store for file contents. It is never exposed; the data service streams every byte.

The design and requirements are in the spike on ndexbio/symposium#13. Its sections are referred to here as R-*.

## Layout

| Path | What it is |
|---|---|
| `service/` | The `symposium_data` Python package: the HTTP API, `data-admin` and the Alembic migrations, plus the tests. Locked with `uv.lock`. |
| `docker/Dockerfile` | Multi-stage build: `runtime-base` (PostgreSQL, supervisor, gosu, SeaweedFS with a pinned sha256), then `builder` (installs the locked wheel into `/opt/venv`), then `deploy`. |
| `docker/supervisord/` | One config snippet per service. `start.sh` assembles them. |
| `docker/scripts/start.sh` | Container start-up: version banner, first-boot secrets, PostgreSQL init, registration guard, then `exec supervisord`. |
| `docker/k8s-data-deployment.yml` | Kubernetes or Podman deployment on a single ReadWriteOnce PVC. |
| `RUNBOOK.md` | How to run, initialize, verify and tear down. |

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

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SYMPOSIUM_DATA_REGISTRATION` | `invite` | `open` (a server bound to localhost) or `invite` (a server reachable by other machines). It is reported by `GET /v1/status`. In `invite` mode the container refuses to start without `SYMPOSIUM_DATA_PUBLIC_BASE_URL`. |
| `SYMPOSIUM_DATA_PUBLIC_BASE_URL` | none | The public URL of the server. Required in `invite` mode; reported by `GET /v1/status`. |
| `SYMPOSIUM_DATA_TRUSTED_PROXY` | `127.0.0.1` | The only address whose `X-Forwarded-*` headers are trusted. |

All state lives under `/apps` inside the container: one volume, or a PVC. Internal secrets are generated on first boot with mode 0600 and are never baked into the image.
