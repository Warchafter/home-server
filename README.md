# Home Server

Config-as-code for a personal home server running Docker Compose on an HP SFF desktop.

## Architecture

```
HP Desktop (Linux) — AMD Ryzen 5 PRO 2400G, Radeon Vega 11 iGPU
├── Tailscale (host-level VPN — not a container)
├── Docker Engine + Compose v2 (15 containers)
│   ├── Caddy            ─ reverse proxy (ports 80, 8090-8099)
│   ├── Docker Proxy     ─ secure Docker socket proxy for Homepage
│   ├── AdGuard Home     ─ DNS + ad blocking (port 53)
│   ├── Uptime Kuma      ─ uptime monitoring (via Caddy :8090)
│   ├── Homepage         ─ dashboard (via Caddy :80)
│   ├── Vaultwarden      ─ password manager (self-signed TLS :8092)
│   ├── Vaultwarden Bkup ─ automated encrypted backups
│   ├── Jellyfin         ─ media server (via Caddy :8093, VAAPI transcoding)
│   ├── Sonarr           ─ TV show management (via Caddy :8094)
│   ├── Radarr           ─ movie management (via Caddy :8095)
│   ├── Prowlarr         ─ indexer manager (via Caddy :8096)
│   ├── Gluetun          ─ VPN tunnel (ProtonVPN, for qBittorrent)
│   ├── qBittorrent      ─ download client (via Caddy :8097, VPN-routed)
│   ├── Home Assistant   ─ smart home automation (via Caddy :8098)
│   └── Syncthing        ─ file sync (via Caddy :8099)
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
docker network create proxy
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
| Vaultwarden | `https://SERVER_IP:8092` | Password manager (Bitwarden-compatible, self-signed TLS) |
| Jellyfin | `http://SERVER_IP:8093` | Media server (movies, TV, music) |
| Sonarr | `http://SERVER_IP:8094` | TV show management & automation |
| Radarr | `http://SERVER_IP:8095` | Movie management & automation |
| Prowlarr | `http://SERVER_IP:8096` | Indexer manager for Sonarr/Radarr |
| qBittorrent | `http://SERVER_IP:8097` | Download client (VPN-routed via Gluetun) |
| Home Assistant | `http://SERVER_IP:8098` | Smart home automation |
| Syncthing | `http://SERVER_IP:8099` | File sync across devices |
| Tailscale | Host-level | Secure remote access from anywhere via VPN |

## Project Structure

```
├── compose.yaml               # Root — includes all stacks
├── .env.example               # Environment variable template
├── stacks/                    # Per-service Docker Compose files
│   ├── caddy.yaml             # Phase 1
│   ├── dockerproxy.yaml
│   ├── adguard.yaml
│   ├── uptime-kuma.yaml
│   ├── homepage.yaml
│   ├── vaultwarden.yaml       # Phase 2
│   ├── vaultwarden-backup.yaml
│   ├── jellyfin.yaml
│   ├── sonarr.yaml
│   ├── radarr.yaml
│   ├── prowlarr.yaml
│   ├── gluetun.yaml
│   ├── qbittorrent.yaml
│   ├── homeassistant.yaml
│   └── syncthing.yaml
├── caddy/
│   └── Caddyfile              # Reverse proxy rules
├── homepage/config/           # Dashboard configuration
├── scripts/
│   └── setup.sh               # Bootstrap script for fresh server
└── docs/                      # Guides and reference
```

## Roadmap

- **Phase 1** (complete): Foundation — Caddy, AdGuard, Tailscale, Uptime Kuma, Homepage
- **Phase 2** (complete): Core services — Vaultwarden, Jellyfin, *arr stack, Home Assistant, Syncthing
- **Phase 3**: Advanced — Kavita, Calibre-Web, Prometheus/Grafana, Nextcloud, WireGuard
