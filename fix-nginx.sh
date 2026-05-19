#!/bin/bash
# Apply the correct nginx config for tranesubishi.com
# RUN WITH: sudo bash fix-nginx.sh
set -e

echo "=== Backing up current config ==="
cp /etc/nginx/sites-available/tranesubishi /etc/nginx/sites-available/tranesubishi.bak.$(date +%Y%m%d-%H%M%S)

echo "=== Installing correct config (proxy_pass to :5052) ==="
cp nginx/tranesubishi.nginx.conf /etc/nginx/sites-available/tranesubishi

echo "=== Testing nginx syntax ==="
nginx -t

echo "=== Reloading nginx ==="
systemctl reload nginx

echo ""
echo "=== Verifying tranesubishi.com ==="
curl -fsS https://tranesubishi.com/status || echo "WARNING: /status check failed"
echo ""

echo "=== Verifying codetest.vrftools.com (guard) ==="
curl -fsS https://codetest.vrftools.com/status || echo "WARNING: codetest check failed"
echo ""

echo "=== Done. Both sites should be healthy. ==="
