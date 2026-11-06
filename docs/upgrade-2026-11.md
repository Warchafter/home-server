# November 2026 upgrade & hardening rollout

This brings every image current, adds Backrest / Diun / Cleanuparr / Seerr,
moves autoheal off the raw Docker socket, and locks things down. Do it in
waves, and **do not run a bare `docker compose up -d` after `git pull`**: that
would start every one-way migration at once, with autoheal free to kill them
mid-way. Each wave below names the services it touches.

Run everything on the server from `~/home-server`.

| Wave | What | Risk |
|---|---|---|
| 0 | Pull, `.env`, pre-upgrade copies | none |
| 1 | autoheal proxy, new services, Caddy/Homepage/MCP, monitoring, low-risk apps, VPN pair | low; rollback = old tag |
| 2 | Backrest configured, first offsite snapshot | none |
| 3 | One-way migrations, one at a time, autoheal stopped: Uptime Kuma → Home Assistant → Syncthing → Jellyfin | **one-way**; rollback = restore the wave 0 copy |
| 4 | Host + Tailscale hardening (docs/security-hardening.md) | SSH lockout if done out of order |
| 5 | App settings: disk guards, Cleanuparr rules, HEVC test | none |

---

## Wave 0 — prepare

```bash
cd ~/home-server && git pull
df -h /                       # need ~15 GB free: new images + Syncthing's migration (up to 8x its DB)
```

Add to `.env` (see `.env.example` for comments). The first two are
**required**: every `docker compose` command refuses to run until they're set.
```bash
MCP_AUTH_TOKEN=<openssl rand -hex 32>
VAULTWARDEN_BACKUP_ZIP_PASSWORD=<openssl rand -base64 24>   # also save it in Vaultwarden
TAILSCALE_IP=<tailscale ip -4>
CONTAINER_DNS=<SERVER_IP>                                    # containers resolve via AdGuard
# DIUN_NOTIF_DISCORD_WEBHOOKURL=...   and/or DIUN_NOTIF_TELEGRAM_TOKEN / _CHATIDS
# BACKREST_B2_KEY_ID=...  BACKREST_B2_APP_KEY=...   (docs/backups.md §1 — key WITHOUT deleteFiles)
```
```bash
chmod 600 .env vaultwarden/ssl/key.pem
docker compose config --quiet && echo "compose config OK"
```
**Check `HOMEPAGE_ALLOWED_HOSTS` in `.env`:** delete the line if it is `*` or the
old CIDR value (`192.168.0.0/24,...`). Homepage v2 matches exact host strings,
and the default now covers SERVER_IP + TAILSCALE_IP.

Pre-upgrade copies of the volumes that migrate one-way: Grafana in wave 1, the
rest in wave 3. Each container is stopped for its copy, so its database is
consistent. `--volumes-from` copies whatever the volume is actually named:
```bash
sudo install -d -m 700 /srv/pre-upgrade-2026-11   # holds tokens/keys/DBs: root-only
docker compose stop autoheal          # don't let it "heal" the stopped containers
snap() {  # <container> <path inside it> [tar options]
  docker stop "$1" &&
  docker run --rm --volumes-from "$1":ro -v /srv/pre-upgrade-2026-11:/b alpine tar czf "/b/$1.tgz" $3 "$2"
  docker start "$1"
}
snap uptime-kuma   /app/data
snap syncthing     /var/syncthing
snap grafana       /var/lib/grafana
snap homeassistant /config
snap jellyfin      /config "--exclude=config/metadata"   # artwork re-downloads
docker compose start autoheal
ls -lh /srv/pre-upgrade-2026-11
```

## Wave 1 — low-risk, no one-way migrations

