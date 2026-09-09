#!/usr/bin/env bash
# symposium_ndex.sh — run the community's record server in a container.
#
#   ./symposium_ndex.sh --data DIR              start it (idempotent; safe to re-run)
#   ./symposium_ndex.sh --data DIR --logs       follow the container log
#   ./symposium_ndex.sh --data DIR --stop       stop and remove the container, keep the data
#   ./symposium_ndex.sh --data DIR --reset      stop, remove, AND DELETE ALL RECORD DATA
#
# --data is REQUIRED and names where this community's record lives. There is no default,
# deliberately: the record is the community's permanent history, it outlives any clone of
# this repository, and a directory chosen silently is a directory nobody can find again.
# `SYMPOSIUM_NDEX_DATA` sets it for a shell session; env.sh from `tools/setup.py` is the
# usual place for it.
#
# ONE COMMUNITY PER DIRECTORY. The container name and port are derived from the data
# directory, so two communities on one machine do not collide and neither has to be
# remembered. Override with SYMPOSIUM_NDEX_CONTAINER and SYMPOSIUM_NDEX_PORT.
#
# The record server is an NDEx instance. Symposium repurposes NDEx for accounts,
# permissions and storage and needs no modification to it, so this runs the published
# image as-is.
#
# THREE SERVICES, NOT FIVE. The image can also start Keycloak and MailHog. Symposium
# authenticates with HTTP Basic against NDEx itself and never sends mail, so neither is
# started: they are two more things to boot, to secure and to explain.
#
# BOUND TO LOCALHOST, DELIBERATELY. A fresh NDEx instance accepts anonymous account
# creation on POST /v2/user — that is what makes `bootstrap.py` possible without a
# chicken-and-egg problem, and it means anyone who can reach the port can create an
# account. Publishing this on 0.0.0.0 puts an open signup endpoint on your network.
# Change the bind address only when you have put something in front of it.
#
# The version is pinned. A reference implementation that follows a moving tag cannot
# say what it was tested against.
set -euo pipefail

IMAGE="ndexbio/ndex-rest:3.0.0"
BIND="${SYMPOSIUM_NDEX_BIND:-127.0.0.1}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DATA="${SYMPOSIUM_NDEX_DATA:-}"
READY_TIMEOUT="${SYMPOSIUM_NDEX_TIMEOUT:-180}"
ACTION="start"

usage() { sed -n '2,34p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage ;;
    --data)    DATA="${2:-}"; [ -n "${DATA}" ] || { echo "ERROR: --data needs a directory" >&2; exit 2; }; shift 2 ;;
    --data=*)  DATA="${1#*=}"; shift ;;
    --logs|--stop|--reset) ACTION="${1#--}"; shift ;;
    start)     shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [ -z "${DATA}" ]; then
  cat >&2 <<'EOF'
ERROR: --data is required. It names the directory holding this community's record.

    ./symposium_ndex.sh --data ~/symposium-mycommunity/server

There is no default. The record is the community's permanent history: it must
outlive this repository, be somewhere you can back up, and be somewhere you can
find again in six months. Choose the directory deliberately, once, and keep it.

To run the example rather than found a community, give it a directory of its own:

    ./symposium_ndex.sh --data ~/symposium-demo/server
EOF
  exit 2
fi

# Absolute, so the derived container name is stable no matter where it is invoked from.
# Resolved WITHOUT creating it: a path that is about to be rejected should not be left
# behind as a directory, least of all inside the repository.
case "${DATA}" in
  "~"|"~/"*) DATA="${HOME}${DATA#\~}" ;;
esac
case "${DATA}" in
  /*) ;;
  *)  DATA="$(pwd)/${DATA}" ;;
esac
# Collapse . and .. without requiring the path to exist yet.
DATA="$(printf '%s' "${DATA}" | awk -F/ '{n=0; for(i=1;i<=NF;i++){if($i==""||$i==".")continue; if($i==".."){if(n>0)n--; continue} p[++n]=$i} s=""; for(i=1;i<=n;i++)s=s"/"p[i]; print (s==""?"/":s)}')"

# A record inside a clone is a record that `git clean` deletes and a second clone
# cannot see. Gitignoring it hides the problem rather than fixing it.
case "${DATA}/" in
  "${REPO_ROOT}"/*)
    echo "ERROR: ${DATA} is inside the Symposium repository." >&2
    echo "       The record must live outside the clone — deleting or re-cloning the" >&2
    echo "       repository would destroy it, and it is append-only by design." >&2
    echo "       Pick a directory elsewhere, e.g. ~/symposium-mycommunity/server" >&2
    exit 2 ;;
esac

# Derived from the data directory so two communities on one machine cannot collide on
# the container name or the port, and neither has to be remembered separately.
SLUG="$(basename "$(dirname "${DATA}")")-$(basename "${DATA}")"
SLUG="$(printf '%s' "${SLUG}" | tr -c 'a-zA-Z0-9_.-' '-' | sed 's/^-*//;s/-*$//')"
CONTAINER="${SYMPOSIUM_NDEX_CONTAINER:-symposium-ndex-${SLUG}}"
if [ -n "${SYMPOSIUM_NDEX_PORT:-}" ]; then
  PORT="${SYMPOSIUM_NDEX_PORT}"
