#!/bin/bash
# Promote the currently-tested image (ccct-web:test) to production
# (ccct-web:prod) on vrftools.com. Pre-flight checks → summary →
# typed PROMOTE confirmation → previous-image backup → 10-minute
# countdown signal → container swap → post-check.
#
# To roll back, see the rollback command printed at the end.
set -e

# ---- CONSTANTS -------------------------------------------------------------
TEST_IMAGE="ccct-web:test"
TEST_CONTAINER="ccct-web-test"
PROD_IMAGE="ccct-web:prod"
PROD_CONTAINER="ccct-web-prod"
PROD_SIGNAL_DIR="$HOME/.ccct/signals/prod"
SIGNAL_FILE="$PROD_SIGNAL_DIR/restart.json"
TEST_HEALTH_URL="https://codetest.vrftools.com/status"
PROD_HEALTH_URL="https://vrftools.com/status"

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

# ---- HELPERS ---------------------------------------------------------------
die()  { echo "ERROR: $*" >&2; exit 1; }
note() { echo; echo "==> $*"; }
write_signal() {  # arg: minutes from now
  local mins="$1"
  local restart_at
  restart_at=$(date -u -d "+${mins} minutes" +%Y-%m-%dT%H:%M:%SZ)
  mkdir -p "$PROD_SIGNAL_DIR"
  printf '{"restart_at": "%s"}\n' "$restart_at" > "$SIGNAL_FILE"
  echo "    signal: restart_at=$restart_at  (T-${mins}min)"
}
clear_signal() {
  echo '{}' > "$SIGNAL_FILE"
}

# ---- 1. PRE-FLIGHT CHECKS --------------------------------------------------
note "1/7  Pre-flight checks"

docker image inspect "$TEST_IMAGE" >/dev/null 2>&1 \
  || die "Test image '$TEST_IMAGE' not found. Run ./deploy-codetest.sh first."

docker inspect -f '{{.State.Running}}' "$TEST_CONTAINER" 2>/dev/null | grep -q true \
  || die "Test container '$TEST_CONTAINER' is not running."

test_status=$(curl -fsS "$TEST_HEALTH_URL" 2>/dev/null || echo "")
case "$test_status" in
  *'"ok": true'*|*'"ok":true'*) echo "    codetest /status: ok" ;;
  *) die "codetest /status did not return ok=true. Got: $test_status" ;;
esac

# ---- 2. SUMMARY ------------------------------------------------------------
note "2/7  Summary"

test_sha=$(docker image inspect "$TEST_IMAGE" -f '{{.Id}}' | cut -c1-19)
echo "    test image:  $TEST_IMAGE   ($test_sha)"

if docker image inspect "$PROD_IMAGE" >/dev/null 2>&1; then
  prod_sha=$(docker image inspect "$PROD_IMAGE" -f '{{.Id}}' | cut -c1-19)
  echo "    prod image:  $PROD_IMAGE   ($prod_sha)"
  if [ "$test_sha" = "$prod_sha" ]; then
    echo "    NOTE: test and prod image SHAs are identical — nothing to promote."
    echo "    Aborting (no-op)."
    exit 0
  fi
else
  echo "    prod image:  (none yet — first-ever promotion)"
fi

if [ -d "$REPO_DIR/.git" ]; then
  git_sha=$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo "?")
  git_msg=$(git -C "$REPO_DIR" log -1 --pretty=%s 2>/dev/null || echo "?")
  echo "    git HEAD:    $git_sha   $git_msg"
fi

# ---- 3. TYPED CONFIRMATION -------------------------------------------------
note "3/7  Confirmation"
echo "    This will replace ccct-web-prod after a 10-minute warning window."
echo "    Active users on vrftools.com will see a countdown banner and have"
echo "    time to save their work before the restart."
echo
read -r -p "    Type 'PROMOTE' (uppercase) to continue, anything else to abort: " confirm
[ "$confirm" = "PROMOTE" ] || die "Aborted (got '$confirm')."

# ---- 4. BACKUP CURRENT PROD IMAGE ------------------------------------------
note "4/7  Backup current prod image"

if docker image inspect "$PROD_IMAGE" >/dev/null 2>&1; then
  ts=$(date -u +%Y%m%dT%H%M%S)
  backup_tag="ccct-web:prod-prev-${ts}"
  docker tag "$PROD_IMAGE" "$backup_tag"
  echo "    backup: $backup_tag"