**1a. Validate the new Caddyfile with the new image before touching Caddy:**
```bash
docker run --rm -v "$PWD/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2.11.9 caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

**1b. autoheal off the raw socket, then prove the proxy refuses everything else:**
```bash
docker compose up -d autoheal-proxy autoheal
docker logs autoheal --tail 5          # "Monitoring containers for unhealthy status"
docker logs autoheal-proxy --tail 5
# must be 403 (create blocked) and 200 (list allowed):
docker run --rm -v autoheal_sock:/s curlimages/curl -s -o /dev/null -w '%{http_code}\n' --unix-socket /s/docker.sock -X POST http://localhost/containers/create
docker run --rm -v autoheal_sock:/s curlimages/curl -s -o /dev/null -w '%{http_code}\n' --unix-socket /s/docker.sock http://localhost/containers/json
```

**1c. New services.** Cleanuparr and Seerr run as UID 1000, and fresh named volumes are root-owned:
```bash
docker volume create cleanuparr_config && docker volume create seerr_config
sudo chown 1000:1000 /var/lib/docker/volumes/cleanuparr_config/_data /var/lib/docker/volumes/seerr_config/_data
docker compose up -d backrest cleanuparr seerr
docker compose ps backrest cleanuparr seerr
```
**Right away**, finish each first-run setup, because each one is open until you do:
Backrest via SSH tunnel (docs/backups.md §2), Cleanuparr `:8107`, Seerr `:8108`
(see the stack-file headers).

**1d. Docker API proxy + its clients, together.** dockerproxy moves to the
internal `dockerapi` network, so Homepage, MCP and Diun must move with it:
```bash
docker compose build mcp
docker compose up -d dockerproxy homepage mcp diun caddy
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/caddy-health    # 200
# allowlist: inspect allowed (200), file copy-out refused (403)
docker exec homepage wget -q -S -O /dev/null http://dockerproxy:2375/containers/caddy/json 2>&1 | head -1
docker exec homepage wget -q -S -O /dev/null 'http://dockerproxy:2375/containers/caddy/archive?path=/etc/hostname' 2>&1 | head -1
# isolation: a container on `proxy` can no longer resolve dockerproxy at all
docker exec seerr wget -q -T 3 -O- http://dockerproxy:2375/version || echo "unreachable (good)"
docker logs dockerproxy 2>&1 | grep ' 403 ' | tail      # anything a client needs that got refused
docker compose exec diun diun notif test
```
If Homepage's container status or a Diun check breaks, the `403` lines show the
path. Add it to `dockerproxy/haproxy.cfg` only if it's a read-only GET that
can't return file contents.
On the laptop, re-register the MCP client with the token:
`claude mcp remove homeserver && claude mcp add --transport http homeserver http://100.82.82.78:8105/mcp --header "Authorization: Bearer <MCP_AUTH_TOKEN>"`.
Odysseus needs the same header, or it gets 401.

**1e. Monitoring** (Grafana 13 migrates dashboards on first start; copy taken in wave 0):
```bash
docker compose up -d prometheus grafana node-exporter cadvisor
docker logs grafana 2>&1 | grep -i -E 'migrat|error' | tail
```

**1f. Apps with automatic, low-risk migrations:**
```bash
docker compose up -d sonarr radarr prowlarr bazarr flaresolverr profilarr calibre-web kavita adguard vaultwarden vaultwarden-backup
nslookup example.com "$(grep ^SERVER_IP= .env | cut -d= -f2)"   # AdGuard still answers (NET_RAW was dropped)
docker logs adguard 2>&1 | grep -i 'operation not permitted' | tail -3   # should be empty
```
- Vaultwarden 1.37 logs out "remember this device" 2FA tokens, so expect one 2FA
  prompt per client.
- Vaultwarden is now on its own network and read-only, and its backup
  container has no network. Point any Uptime Kuma monitor that used
  `vaultwarden:80` at `https://<SERVER_IP>:8092/alive` instead.
- FlareSolverr is now reachable only from Prowlarr. Re-test one
  Cloudflare-protected indexer in Prowlarr, and drop any Uptime Kuma monitor on
  `flaresolverr:8191`.
- Bazarr 1.6 removed the Podnapisi provider.

