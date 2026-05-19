# DEPLOY.md — tranesubishi.com Deployment

VRFTools refactor app deployed at https://tranesubishi.com.

## Architecture

```
                  ┌────────────────────────────┐
                  │     Nginx (tranesubishi)     │
                  │  /etc/nginx/sites-available/ │
                  │       tranesubishi           │
                  └──────────┬─────────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
         / (Flask)      /hearth        /static
         127.0.0.1:5052  127.0.0.1:5055  (future)
              │              │
    ┌─────────┴─────────┐    │
    │ vrf-tools-        │    │
    │ tranesubishi      │    │
    │ (Flask :5050)     │    │
    └───────────────────┘    │
                    ┌───────┴──────────┐
                    │ family-tasks     │
                    │ (Hearth :5050)   │
                    └──────────────────┘
```

## Container Details

| Field | Value |
|---|---|
| **Container name** | `vrf-tools-tranesubishi` |
| **Image** | `vrf-tools:tranesubishi` |
| **Port mapping** | `127.0.0.1:5052 → container:5050` |
| **Internal port** | `5050` (gunicorn) |
| **Network** | `vrftools-net` |
| **Restart policy** | `unless-stopped` |
| **Signals volume** | `~/.vrf-tools/signals/tranesubishi:/app/signals` |

## Other Running Containers (for reference)

| Container | Port | Site |
|---|---|---|
| `ccct-web-prod` | 127.0.0.1:5050 | vrftools.com |
| `ccct-web-test` | 127.0.0.1:5051 | codetest.vrftools.com |
| `vrf-tools-tranesubishi` | 127.0.0.1:5052 | tranesubishi.com |
| `family-tasks` | 0.0.0.0:5055 | tranesubishi.com/hearth |
| `umami` | 127.0.0.1:3000 | analytics.vrftools.com |

## Nginx Config

- **File**: `/etc/nginx/sites-available/tranesubishi` (symlinked in `/etc/nginx/sites-enabled/`)
- **SSL**: Let's Encrypt via certbot, auto-renewing
- **Cert path**: `/etc/letsencrypt/live/tranesubishi.com/`
- **Proxy for `/`**: `http://127.0.0.1:5052` (Flask app)
- **Proxy for `/hearth`**: `http://127.0.0.1:5055` (family-tasks container)

## Deploy / Rebuild

```bash
cd /home/claudecode/vrf-tools
./deploy-tranesubishi.sh
```

What it does:
1. Builds `vrf-tools:tranesubishi` Docker image from current repo state
2. Stops and removes the old `vrf-tools-tranesubishi` container
3. Starts a new container on `127.0.0.1:5052`
4. Waits for gunicorn to start
5. Verifies `https://tranesubishi.com/status` returns `ok: true`
6. Verifies `https://codetest.vrftools.com/status` is still healthy (guard)

No nginx reload is needed on rebuild — the proxy points to a stable localhost port.

## Nginx Config Update

If the nginx config needs updating:

```bash
# Edit the config
sudo nano /etc/nginx/sites-available/tranesubishi

# Test syntax
sudo nginx -t

# Apply
sudo systemctl reload nginx
```

## TLS Certificate

- **Obtained via**: `sudo certbot --nginx -d tranesubishi.com -d www.tranesubishi.com`
- **Auto-renewal**: certbot systemd timer (runs twice daily)
- **Manual renewal**: `sudo certbot renew --dry-run` (test), `sudo certbot renew` (force)
- **Cert files**: `/etc/letsencrypt/live/tranesubishi.com/{fullchain.pem,privkey.pem}`

## Rollback

To roll back to a previous image:

```bash
# If you tagged a backup:
docker tag vrf-tools:tranesubishi-prev-YYYYMMDDTHHMMSS vrf-tools:tranesubishi

# Or rebuild from a known-good git commit:
cd /home/claudecode/vrf-tools
git checkout <known-good-sha>
./deploy-tranesubishi.sh
git checkout main  # return to main
```

## Docker Network Membership

The container joins `vrftools-net` so it can reach:
- `umami` (analytics)
- `umami-db` (Postgres for analytics)
- Other containers on the same network

No other networks are attached by default.

## Logs

```bash
# Real-time logs
sg docker -c "docker logs -f vrf-tools-tranesubishi"

# Last 50 lines
sg docker -c "docker logs vrf-tools-tranesubishi --tail 50"

# Inspect container
sg docker -c "docker inspect vrf-tools-tranesubishi"
```

## Health Check

The Dockerfile includes a HEALTHCHECK that queries `/status` every 30 seconds.
`docker ps` will show `(healthy)` when the app is responding correctly.

Manual check:
```bash
curl -fsS https://tranesubishi.com/status
# Expected: {"env":"production","ok":true,...}
```

## Environment Variables

| Variable | Purpose |
|---|---|
| `PYTHONUNBUFFERED=1` | Unbuffered Python output |
| `APP_ENV=production` | App environment (used by Flask) |
| `SECRET_KEY` | Flask session signing key (from `$TRANESUBISHI_SECRET_KEY` env) |

## Monitoring

Both sites are verified after every deploy:
- `https://tranesubishi.com/status` → must return `"ok": true`
- `https://codetest.vrftools.com/status` → must return `"ok": true` (guard)
