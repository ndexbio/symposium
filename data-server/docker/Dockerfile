# Symposium Data: one image running the data service, PostgreSQL and SeaweedFS under
# supervisord. Build context: data-server/.

# ── Runtime base: PostgreSQL 16 (PGDG), supervisor, gosu, SeaweedFS ─────────────────────────
# Debian plus PGDG rather than the postgres image: that image declares
# VOLUME /var/lib/postgresql/data, which would give every container a stray anonymous volume.
# All state here lives under /apps.
FROM debian:bookworm-slim AS runtime-base
ARG TARGETARCH
ARG POSTGRES_VERSION=16
ARG SEAWEEDFS_VERSION=4.48
ARG SEAWEEDFS_SHA256_AMD64=4a7d108384d044d95212d1342cdda9533fa55842c1c9b41f606ca3c8a9561124
ARG SEAWEEDFS_SHA256_ARM64=557e92c38c5c7d180748eb8e2b2b45e426f8e5282a4caca8e098a90d09f03a07
ENV PATH="/usr/lib/postgresql/${POSTGRES_VERSION}/bin:${PATH}"
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        | gpg --dearmor -o /usr/share/keyrings/postgresql.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/postgresql.gpg] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-${POSTGRES_VERSION} postgresql-client-${POSTGRES_VERSION} \
        python3 supervisor gosu \
    && apt-get purge -y gnupg && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
RUN set -eu; \
    case "${TARGETARCH}" in \
      amd64) sum="${SEAWEEDFS_SHA256_AMD64}" ;; \
      arm64) sum="${SEAWEEDFS_SHA256_ARM64}" ;; \
      *) echo "unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/weed.tgz \
      "https://github.com/seaweedfs/seaweedfs/releases/download/${SEAWEEDFS_VERSION}/linux_${TARGETARCH}.tar.gz"; \
    echo "${sum}  /tmp/weed.tgz" | sha256sum -c -; \
    tar -xzf /tmp/weed.tgz -C /usr/local/bin weed; \
    rm /tmp/weed.tgz; \
    chmod +x /usr/local/bin/weed
RUN groupadd -r symposium && useradd -r -g symposium -d /apps/data -s /usr/sbin/nologin symposium

# ── Builder: the locked dependencies and the service, installed as a wheel into /opt/venv ──
FROM runtime-base AS builder
COPY --from=ghcr.io/astral-sh/uv:0.10.4 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON=/usr/bin/python3 UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
# the service builds at /build/service, so its path dependency on ../../tools (symposium-rules,
# the named context `rules`) resolves to /tools
WORKDIR /build/service
COPY --from=rules pyproject.toml /tools/pyproject.toml
COPY --from=rules symposium_rules /tools/symposium_rules
COPY service/pyproject.toml service/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY service/ ./
RUN uv sync --frozen --no-dev --no-editable

# ── Deploy ───────────────────────────────────────────────────────────────────────────────────
FROM runtime-base AS deploy
ARG DATA_VERSION=
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
RUN mkdir -p /opt/symposium-data /apps \
    && if [ -n "${DATA_VERSION}" ]; then echo "${DATA_VERSION}" > /opt/symposium-data/VERSION; fi
# The API's contract lives outside this build context: the Makefile passes it as the named
# context `api` (api/).
COPY --from=api openapi.yaml /opt/symposium-api/openapi.yaml
COPY docker/supervisord/ /opt/symposium-data/supervisord/
COPY docker/scripts/start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/start.sh"]
CMD ["--data-api", "--postgres", "--seaweed"]