**1g. VPN pair, together** (qBittorrent shares Gluetun's network namespace):
```bash
docker compose up -d gluetun qbittorrent
docker compose up -d --force-recreate qbittorrent
docker logs gluetun 2>&1 | grep -i 'port forward' | tail -3
```
In qBittorrent → Options → Connection, the listening port must match. Re-check
that *Bypass authentication for clients on localhost* is still on (Gluetun's
port-sync POST needs it). qBittorrent now sees only `/media/downloads`, and its
save paths are unchanged.

Gluetun's control server now answers only the public-IP route (gluetun/control-server-auth.toml):
```bash
docker inspect --format '{{.State.Health.Status}}' gluetun qbittorrent        # healthy healthy
docker exec homepage wget -q -O- http://gluetun:8000/v1/publicip/ip | head -c 80; echo
docker exec homepage wget -q -S -O /dev/null http://gluetun:8000/v1/vpn/settings 2>&1 | head -1   # 401/403
```

## Wave 2 — first offsite backup

Follow docs/backups.md §3–5. Don't start wave 3 until a snapshot has finished
and the test restore works.

## Wave 3 — one-way migrations (autoheal stopped)

```bash
docker compose stop autoheal
```

**3a. Uptime Kuma 1.23 → 2.5.** Must come before Home Assistant (HA 2026.11's
Kuma integration requires 2.x). Do not interrupt the migration:
```bash
docker compose up -d uptime-kuma
docker logs -f uptime-kuma          # wait for the migration to finish and the server to listen
```
**3b. Home Assistant 2026.11:**
```bash
docker compose up -d homeassistant && docker logs -f homeassistant
```
**3c. Syncthing 1.29 → 2.1** (LevelDB → SQLite, minutes to tens of minutes):
```bash
docker compose up -d syncthing && docker logs -f syncthing
```
**3d. Jellyfin 10.11 → 12.4.** First, in the Jellyfin dashboard, *remove third-party
plugins* (10.11 builds won't load in 12). Then:
```bash
docker compose up -d jellyfin && docker logs -f jellyfin
```
After it is up: *Dashboard → Libraries → Scan All Libraries*. The first scan is
slow (full path check). Confirm transcoding still uses VAAPI (play something
that needs a transcode; *Dashboard → Activity* shows the method).

**Then turn autoheal back on and check everything:**
```bash
docker compose start autoheal
docker compose up -d                 # should now report everything "Running"/"Started" with no recreations
docker compose ps --format 'table {{.Name}}\t{{.Status}}'
python3 scripts/alert-check.py --print
```

**Rollback for a wave 3 service:** stop it, set its old tag back in
`stacks/<name>.yaml`, restore its tarball into the volume
(`docker run --rm --volumes-from <name> -v /srv/pre-upgrade-2026-11:/b alpine sh -c 'cd / && tar xzf /b/<name>.tgz'`),
then start it. Once everything has run cleanly for a week, delete `/srv/pre-upgrade-2026-11`.

## Wave 4 — host and Tailscale

Work through docs/security-hardening.md top to bottom (SSH keys, patches,
reboot, Tailscale, Vaultwarden via Tailscale Serve, encrypted DNS, Syncthing
privacy, app auth/telemetry checklist). Then install the alert cron if it
isn't installed yet (docs/deployment.md → Alerting), and add a notification
channel to Uptime Kuma.

## Wave 5 — keep the disk from filling again

- **Sonarr / Radarr → Settings → Media Management → Minimum Free Space: 20000 MB.**
  Imports stop before the disk is full, instead of crashing every SQLite app.
- **Cleanuparr** (`:8107`): add qBittorrent (`http://gluetun:8080`), Sonarr
  (`http://sonarr:8989`), Radarr (`http://radarr:7878`).
  - *Queue Cleaner:* on, defaults.
  - *Download Cleaner:* category `tv-sonarr` / `radarr` (whatever qB shows) —
    max ratio 2.0 *or* max seed time 14 days, then **remove torrent + files**;
    enable *unlinked downloads* (files no longer hardlinked into the library).
  - *Seeker:* on, slowest interval.
  - Run each job in dry-run first and read what it would remove.
- **qBittorrent → Options → BitTorrent → Seeding Limits** as a backstop (ratio 2 /
  20160 min, then *Remove torrent and its files*). Leave this off if you'd
  rather Cleanuparr be the only thing deleting.
- **HEVC 10-bit hardware decode test** (the kernel 6.8 amdgpu hang is long fixed
  on 7.0, and Jellyfin 12 carries an AMD hevc_vaapi fix). Jellyfin → Playback →
  Transcoding → enable *HEVC 10bit* decoding → play an x265 10-bit file that
  needs a transcode (Interstellar / Blade Runner 2049) and seek around hard
  for a few minutes. Watch `sudo dmesg -w | grep -i amdgpu` and the NVMe temp
  (MCP `health_summary`). Any `ring gfx timeout` → switch it back off.
- **Profilarr v1.1.5 is the last v1 release and is unmaintained.** v2 has no
  migration path. Keep v1 until you have time to set v2 up from scratch.
