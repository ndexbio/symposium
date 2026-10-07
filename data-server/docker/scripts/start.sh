#!/usr/bin/env bash
# start.sh — Symposium Data container startup.
#
# Usage: start.sh [--data-api] [--postgres] [--seaweed]     (no flags: all three)
#
# Phases:
#   0  Version banner
#   1  Parse service flags
#   2  Operational directories under /apps (the single persistent volume)
#   3  First-boot secrets (owner-only files; never in the image, never on stdout)
#   4  PostgreSQL cluster and database (sentinel-guarded)
#   5  SeaweedFS identity (sentinel-guarded)
#   6  Assemble supervisord.conf and exec supervisord (PID 1)
set -euo pipefail

log() { echo "[start.sh] $*"; }

# ── Phase 0: version banner ───────────────────────────────────────────────────────────────────
echo "symposium-data $(/opt/venv/bin/python -c 'import symposium_data; print(symposium_data.version())')"

# ── Phase 1: flags ────────────────────────────────────────────────────────────────────────────
ENABLE_API=false; ENABLE_PG=false; ENABLE_SW=false
[[ $# -eq 0 ]] && set -- --data-api --postgres --seaweed
for flag in "$@"; do
  case "$flag" in
    --data-api) ENABLE_API=true ;;
    --postgres) ENABLE_PG=true ;;
    --seaweed)  ENABLE_SW=true ;;
    *) echo "unknown flag: $flag" >&2; exit 2 ;;
  esac
done
export SYMPOSIUM_DATA_TRUSTED_PROXY="${SYMPOSIUM_DATA_TRUSTED_PROXY:-127.0.0.1}"
# uvicorn workers for the data API and the Symposium API (one process, both prefixes)
export SYMPOSIUM_DATA_WORKERS="${SYMPOSIUM_DATA_WORKERS:-1}"

# ── Phase 2: directories ──────────────────────────────────────────────────────────────────────
mkdir -p /apps/data/config /apps/postgres/config /apps/postgres/data \
         /apps/seaweed/config /apps/seaweed/data
chown -R symposium:symposium /apps/data /apps/seaweed
chown postgres:postgres /apps/postgres/data /apps/postgres/config
chmod 700 /apps/postgres/data

gen() { head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32 || true; }

# ── Phase 3: first-boot secrets ───────────────────────────────────────────────────────────────
CFG=/apps/data/config/service.env
if [[ ! -f "$CFG" ]]; then
  log "first boot: generating internal secrets"
  umask 077
  PG_PASS="$(gen)"; S3_ACCESS="$(gen)"; S3_SECRET="$(gen)"
  printf '%s\n' "$PG_PASS" > /apps/postgres/config/superuser.pw
  cat > "$CFG" <<EOT
DATABASE_URL=postgresql://symposium_data:${PG_PASS}@127.0.0.1:5432/symposium_data
S3_ENDPOINT=http://127.0.0.1:8333
S3_ACCESS_KEY=${S3_ACCESS}
S3_SECRET_KEY=${S3_SECRET}
S3_BUCKET=symposium-data
SERVER_ID=$(cat /proc/sys/kernel/random/uuid)
TOKEN_KEY_FILE=/apps/data/config/token_ed25519.pem
EOT
  /opt/venv/bin/python - <<'EOP'
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

key = Ed25519PrivateKey.generate()
with open("/apps/data/config/token_ed25519.pem", "wb") as fh:
    fh.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                               serialization.NoEncryption()))
EOP
  cat > /apps/seaweed/config/s3.json <<EOT
{"identities": [{"name": "data-service",
  "credentials": [{"accessKey": "${S3_ACCESS}", "secretKey": "${S3_SECRET}"}],
  "actions": ["Admin", "Read", "Write", "List", "Tagging"]}]}
EOT
  umask 022
  chown symposium:symposium "$CFG" /apps/data/config/token_ed25519.pem /apps/seaweed/config/s3.json
  chown postgres:postgres /apps/postgres/config/superuser.pw
  chmod 600 "$CFG" /apps/data/config/token_ed25519.pem /apps/seaweed/config/s3.json \
            /apps/postgres/config/superuser.pw
fi

# The API keys' encryption key (api/DESIGN.md §4.3): 32 random bytes beside the other secrets,
# made on first boot and on the first boot of a server that predates the API.
API_KEY=/apps/data/config/api_key_enc.key
if [[ ! -f "$API_KEY" ]]; then
  log "generating the API keys' encryption key"
  ( umask 077; head -c 32 /dev/urandom > "$API_KEY" )
  chown symposium:symposium "$API_KEY"
  chmod 600 "$API_KEY"
fi
if ! grep -q '^API_KEY_ENC_KEY_FILE=' "$CFG"; then
  echo "API_KEY_ENC_KEY_FILE=$API_KEY" >> "$CFG"
fi

# ── Phase 4: PostgreSQL ───────────────────────────────────────────────────────────────────────
if [[ ! -f /apps/postgres/config/.initialized ]]; then
  log "first boot: initialising PostgreSQL"
  PG_PASS="$(cat /apps/postgres/config/superuser.pw)"
  # UTF-8 explicitly: a bare Debian base has no default locale, and initdb would
  # otherwise create an SQL_ASCII cluster.
  gosu postgres initdb -D /apps/postgres/data --auth-local=peer --auth-host=scram-sha-256 \
    --encoding=UTF8 --locale=C.UTF-8 >/dev/null
  gosu postgres pg_ctl -D /apps/postgres/data -o "-c listen_addresses=127.0.0.1" -w start >/dev/null
  gosu postgres psql -v ON_ERROR_STOP=1 -q -v pw="$PG_PASS" <<'EOSQL'
CREATE ROLE symposium_data LOGIN PASSWORD :'pw';
CREATE DATABASE symposium_data OWNER symposium_data ENCODING 'UTF8' TEMPLATE template0;
EOSQL
  gosu postgres pg_ctl -D /apps/postgres/data -m fast -w stop >/dev/null
  touch /apps/postgres/config/.initialized
fi

# ── Phase 5: SeaweedFS ────────────────────────────────────────────────────────────────────────
if [[ ! -f /apps/seaweed/config/.initialized ]]; then
  touch /apps/seaweed/config/.initialized
  log "first boot: SeaweedFS identity ready"
fi

# ── Phase 6: supervisord ──────────────────────────────────────────────────────────────────────
CONF=/tmp/supervisord.conf
cat /opt/symposium-data/supervisord/header.conf > "$CONF"
$ENABLE_PG  && cat /opt/symposium-data/supervisord/postgres.conf >> "$CONF"
$ENABLE_SW  && cat /opt/symposium-data/supervisord/seaweed.conf  >> "$CONF"
$ENABLE_API && cat /opt/symposium-data/supervisord/data-api.conf >> "$CONF"
log "starting supervisord (api=$ENABLE_API postgres=$ENABLE_PG seaweed=$ENABLE_SW)"
exec supervisord -c "$CONF"
