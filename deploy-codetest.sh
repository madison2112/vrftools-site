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
  --network container:tranesubishi \
  --restart unless-stopped \
  -e PYTHONUNBUFFERED=1 \
  "$IMAGE" \
  gunicorn --bind 127.0.0.1:5050 --workers 2 --timeout 60 app:app

echo "Waiting for app to start..."
sleep 3
docker logs "$CONTAINER" --tail 5

echo "Done. Testing https://codetest.vrftools.com/ ..."
code=$(curl -s -o /dev/null -w "%{http_code}" https://codetest.vrftools.com/)
echo "HTTP $code"

# NOTE: if tranesubishi nginx container is ever restarted, run:
#   docker restart ccct-web
# to reattach to its network namespace.
