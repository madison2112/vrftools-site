#!/bin/bash
# Deploy Central Controller Config Tools to codetest.vrftools.com (TEST ONLY).
#
# This script can ONLY build/run the test container (ccct-web-test) on the
# test image (ccct-web:test). It is physically incapable of touching prod —
# the guard below will hard-exit on any prod-shaped name. To promote a tested
# build to vrftools.com, use ./promote-to-prod.sh instead.
set -e

# ---- HARD-CODED TEST RESOURCE NAMES ----------------------------------------
# Deliberately hard-coded (not env-overridable) so a typo can't repurpose this
# script to touch prod.
IMAGE="ccct-web:test"
CONTAINER="ccct-web-test"
SIGNAL_DIR="$HOME/.ccct/signals/test"

# ---- DEFENSIVE GUARD -------------------------------------------------------
# Belt-and-suspenders: if any future edit accidentally introduces a prod-
# shaped value into IMAGE or CONTAINER, refuse to run.
case "$IMAGE" in *":prod"*|*":latest"*) echo "ERROR: deploy-codetest.sh refuses image '$IMAGE'." >&2; exit 1 ;; esac
case "$CONTAINER" in *"-prod"*|"ccct-web") echo "ERROR: deploy-codetest.sh refuses container '$CONTAINER'." >&2; exit 1 ;; esac

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
  -p 127.0.0.1:5051:5050 \
  --restart unless-stopped \
  -e PYTHONUNBUFFERED=1 \
  -e APP_ENV=test \
  -e SECRET_KEY="${TEST_SECRET_KEY:-codetest-hmac-key-change-before-prod}" \
  -e AGENT_API_KEY="${AGENT_API_KEY:-}" \
  -v "$SIGNAL_DIR":/app/signals \
  "$IMAGE"

# Re-attach to hermes-net so the Hermes agent can reach this container after rebuild
docker network connect hermes-net "$CONTAINER" 2>/dev/null || true

echo "Waiting for app to start..."
sleep 3
docker logs "$CONTAINER" --tail 5

# Host nginx proxies to a stable localhost port (127.0.0.1:5051), so no nginx
# reload is needed when the test container is recreated.
sleep 1

echo "Done. Testing https://codetest.vrftools.com/status ..."
status_json=$(curl -fsS https://codetest.vrftools.com/status || echo "")
echo "$status_json"
case "$status_json" in
  *'"ok": true'*|*'"ok":true'*) echo "OK — codetest is live and responding." ;;
  *) echo "WARNING: codetest /status did not return ok=true. Check 'docker logs $CONTAINER'."; exit 2 ;;
esac
