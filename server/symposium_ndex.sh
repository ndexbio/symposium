#!/usr/bin/env bash
# symposium_ndex.sh — run the community's record server in a container.
#
#   ./symposium_ndex.sh              start it (idempotent; safe to re-run)
#   ./symposium_ndex.sh --logs       follow the container log
#   ./symposium_ndex.sh --stop       stop and remove the container, keep the data
#   ./symposium_ndex.sh --reset      stop, remove, AND DELETE ALL RECORD DATA
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
CONTAINER="${SYMPOSIUM_NDEX_CONTAINER:-symposium-ndex}"
PORT="${SYMPOSIUM_NDEX_PORT:-8080}"
BIND="${SYMPOSIUM_NDEX_BIND:-127.0.0.1}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${SYMPOSIUM_NDEX_DATA:-${SCRIPT_DIR}/data}"
READY_TIMEOUT="${SYMPOSIUM_NDEX_TIMEOUT:-180}"

usage() { sed -n '2,24p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0; }

case "${1:-start}" in
  -h|--help) usage ;;
  --logs)    exec docker logs -f "${CONTAINER}" ;;
  --stop)
    echo "==> stopping ${CONTAINER} (data kept in ${DATA})"
    docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
    exit 0 ;;
  --reset)
    echo "This deletes the whole record: every account, every accepted Artifact,"
    echo "every permission grant, under ${DATA}."
    printf "Type the word DELETE to confirm: "
    read -r confirm
    [ "${confirm}" = "DELETE" ] || { echo "not confirmed; nothing changed"; exit 1; }
    docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
    rm -rf "${DATA}"
    echo "==> removed"
    exit 0 ;;
  start) ;;
  *) echo "unknown option: $1" >&2; exit 2 ;;
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

# One bind mount per service, at the paths the image expects under /apps, so the record
# survives the container being removed and can be backed up by copying a directory.
echo "==> data directory: ${DATA}"
for d in ndex/config ndex/data postgres/config postgres/data solr/config solr/data; do
  mkdir -p "${DATA}/${d}"
done

echo "==> starting ${CONTAINER} from ${IMAGE}"
docker run -d \
  --name "${CONTAINER}" \
  -p "${BIND}:${PORT}:8080" \
  -v "${DATA}/ndex/config:/apps/ndex/config" \
  -v "${DATA}/ndex/data:/apps/ndex/data" \
  -v "${DATA}/postgres/config:/apps/postgres/config" \
  -v "${DATA}/postgres/data:/apps/postgres/data" \
  -v "${DATA}/solr/config:/apps/solr/config" \
  -v "${DATA}/solr/data:/apps/solr/data" \
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
    echo "${DATA} may be left over from an incompatible run — ./symposium_ndex.sh --reset" >&2
    exit 1
  fi
  echo -n "."
  sleep 5
  ELAPSED=$((ELAPSED + 5))
done

echo
echo "==> ready at http://${BIND}:${PORT}"
echo
echo "Next: create the community's accounts."
echo "    python3 bootstrap.py --community community.json"