else
  backup_tag=""
  echo "    no prior prod image to back up — first-ever promotion"
fi

# ---- 5. COUNTDOWN SIGNAL SEQUENCE (polled — skips if idle) ----------------
note "5/7  Countdown — checking for active sessions via Umami"

mkdir -p "$PROD_SIGNAL_DIR"
write_signal 10

# Poll umami-db at each countdown tick.  If zero active sessions are
# found, skip the remaining wait and promote immediately.  Falls back
# to the full 10-minute countdown if the DB query fails for any reason.
remaining="10 5 2"
skipped=false
for wait_min in $remaining; do
  active=$(docker exec umami-db psql -U umami -d umami -tAc \
    "SELECT COUNT(DISTINCT we.session_id)
     FROM website_event we
     JOIN website w ON w.website_id = we.website_id
     WHERE w.domain = 'vrftools.com'
       AND w.deleted_at IS NULL
       AND we.created_at > NOW() - INTERVAL '30 minutes'" 2>/dev/null || echo "?")
  active=${active:-0}

  if [ "$active" = "0" ]; then
    echo "    No active sessions — skipping remaining countdown."
    skipped=true
    break
  fi
  echo "    $active active session(s) — waiting $wait_min min..."
  sleep $((wait_min * 60))
done

if [ "$skipped" = false ]; then
  echo "    Countdown complete (no idle window detected)."
fi

# ---- 6. PROMOTE ------------------------------------------------------------
note "6/7  Promote: tag $TEST_IMAGE -> $PROD_IMAGE and swap container"

docker tag "$TEST_IMAGE" "$PROD_IMAGE"

docker stop "$PROD_CONTAINER" 2>/dev/null || true
docker rm   "$PROD_CONTAINER" 2>/dev/null || true

docker run -d \
  --name "$PROD_CONTAINER" \
  --network vrftools-net \
  -p 127.0.0.1:5050:5050 \
  --restart unless-stopped \
  -e PYTHONUNBUFFERED=1 \
  -e APP_ENV=prod \
  -e SECRET_KEY="${PROD_SECRET_KEY:?PROD_SECRET_KEY env var must be set}" \
  -e AGENT_API_KEY="${AGENT_API_KEY:-}" \
  -v "$PROD_SIGNAL_DIR":/app/signals \
  "$PROD_IMAGE"

# Re-attach to hermes-net so the Hermes agent can reach this container after rebuild
docker network connect hermes-net "$PROD_CONTAINER" 2>/dev/null || true

clear_signal

# Host nginx proxies to a stable localhost port (127.0.0.1:5050), so no nginx
# reload is needed when ccct-web-prod is recreated.
sleep 1

# ---- 7. POST-CHECK ---------------------------------------------------------
note "7/7  Post-check"

sleep 5
prod_status=$(curl -fsS "$PROD_HEALTH_URL" 2>/dev/null || echo "")
case "$prod_status" in
  *'"ok": true'*|*'"ok":true'*) echo "    vrftools.com /status: ok" ;;
  *) die "POST-PROMOTION CHECK FAILED. /status did not return ok=true. Got: $prod_status. Consider rolling back (see below)." ;;
esac

new_prod_sha=$(docker image inspect "$PROD_IMAGE" -f '{{.Id}}' | cut -c1-19)
echo
echo "============================================================"
echo " Promotion complete."
echo " New prod image: $PROD_IMAGE  ($new_prod_sha)"
if [ -n "$backup_tag" ]; then
  echo
  echo " Rollback command (if needed):"
  echo "   docker tag $backup_tag $PROD_IMAGE \\"
  echo "   && docker stop $PROD_CONTAINER \\"
  echo "   && docker rm $PROD_CONTAINER \\"
  echo "   && docker run -d --name $PROD_CONTAINER --network vrftools-net \\"
  echo "        --restart unless-stopped -e APP_ENV=prod \\"
  echo "        -e SECRET_KEY=\"\$PROD_SECRET_KEY\" \\"
  echo "        -v $PROD_SIGNAL_DIR:/app/signals $PROD_IMAGE"
fi
echo "============================================================"
