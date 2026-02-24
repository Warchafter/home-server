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

## Backup Reminder

Back up these critical items regularly:
- This Git repo (it's your entire server config)
- The `.env` file (not in git — copy it somewhere safe)
- Docker volumes: `adguard_conf`, `adguard_work`, `uptime_kuma_data`, `caddy_data`, `caddy_config`

To dump a volume to a tarball:
```bash
docker run --rm -v adguard_conf:/data -v $(pwd):/backup busybox \
  tar czf /backup/adguard_conf_backup.tar.gz -C /data .
```