else
  # Stable per-directory port in 8080-8179, so the same community always comes back on
  # the same URL and a second one does not silently take the first one's place.
  PORT=$(( 8080 + $(printf '%s' "${DATA}" | cksum | cut -d' ' -f1) % 100 ))
fi

PG_VOL="symposium-pg-${SLUG}"
SOLR_VOL="symposium-solr-${SLUG}"

case "${ACTION}" in
  logs)    exec docker logs -f "${CONTAINER}" ;;
  stop)
    echo "==> stopping ${CONTAINER} (data kept in ${DATA})"
    docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
    exit 0 ;;
  reset)
    echo "This deletes the whole record: every account, every accepted Artifact,"
    echo "every permission grant, under ${DATA}."
    printf "Type the word DELETE to confirm: "
    read -r confirm
    [ "${confirm}" = "DELETE" ] || { echo "not confirmed; nothing changed"; exit 1; }
    docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
    rm -rf "${DATA}"
    # The accounts and the search index live in named volumes, not in ${DATA}. Leaving
    # them behind would give the "new" community the old one's accounts.
    docker volume rm "${PG_VOL}" "${SOLR_VOL}" >/dev/null 2>&1 || true
    echo "==> removed (record, accounts and index)"
    exit 0 ;;
esac

command -v docker >/dev/null || { echo "ERROR: docker is not on PATH" >&2; exit 1; }
docker info >/dev/null 2>&1 || {
  echo "ERROR: the Docker daemon is not responding. Start Docker Desktop (wait for the" >&2
  echo "       whale icon to stop animating) and run this again." >&2; exit 1; }

if [ -n "$(docker ps -q -f "name=^${CONTAINER}$" 2>/dev/null)" ]; then
  echo "==> ${CONTAINER} is already running on ${BIND}:${PORT}"
  exit 0
fi
docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true

# TWO KINDS OF STATE, TWO KINDS OF MOUNT.
#
# The record — the CX2 artifacts under ndex/ — is yours: it stays a bind mount in ${DATA}
# so you can read it, back it up by copying a directory, and move it between machines. NDEx
# runs as root in the container, so the ownership the mount reports does not trouble it.
#
# Postgres and Solr are the engine's own state, and they must be owned by the postgres and
# solr users inside the container. On macOS a bind mount reports every file as 0:0 and
# silently ignores chown, so `initdb` succeeds the first time (it creates PGDATA itself)
# and every RESTART then fails with `data directory has wrong ownership` — a server that
# works until the first reboot and then never starts again, with the record still inside it.
# Docker named volumes keep the ownership that is set on them, so they restart correctly.
# They are per-community, derived from the same slug as the container.
echo "==> data directory: ${DATA}"
for d in ndex/config ndex/data; do
  mkdir -p "${DATA}/${d}"
done
DATA="$(cd "${DATA}" && pwd)"
docker volume create "${PG_VOL}" >/dev/null
docker volume create "${SOLR_VOL}" >/dev/null

echo "==> starting ${CONTAINER} from ${IMAGE}"
docker run -d \
  --name "${CONTAINER}" \
  -p "${BIND}:${PORT}:8080" \
  -v "${DATA}/ndex/config:/apps/ndex/config" \
  -v "${DATA}/ndex/data:/apps/ndex/data" \
  -v "${PG_VOL}:/apps/postgres" \
  -v "${SOLR_VOL}:/apps/solr" \
  "${IMAGE}" \
  --ndex --postgres --solr >/dev/null

# Readiness is the API answering, not the container running. Postgres and Solr come up
# first and NDEx takes tens of seconds after that; a publish attempted in between fails
# in a way that reads like bad credentials.
echo -n "==> waiting for the API"
ELAPSED=0
until curl -sf "http://${BIND}:${PORT}/v2/admin/status" >/dev/null 2>&1; do
  if [ "${ELAPSED}" -ge "${READY_TIMEOUT}" ]; then
    echo
    echo "ERROR: no answer from /v2/admin/status after ${READY_TIMEOUT}s." >&2
    echo "Last 40 lines of the container log:" >&2
    docker logs "${CONTAINER}" 2>&1 | tail -40 >&2
    echo >&2
    echo "If the log ends in 'exec format error', this machine needs Rosetta for" >&2
    echo "linux/amd64 images. If it never mentions NDEx at all, the bind mounts under" >&2
    echo "${DATA} may be left over from an incompatible run:" >&2
    echo "    ./symposium_ndex.sh --data ${DATA} --reset" >&2
    exit 1
  fi
  echo -n "."
  sleep 5
  ELAPSED=$((ELAPSED + 5))
done

echo
echo "==> ready at http://${BIND}:${PORT}"
echo "    record data: ${DATA}"
echo "    container:   ${CONTAINER}"
echo
echo "The port is derived from the data directory, so this community always comes back"
echo "on this URL. Every tool needs to be told it:"
echo
echo "    export SYMPOSIUM_BASE=http://${BIND}:${PORT}"
echo
echo "Next: create the community's accounts."
echo "    python3 bootstrap.py --community community.json"
