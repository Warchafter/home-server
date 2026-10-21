# Deployment Guide

## First-Time Setup

```bash
# 1. Clone the repo on your HP server
git clone https://github.com/Warchafter/home-server.git
cd home-server

# 2. Run the bootstrap script
bash scripts/setup.sh

# 3. Log out and back in (for Docker group permissions)
exit
# SSH back in, then:
cd home-server

# 4. Review and edit your config
nano .env

# 5. Start everything
docker compose up -d

# 6. IMPORTANT: Complete AdGuard setup wizard at http://SERVER_IP:3000
#    - Set an admin username and password
#    - Choose upstream DNS (e.g., 1.1.1.1)
#    After the wizard, access AdGuard normally at http://SERVER_IP:8091
```

## Common Operations

### Check status
```bash
docker compose ps
```

### View logs
```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f caddy
```

### Restart a single service
```bash
docker compose restart caddy
```

### Update after changing config files
```bash
# Pull latest config from git
git pull

# Recreate containers with updated compose files
docker compose up -d

# If you changed caddy/Caddyfile (not caddy.yaml), reload Caddy separately:
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
```

### Update container images
```bash
# Since images are pinned to specific versions in the compose files,
# update the version tags in stacks/*.yaml first, then:
docker compose pull

# Recreate containers with new images
docker compose up -d
```

### Stop everything
```bash
docker compose down
```

### Recreate all containers (keeps data)
```bash
docker compose down
docker compose up -d --force-recreate
```

**WARNING:** Never run `docker compose down -v` — the `-v` flag destroys all
persistent data (AdGuard config, Uptime Kuma monitors, Caddy certificates).

## Alerting

Uptime Kuma watches the HTTP services but needs a notification channel to be
useful: Settings > Notifications > add Telegram or Discord, then enable it on
every monitor. Both are outbound webhooks and work from a LAN-only server.

Disk space and crash loops are watched by `scripts/alert-check.py`, which runs
from cron on the host and does not depend on Prometheus (Prometheus is the
first thing a full disk kills). Set `ALERT_DISCORD_WEBHOOK` and/or the
`ALERT_TELEGRAM_*` values in `.env`, then:
```bash
python3 scripts/alert-check.py --test     # confirm delivery
python3 scripts/alert-check.py --print    # see what it would report right now
crontab -e                                 # add:
# */10 * * * * /usr/bin/python3 /home/wachacha/home-server/scripts/alert-check.py >> /var/tmp/alert-check.log 2>&1
```
It alerts once per new problem, reminds every 24 h while it persists, and
sends a resolved message when it clears.

## Backups

**Vaultwarden (automated):** The `vaultwarden-backup` container runs daily
at 2:00 AM, creating compressed SQLite backups in the `vaultwarden_backup`
volume and keeping the last 30 days. Check backup status:
```bash
docker compose logs vaultwarden-backup
```

**Everything else (manual):** Back up these critical items regularly:
- This Git repo (it's your entire server config)
- The `.env` file (not in git — copy it somewhere safe)
- Docker volumes (Phase 1): `adguard_conf`, `adguard_work`, `uptime_kuma_data`, `caddy_data`, `caddy_config`
- Docker volumes (Phase 2): `jellyfin_config`, `sonarr_config`, `radarr_config`, `prowlarr_config`, `qbittorrent_config`, `homeassistant_config`, `syncthing_config`
- Bind mount directories: `MEDIA_PATH` (media library), `SYNCTHING_DATA_PATH` (synced files)

To dump a volume to a tarball:
```bash
docker run --rm -v adguard_conf:/data -v $(pwd):/backup busybox \
  tar czf /backup/adguard_conf_backup.tar.gz -C /data .
```

## Runbooks

### Disk full / Sonarr, Radarr, Prowlarr, Bazarr crash-looping

Signature: those four return 502 and sit in `health: starting` forever while
everything read-mostly stays up; Prometheus logs `write to WAL ... no space
left on device`; Grafana logs `database or disk is full`. `df` can read 97%
and still mean zero: ext4 reserves ~5% for root, and the containers run
unprivileged. Running SQLite apps survive a full disk and die at their NEXT
restart, so a deploy days later can look like the deploy broke them.

1. Find the space. Deleting in Sonarr/Radarr only removes the library hardlink;
   the qBittorrent copy keeps the bytes. Files with a single link under
   `downloads/complete` exist nowhere else:
   ```bash
   sudo find /srv/media/downloads/complete -type f -links 1 -size +100M -printf '%s\t%p\n' \
     | awk -F'\t' '{s+=$1; n++} END {printf "%d files, %.1f GB reclaimable\n", n, s/1e9}'
   ```
2. Reclaim it: delete those files, restart qBittorrent so it notices, then in
   its web UI filter **Errored**, select all, Remove.
   ```bash
   sudo find /srv/media/downloads/complete -type f -links 1 -size +100M -delete
   sudo find /srv/media/downloads/complete -mindepth 1 -type d -empty -delete
   docker compose restart qbittorrent
   ```
3. autoheal brings the four *arr containers back within ~2 minutes. Prometheus
   resumes on its own; restart it only if Grafana stays blank.

To stop this recurring: qBittorrent > Options > BitTorrent > Seeding Limits
with the action "Remove torrent and its files" (the library hardlink survives),
and Sonarr/Radarr > Settings > Download Clients > "Remove Completed".

### Jellyfin: deleted shows linger, new shows never appear

Jellyfin 10.11 bug (fixed only in 12.0): removing an item can fail with
`UNIQUE constraint failed: UserData.ItemId, UserData.UserId, UserData.CustomDataKey`
and every library refresh aborts at that point. Check:
```bash
docker logs jellyfin --since 1h 2>&1 | grep -c 'UNIQUE constraint'
```
Fix with the bundled script (dry run first, then `--delete`):
```bash
docker compose stop jellyfin
sudo python3 scripts/jellyfin-prune-stale-userdata.py
sudo python3 scripts/jellyfin-prune-stale-userdata.py --delete
docker compose start jellyfin
# Jellyfin > Dashboard > Libraries > Scan All Libraries
```

### Containers can't resolve DNS (SERVFAIL from 127.0.0.11)

Signature: Syncthing logs `lookup relays.syncthing.net on 127.0.0.11:53: server
misbehaving`; Jellyfin and the *arrs log `Resource temporarily unavailable
(host:443)` (that is errno EAGAIN from getaddrinfo, a DNS failure, not a
connection failure). Cause so far has always been Tailscale putting
100.100.100.100 into the host's resolv.conf:
```bash
resolvectl status | head -5          # Global "Current DNS Server: 100.100.100.100" = regressed
sudo tailscale set --accept-dns=false
docker compose up -d                 # containers read DNS config at (re)create time
```
The outbound-calling stacks pin `dns:` to `CONTAINER_DNS` + 1.1.1.1 so this
can no longer reach them; the commands above are for the host itself.

