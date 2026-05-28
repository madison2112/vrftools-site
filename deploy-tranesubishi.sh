#!/bin/bash
# Deploy VRFTools refactor app to tranesubishi.com.
#
# This script builds and runs the vrf-tools-tranesubishi container. It is
# completely isolated from the codetest.vrftools.com / vrftools.com deployment
# (which lives in the central-control-database-tools repo).  The guard below
# hard-exits on any ccct-* shaped name so a copy-paste accident can't touch prod.
set -e

# ---- SMTP CREDENTIALS (local, never committed) ----------------------------
# If ~/.vrf-tools/secrets/smtp.env exists, source it so MAIL_USERNAME/MAIL_PASSWORD
# (and other MAIL_* overrides) are available to docker run -e. File should be
# chmod 600 and located OUTSIDE any git repo. Silently no-op if absent.
_SMTP_ENV_FILE="$HOME/.vrf-tools/secrets/smtp.env"
if [ -f "$_SMTP_ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$_SMTP_ENV_FILE"
  set +a
fi

# ---- HARD-CODED RESOURCE NAMES --------------------------------------------
# Deliberately hard-coded so a typo can't repurpose this script to touch
# the live codetest/vrftools deployment.
IMAGE="vrf-tools:tranesubishi"
CONTAINER="vrf-tools-tranesubishi"
SIGNAL_DIR="$HOME/.vrf-tools/signals/tranesubishi"

# ---- DEFENSIVE GUARD ------------------------------------------------------
case "$IMAGE" in *"ccct"*|*"codetest"*|*"vrftools.com"*)
  echo "ERROR: deploy-tranesubishi.sh refuses image '$IMAGE'." >&2
  exit 1
esac
case "$CONTAINER" in *"ccct"*|*"codetest"*|*"prod"*)
  echo "ERROR: deploy-tranesubishi.sh refuses container '$CONTAINER'." >&2
  exit 1
esac
HOST_PORT="5052"
case "$HOST_PORT" in 5050|5051)
  echo "ERROR: deploy-tranesubishi.sh refuses host port $HOST_PORT (reserved for prod/codetest)." >&2
  exit 1
esac

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

mkdir -p "$SIGNAL_DIR"

echo "Building image $IMAGE..."
docker build -t "$IMAGE" .

echo "Replacing container $CONTAINER..."
docker stop "$CONTAINER" 2>/dev/null || true
docker rm   "$CONTAINER" 2>/dev/null || true

docker run -d \
  --name "$CONTAINER" \
  --network vrftools-net \
  -p "127.0.0.1:${HOST_PORT}:5050" \
  --restart unless-stopped \
  -e PYTHONUNBUFFERED=1 \
  -e APP_ENV=production \
  -e SECRET_KEY="${TRANESUBISHI_SECRET_KEY:-tranesubishi-hmac-key-change-before-going-live}" \
  -e MAIL_USERNAME="${MAIL_USERNAME:-}" \
  -e MAIL_PASSWORD="${MAIL_PASSWORD:-}" \
  -e MAIL_FROM="${MAIL_FROM:-support@vrftools.com}" \
  -e MAIL_TO="${MAIL_TO:-support@vrftools.com}" \
  -e MAIL_SMTP_HOST="${MAIL_SMTP_HOST:-smtp.hostinger.com}" \
  -e MAIL_SMTP_PORT="${MAIL_SMTP_PORT:-465}" \
  -v "$SIGNAL_DIR":/app/signals \
  "$IMAGE"

echo "Waiting for app to start..."
sleep 3
docker logs "$CONTAINER" --tail 5

sleep 1

echo "Done. Testing https://tranesubishi.com/status ..."
status_json=$(curl -fsS https://tranesubishi.com/status || echo "")
echo "$status_json"
case "$status_json" in
  *'"ok": true'*|*'"ok":true'*) echo "OK — tranesubishi is live and responding." ;;
  *) echo "WARNING: tranesubishi /status did not return ok=true. Check 'docker logs $CONTAINER'."; exit 2 ;;
esac

echo ""
echo "Verifying codetest is NOT affected..."
codetest_status=$(curl -fsS https://codetest.vrftools.com/status || echo "")
case "$codetest_status" in
  *'"ok": true'*|*'"ok":true'*) echo "OK — codetest.vrftools.com is still healthy." ;;
  *) echo "WARNING: codetest.vrftools.com /status did not return ok=true!"; exit 3 ;;
esac
