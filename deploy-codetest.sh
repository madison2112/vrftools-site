#!/bin/bash
# Deploy Central Controller Config Tools to codetest.vrftools.com
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
IMAGE="ccct-web:latest"
CONTAINER="ccct-web"

cd "$REPO_DIR"

echo "Building image..."
docker build -t "$IMAGE" .

echo "Replacing container..."
docker stop "$CONTAINER" 2>/dev/null || true
docker rm   "$CONTAINER" 2>/dev/null || true

docker run -d \
  --name "$CONTAINER" \
  --network vrftools-net \
  --restart unless-stopped \
  -e PYTHONUNBUFFERED=1 \
  -e SECRET_KEY="${SECRET_KEY:-codetest-hmac-key-change-before-prod}" \
  "$IMAGE" \
  gunicorn --bind 0.0.0.0:5050 --workers 2 --timeout 60 app:app

echo "Waiting for app to start..."
sleep 3
docker logs "$CONTAINER" --tail 5

echo "Done. Testing https://codetest.vrftools.com/ ..."
code=$(curl -s -o /dev/null -w "%{http_code}" https://codetest.vrftools.com/)
echo "HTTP $code"

# All containers use the vrftools-net bridge network, so restarting
# tranesubishi or any backend is fully independent of the others.
