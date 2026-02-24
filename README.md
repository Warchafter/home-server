# Home Server

Config-as-code for a personal home server running Docker Compose on an HP SFF desktop.

## Architecture

```
HP Desktop (Linux)
├── Tailscale (host-level VPN — not a container)
├── Docker Engine + Compose v2
│   ├── Caddy          ─ reverse proxy (ports 80, 8090, 8091)
│   ├── AdGuard Home   ─ DNS + ad blocking (port 53)
│   ├── Uptime Kuma    ─ uptime monitoring (via Caddy :8090)
│   └── Homepage       ─ dashboard (via Caddy :80)
```

## Quick Start

```bash
# 1. On the HP server, clone the repo:
git clone https://github.com/Warchafter/home-server.git
cd home-server

# 2. Run the bootstrap script (installs Docker, Tailscale, fixes DNS):
bash scripts/setup.sh

# 3. Log out and back in (or run: newgrp docker)

# 4. Review your config:
nano .env

# 5. Start everything:
docker compose up -d

# 6. FIRST RUN: Complete AdGuard setup wizard at http://SERVER_IP:3000
#    (Set admin password, pick upstream DNS like 1.1.1.1)
```

Then open `http://<SERVER_IP>` for the dashboard.

## Services

| Service | Access | Purpose |
|---------|--------|---------|
| Homepage | `http://SERVER_IP` | Dashboard — your landing page |
| Uptime Kuma | `http://SERVER_IP:8090` | Monitors uptime of all services |
| AdGuard Home | `http://SERVER_IP:8091` | DNS admin panel + ad blocking stats |
| AdGuard Setup | `http://SERVER_IP:3000` | One-time setup wizard (first run only) |
| AdGuard DNS | `SERVER_IP:53` | Network-wide ad blocking (point router here) |
| Tailscale | Host-level | Secure remote access from anywhere via VPN |

## Project Structure

```
├── compose.yaml          # Root — includes all stacks
├── .env.example          # Environment variable template
├── stacks/               # Per-service Docker Compose files
│   ├── caddy.yaml
│   ├── adguard.yaml
│   ├── uptime-kuma.yaml
│   └── homepage.yaml
├── caddy/
│   └── Caddyfile         # Reverse proxy rules
├── homepage/config/      # Dashboard configuration
├── scripts/
│   └── setup.sh          # Bootstrap script for fresh server
└── docs/                 # Guides and reference
```

## Roadmap

- **Phase 1** (current): Foundation — Caddy, AdGuard, Tailscale, Uptime Kuma, Homepage
- **Phase 2**: Core services — Vaultwarden, Jellyfin, *arr stack, Home Assistant, Syncthing
- **Phase 3**: Advanced — Forgejo, Prometheus/Grafana, Nextcloud, WireGuard
