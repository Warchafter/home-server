# Home Server Comprehensive Analysis (February 2026)

> **Hardware:** Old HP desktop PC running Linux
> **Profile:** Developer who wants to learn -- stack should be approachable but not dumbed down
> **Interests:** Media/entertainment, smart home/IoT, privacy/security, dev tools/learning

---

## Table of Contents

1. [Core Infrastructure / Tech Stack Options](#1-core-infrastructure--tech-stack-options)
2. [Services by Category](#2-services-by-category)
3. [Recommended Architecture & Phased Roadmap](#3-recommended-architecture--phased-roadmap)
4. [Key Decisions to Make Early](#4-key-decisions-to-make-early)
5. [Sources](#sources)

---

## 1. Core Infrastructure / Tech Stack Options

### 1A. Docker Compose (Direct on Linux)

Install Docker Engine on a standard Linux distro (Ubuntu Server 24.04 LTS or Debian 12) and manage everything through `docker-compose.yml` files.

| Aspect | Details |
|--------|---------|
| **Pros** | Simplest path from zero to running services. Compose files are human-readable YAML, easy to version-control in Git. Extremely well-documented with massive community. Lightweight -- no hypervisor overhead, every CPU cycle and byte of RAM goes to your workloads. Reproducible: your entire server is defined in text files you can rebuild from scratch. |
| **Cons** | Single point of failure -- one host, one OS. No built-in HA or auto-restart across machines. Manual networking (you manage port mappings, bridge networks). No GUI unless you add one (Portainer, Komodo, Dockge). |
| **Best for** | Someone who wants to learn containers properly, values simplicity, and runs a single physical machine. This is the 80/20 choice for home servers. |

### 1B. Kubernetes (k3s / microk8s)

A lightweight Kubernetes distribution running on one or more nodes.

| Aspect | Details |
|--------|---------|
| **Pros** | Industry-standard orchestration -- transferable skills to professional work. Built-in service discovery, rolling updates, health checks, auto-restarts. Helm charts make deploying complex stacks repeatable. k3s is genuinely lightweight (single binary, ~512MB RAM overhead). |
| **Cons** | Significant learning curve, even with k3s. Abstractions (pods, services, ingress, PVCs) add complexity that doesn't pay off on a single node. Debugging is harder. Most home server guides and community support target Docker Compose, not Kubernetes. Overkill for managing 10-20 containers on one machine. |
| **Best for** | Someone who specifically wants to learn Kubernetes for career reasons, OR who plans to expand to a multi-node cluster. Not recommended as a first step. |

### 1C. Proxmox VE (Type-1 Hypervisor)

Bare-metal hypervisor that runs VMs and LXC containers, with a web management UI.

| Aspect | Details |
|--------|---------|
| **Pros** | True isolation between workloads via VMs. Can run multiple OSes (a Linux VM for Docker, a Home Assistant OS VM, a Windows VM for testing). LXC containers are lightweight alternatives to full VMs. Snapshots and live migration if you add nodes later. Web UI for management. Proxmox VE 8.x+ now supports OCI container images natively. |
| **Cons** | Higher RAM overhead -- each VM needs its own OS allocation (typically 1-4 GB minimum). More complex storage management (ZFS, LVM-thin). Adds a layer between you and your services. Hardware compatibility can be finicky with older HP desktops (check IOMMU/VT-x support). You still need Docker Compose *inside* a VM, so it's Docker Compose + extra steps. |
| **Best for** | Someone who needs hard isolation (e.g., running untrusted workloads), wants to experiment with multiple OSes, or plans to build a multi-node cluster. Good "Phase 3" upgrade path, not a great starting point. |

### 1D. GUI Dashboard Platforms (CasaOS / Umbrel / Cosmos Server)

Pre-built platforms that provide a web storefront for installing self-hosted apps with minimal configuration.

| Aspect | Details |
|--------|---------|
| **Pros** | Fastest time-to-running-services. Beautiful UIs. CasaOS (32k+ GitHub stars) has a curated app store with 50+ verified apps. Cosmos Server provides built-in reverse proxy, authentication, and certificate management. Umbrel focuses on privacy-first apps. |
| **Cons** | Limited customization -- you're constrained to what the platform supports. Abstracts away the learning. When something breaks, debugging is harder because you don't understand the underlying plumbing. Most use Docker underneath, but hide it behind their own abstractions. Lock-in to the platform's update cycle and app catalog. |
| **Best for** | Non-technical users or someone who explicitly does NOT want to learn the internals. Not recommended for a developer who wants to understand what's happening. |

### Recommendation: Docker Compose on Ubuntu Server 24.04 LTS

**Start with Docker Compose on bare metal Linux.** Here's why this is the right call for your profile:

1. **You're a developer.** Compose files are just YAML. You'll read them, understand them, and version-control them in this very Git repo.
2. **Single machine.** Kubernetes and Proxmox shine in multi-node scenarios. On one old HP desktop, they add overhead without proportional benefit.
3. **Learning that transfers.** Docker and Compose are foundational. If you later move to Kubernetes, Proxmox, or cloud hosting, this knowledge carries over directly.
4. **Community support.** Nearly every self-hosted app publishes a Docker Compose example. Troubleshooting is straightforward.
5. **Optional GUI later.** If you want a management GUI, add **Komodo** (free, open-source, no paywall features, built-in monitoring) or **Dockge** (lightweight Compose stack manager) on top, rather than letting a platform own your entire stack.

**Upgrade path:** If you outgrow one machine, consider Proxmox as the host OS with a Docker VM inside it, or expand to a k3s cluster across multiple machines.

---

## 2. Services by Category

### 2A. Media & Entertainment

#### Media Server

| Service | License | Cost | Verdict |
|---------|---------|------|---------|
| **Jellyfin** | FOSS (GPL) | Free, forever | **Recommended.** Hardware transcoding (Intel QSV, VAAPI, NVIDIA) included free. No telemetry. Active community. UI is 90% as polished as Plex. |
| **Plex** | Proprietary | Free tier + Plex Pass ($120 lifetime or $5/mo) | Most polished UI and widest device support. But: remote playback now requires Plex Pass (since April 2025), hardware transcoding requires Plex Pass, and it phones home to Plex servers. |
| **Emby** | Proprietary | Free tier + Emby Premiere ($119 lifetime) | Good middle ground on UI quality. Hardware transcoding and mobile sync require Premiere. Less community momentum than Jellyfin. |

**Pick Jellyfin.** It aligns with the self-hosting philosophy (no vendor dependency, no paywalls), and your old HP desktop likely has an Intel iGPU that Jellyfin will use for free hardware transcoding via VAAPI/QSV.

#### Music Server

| Service | Notes |
|---------|-------|
| **Navidrome** | **Recommended.** Lightweight, modern web UI, compatible with all Subsonic API clients (DSub, Symfonium, play:Sub). Handles large libraries well. Minimal resource usage. |
| **Funkwhale** | Decentralized/social music platform. Heavier, community-focused. Better if you want to share music with others in a federated network. |

#### Ebooks & Comics

| Service | Best For |
|---------|----------|
| **Kavita** | **Recommended for comics/manga.** Excellent built-in reader for CBZ/CBR/PDF. Series tracking, per-user progress, no external dependencies. Great standalone option if starting from scratch. |
| **Calibre-Web** | **Recommended for ebooks.** Integrates with Calibre's metadata engine. Send-to-Kindle, Kobo sync, OPDS feeds. Best if you already use Calibre for library management. |

You can run both side by side -- Kavita for visual media (comics, manga) and Calibre-Web for text-heavy ebooks.

#### The *arr Stack (Media Automation)

The *arr stack automates the pipeline of finding, downloading, organizing, and renaming media.

| Service | Role |
|---------|------|
| **Prowlarr** | Indexer manager. Configure indexers once, syncs to all other *arr apps automatically. |
| **Sonarr** (v4) | TV show management. Monitors, downloads, renames, organizes series. |
| **Radarr** (v5) | Movie management. Same workflow as Sonarr but for films. |
| **Lidarr** | Music management (optional -- Navidrome handles playback). |
| **Readarr** | Ebook/audiobook management (optional). |
| **Bazarr** | Subtitle management. Auto-downloads subtitles for Sonarr/Radarr content. |
| **Jellyseerr** | Request portal. Lets household members request movies/shows with a Netflix-like UI. |
| **Profilarr** | (New, 2025+) Syncs TRaSH-Guides quality profiles and custom formats to Sonarr/Radarr automatically. |
| **FlareSolverr** | Cloudflare challenge solver proxy for Prowlarr. Essential in 2026 as many indexers sit behind CAPTCHAs. |

**Supporting infrastructure:**
- **Download client:** qBittorrent (with VueTorrent UI) or Transmission
- **VPN for downloads:** **Gluetun** container -- routes download client traffic through a VPN provider while keeping other containers on the local network
- **Follow [TRaSH-Guides](https://trash-guides.info/)** for optimal quality profiles, naming conventions, and hardlink configuration

**Critical setup detail:** Use a unified media folder structure with hardlinks. All *arr containers and your download client must share the same volume mount and run with identical `PUID`/`PGID` values. This avoids file copies and saves disk space.

---

### 2B. Smart Home / IoT

#### Home Assistant

**Home Assistant** is the undisputed leader in self-hosted smart home control. It supports 2,000+ integrations, has a powerful automation engine, and a mobile app for both iOS and Android.

**Deployment options:**
- **Home Assistant OS (HAOS) in a VM:** The "official" path. Runs the full supervisor with add-on store. Best if you later move to Proxmox. Not ideal for a single Docker Compose setup.
- **Home Assistant Container:** Runs as a Docker container. No supervisor or add-on store, but integrates cleanly with your Compose stack. You install companion services (Mosquitto, Zigbee2MQTT) as separate containers. **Recommended for a Docker Compose setup.**

#### MQTT Broker

| Service | Notes |
|---------|-------|
| **Eclipse Mosquitto** | **Recommended.** The gold standard MQTT broker. Tiny footprint, rock-solid, well-documented. Run as a Docker container alongside Home Assistant. |

#### Zigbee / Z-Wave Integration

| Approach | Pros | Cons |
|----------|------|------|
| **Zigbee2MQTT + Mosquitto** | **Recommended.** Supports 3,000+ devices. Runs independently of HA, communicates via MQTT. Highly configurable. Large community. | Requires separate container and MQTT broker setup. |
| **ZHA (Zigbee Home Automation)** | Built into Home Assistant. Simpler setup, no MQTT needed. | Fewer supported devices. Less flexibility. Harder to debug. |

**Recommended hardware:**
- **Budget:** Sonoff ZBDongle-E (Zigbee 3.0, ~$15-20). Solid with Zigbee2MQTT, supports firmware upgrades.
- **Best long-term:** SLZB-06 (Ethernet Zigbee coordinator, ~$35-40). Network-based placement means you can put it where Zigbee coverage is best, not where your server is.
- **Official:** Home Assistant Connect ZBT-2 (USB stick supporting Zigbee + Thread/Matter).

**For Z-Wave:** If needed, use a Z-Wave JS USB stick with the Z-Wave JS add-on. Z-Wave is less common now; most new devices use Zigbee, Thread, or Matter.

---

### 2C. Privacy & Security

#### VPN / Remote Access

| Service | Architecture | Verdict |
|---------|-------------|---------|
| **WireGuard** (via wg-easy) | Self-hosted VPN server. You own everything. Kernel-level performance (~8Gbps capable). | **Recommended if you have a static IP or no CGNAT.** Full control, zero external dependencies, fastest performance. Use [wg-easy](https://github.com/wg-easy/wg-easy) for a management UI. |
| **Tailscale** | Mesh VPN using WireGuard protocol. Devices connect peer-to-peer. Control plane hosted by Tailscale Inc. | **Recommended if you have CGNAT or want zero-config device mesh.** Works behind any NAT. Free for up to 100 devices. Minimal setup. |
| **Headscale** | Self-hosted Tailscale control plane. | For those who want Tailscale's UX without trusting a third party. More complex to set up. |

**Practical advice:** Start with **Tailscale** (free tier) to get immediate remote access to your server. Later, add **WireGuard** if you want a traditional VPN gateway for routing all traffic (e.g., when on public WiFi).

#### DNS-Level Ad Blocking

| Service | Verdict |
|---------|---------|
| **AdGuard Home** | **Recommended.** Modern UI, built-in DNS-over-HTTPS/TLS support, parental controls, per-client settings, easier initial setup. Single binary, low resource usage. |
| **Pi-hole** | Excellent and battle-tested. Larger community. More customizable via CLI. Requires more manual config for encrypted DNS. |

Both are nearly equivalent in ad-blocking effectiveness. AdGuard Home's edge comes from its more modern UI, native encrypted DNS support, and easier configuration for families.

#### Password Manager

| Service | Notes |
|---------|-------|
| **Vaultwarden** | **Recommended.** Unofficial Bitwarden-compatible server written in Rust. Under 50MB RAM idle. Full compatibility with all Bitwarden clients (browser extensions, mobile apps, CLI). Supports TOTP, file attachments, organizations. 35k+ GitHub stars. |

**Critical:** Vaultwarden requires HTTPS. Deploy it behind your reverse proxy with a valid TLS certificate. This is arguably the most important service to get right -- treat it as production-grade from day one. Back it up religiously.

#### File Sync & Cloud Storage

| Service | Architecture | Verdict |
|---------|-------------|---------|
| **Syncthing** | Peer-to-peer sync. No server needed. | **Recommended for device-to-device file sync.** Zero maintenance, encrypted, works across platforms. Set up folder pairs and forget about it. Android client available. |
| **Nextcloud** | Client-server cloud platform (files, calendar, contacts, office docs, video calls). | **Recommended if you want a full Google Workspace replacement.** Much heavier (needs PHP, a database, Redis). More maintenance. But feature-rich: collaborative document editing, CalDAV/CardDAV, mobile auto-upload. |

**Practical approach:** Start with **Syncthing** for immediate file sync needs (lightweight, no server component). Add **Nextcloud** in Phase 2 or 3 when you want calendar/contacts sync or sharing with non-technical family members.

#### Reverse Proxy

| Service | Config Style | Auto-Discovery | Verdict |
|---------|-------------|----------------|---------|
| **Caddy** | Caddyfile (simple text) | No (manual) | **Recommended to start.** Automatic HTTPS by default. Simplest configuration syntax. Handles Let's Encrypt certificate provisioning with zero config. Great documentation. |
| **Traefik** | Docker labels + YAML/TOML | Yes (watches Docker socket) | **Recommended for larger setups.** Auto-discovers new containers via Docker labels. More powerful but steeper learning curve. Excellent once set up. |
| **Nginx Proxy Manager** | Web GUI | No (manual via UI) | Most approachable for beginners. But: project has stalled (v3 in perpetual WIP), slow security patching, limited automation. Not recommended for a developer. |

**Recommendation:** Start with **Caddy** for its simplicity and automatic HTTPS. If you find yourself constantly editing the Caddyfile every time you add a service, migrate to **Traefik** for its Docker auto-discovery.

---

### 2D. Dev Tools & Learning

#### Git Server

| Service | Notes |
|---------|-------|
| **Forgejo** | **Recommended.** Community-governed hard fork of Gitea (GPLv3+). More active development (232 contributors, 2,181 PRs in 2025 vs Gitea's 153 contributors, 1,256 commits). Built-in CI/CD via Forgejo Actions (GitHub Actions compatible syntax). Non-profit governance under Codeberg e.V. No copyright assignment required for contributions. |
| **Gitea** | Still solid, but governed by a for-profit company (Gitea Ltd). MIT licensed. Slower development pace. Feature-equivalent to Forgejo for now, but diverging. |

#### CI/CD

| Service | Notes |
|---------|-------|
| **Forgejo Actions** (built-in) | **Recommended if using Forgejo.** Uses GitHub Actions-compatible workflow syntax (`.forgejo/workflows/`). Self-hosted runner connects outbound (no public IP needed). Learn one CI syntax that works on GitHub AND your home server. |
| **Woodpecker CI** | Lightweight, community fork of Drone. Good standalone CI if you're not using Forgejo. YAML pipeline definitions. |
| **GitHub Actions self-hosted runner** | Run GitHub Actions workflows on your own hardware. Good if your primary repos are on GitHub and you want local execution for builds/tests. |

#### Databases

For development and learning, run these as Docker containers:

| Database | Use Case |
|----------|----------|
| **PostgreSQL 17** | Primary relational database. Used by Nextcloud, Forgejo, Vaultwarden, and many other self-hosted apps. Learn one, use it everywhere. |
| **Redis 7** | In-memory cache/queue. Required by Nextcloud, useful for caching in your own projects. |
| **MariaDB 11** | MySQL-compatible. Some apps (e.g., certain WordPress setups) prefer it. Keep as a secondary option. |

#### Monitoring & Observability

| Service | Role | Notes |
|---------|------|-------|
| **Uptime Kuma** | Uptime monitoring & alerting | **Recommended as first monitoring tool.** Beautiful UI, monitors HTTP/TCP/DNS/ping endpoints, sends alerts via Telegram/Slack/email/Gotify. Dead simple to set up. |
| **Prometheus** | Metrics collection | Time-series database that scrapes metrics from exporters. Foundation for advanced monitoring. |
| **Grafana** | Visualization & dashboards | Connects to Prometheus (and many other sources). Pre-built dashboards for everything. |
| **Node Exporter** | Host metrics | Exposes CPU, RAM, disk, network stats to Prometheus. |
| **cAdvisor** | Container metrics | Exposes per-container resource usage to Prometheus. |

**Phased approach:** Start with **Uptime Kuma** alone (Phase 1). Add the full **Prometheus + Grafana + exporters** stack in Phase 3 when you have services worth monitoring in depth.

#### Dashboard

| Service | Config | Notes |
|---------|--------|-------|
| **Homepage** | YAML files | **Recommended.** Best widget ecosystem, lightweight, real-time service status, easy to version-control. Perfect for a developer. |
| **Homarr** | Web GUI (drag-and-drop) | More user-friendly, no YAML needed. Slightly heavier. Better for shared households where non-technical users want a portal. |

---

## 3. Recommended Architecture & Phased Roadmap

### Phase 1: Foundation (Week 1-2)

**Goal:** A stable, secure base that everything else builds on.

```
HP Desktop
|-- Ubuntu Server 24.04 LTS (bare metal)
|-- Docker Engine + Docker Compose v2
|-- Core infrastructure containers:
    |-- Caddy (reverse proxy + automatic HTTPS)
    |-- AdGuard Home (DNS + ad blocking)
    |-- Tailscale (remote access)
    |-- Uptime Kuma (monitoring)
    |-- Homepage (dashboard)
    |-- Watchtower (automatic container image updates -- use with caution, see notes)
```

**Phase 1 tasks:**
1. Install Ubuntu Server 24.04 LTS on the HP desktop
2. Harden SSH (key-only auth, disable password login, non-standard port)
3. Install Docker Engine and Docker Compose v2 (via official Docker repo, not Snap)
4. Set up your project directory structure (see below)
5. Configure Caddy as the reverse proxy with automatic Let's Encrypt certificates
6. Deploy AdGuard Home as your network's DNS server (point your router's DHCP DNS setting to it)
7. Install Tailscale for immediate remote access
8. Deploy Uptime Kuma to monitor your services
9. Set up Homepage dashboard to see everything at a glance
10. Initialize your backup strategy (see Section 4)

**Suggested directory structure:**
```
/home/<user>/home-server/          # This Git repo
  docker-compose.yml               # Or split into per-stack files
  .env                             # Secrets (gitignored)
  caddy/
    Caddyfile
  adguard/
    conf/
  homepage/
    config/
  monitoring/
    docker-compose.yml

/srv/docker/                       # Persistent container data (volumes)
  caddy/
  adguard/
  uptime-kuma/
  homepage/

/mnt/storage/                      # Large media storage (separate drive if possible)
  media/
    movies/
    tv/
    music/
    books/
  downloads/
    complete/
    incomplete/
```

---

### Phase 2: Core Services (Week 3-6)

**Goal:** The services you'll actually use daily.

```
Add to stack:
|-- Vaultwarden (password manager) -- CRITICAL, set up HTTPS properly
|-- Syncthing (file sync between devices)
|-- Jellyfin (media server)
|-- Navidrome (music streaming)
|-- *arr stack:
    |-- Prowlarr
    |-- Sonarr v4
    |-- Radarr v5
    |-- Bazarr
    |-- Jellyseerr
    |-- qBittorrent + Gluetun (VPN)
    |-- FlareSolverr
|-- Home Assistant Container
|-- Mosquitto (MQTT broker)
|-- Zigbee2MQTT (with USB Zigbee coordinator)
```

**Phase 2 tasks:**
1. Deploy Vaultwarden behind Caddy with HTTPS. Migrate your passwords. Set up emergency access.
2. Install Syncthing, pair your devices, configure shared folders.
3. Set up the media stack: Jellyfin first, then the *arr stack following TRaSH-Guides for quality profiles and folder structure.
4. Configure Gluetun with your VPN provider, route only qBittorrent through it.
5. Deploy Home Assistant Container. Add Mosquitto and Zigbee2MQTT. Buy a Zigbee coordinator and a few smart devices to experiment with.
6. Set up Navidrome, point it at your music collection.

---

### Phase 3: Advanced & Nice-to-Have (Month 2+)

**Goal:** Developer tools, deeper monitoring, and polish.

```
Add to stack:
|-- Forgejo (self-hosted Git)
|-- Forgejo Actions Runner (CI/CD)
|-- PostgreSQL 17 (shared database)
|-- Kavita or Calibre-Web (ebooks/comics)
|-- Nextcloud (if you want full cloud suite)
|-- Prometheus + Grafana + Node Exporter + cAdvisor
|-- WireGuard (wg-easy) as a proper VPN gateway
|-- Profilarr (auto-sync TRaSH profiles)
```

**Phase 3 tasks:**
1. Deploy Forgejo. Mirror your GitHub repos. Set up a self-hosted runner for CI/CD.
2. Replace per-app SQLite databases with a shared PostgreSQL instance where supported.
3. Deploy the full Prometheus + Grafana monitoring stack. Import community dashboards.
4. Add Kavita for your comics/manga collection.
5. (Optional) Set up Nextcloud if you want calendar/contacts sync or collaborative documents.
6. (Optional) Deploy WireGuard via wg-easy for a traditional VPN gateway.
7. (Optional) Consider migrating to Proxmox if you want VM isolation, or to k3s if you want Kubernetes experience.

---

## 4. Key Decisions to Make Early

These decisions ripple through your entire setup. Decide them before Phase 1.

### 4.1. Domain Name & DNS

**Decision:** Buy a domain name (e.g., `yourname.dev` or `homelab.yourdomain.com`).

**Why it matters:** A real domain is required for valid HTTPS certificates (Let's Encrypt). Without it, you're stuck with self-signed certs and browser warnings.

**Recommendation:**
- Buy a domain from **Cloudflare Registrar** (at-cost pricing, no markup) or **Porkbun** (cheap, good UI).
- Use **Cloudflare** as your DNS provider (free tier) -- it integrates well with Caddy and Traefik for DNS-01 ACME challenges, which let you get certificates for internal services without exposing port 80 to the internet.
- Set up a wildcard DNS record (`*.home.yourdomain.com`) pointing to your server's local IP.

### 4.2. Storage Strategy

**Decision:** How will you store and organize persistent data?

**Why it matters:** Once containers are writing data to specific paths, restructuring is painful. Get the layout right from the start.

**Recommendation:**
- **OS drive:** The HP desktop's internal drive for Ubuntu, Docker, and container configs.
- **Storage drive:** If possible, add a second internal drive (or USB-attached external) for media and bulk data. Mount at `/mnt/storage/`.
- **Filesystem:** Use **ext4** for simplicity. If you have 2+ drives and want redundancy, consider **mergerfs** (pools multiple drives into one mount) + **SnapRAID** (parity-based backup, not real-time RAID).
- **Avoid ZFS** on an old HP desktop unless it has 16GB+ RAM. ZFS is memory-hungry.
- **Unified media folder structure:** Use a single root (`/mnt/storage/media/`) with subdirectories. Mount this into all *arr containers and Jellyfin at the same path to enable hardlinks.

### 4.3. Backup Strategy (The 3-2-1 Rule)

**Decision:** How will you protect against data loss?

**The 3-2-1 rule:** 3 copies of data, on 2 different media types, with 1 copy offsite.

**Recommendation:**

| Copy | Tool | Location |
|------|------|----------|
| **Live data** | -- | Server drives |
| **Local backup** | **Restic** or **BorgBackup** | External USB drive or NAS |
| **Offsite backup** | **Restic** to B2/S3 | Backblaze B2 ($6/TB/month) or any S3-compatible storage |

- **Restic** is recommended over BorgBackup for its native S3/B2 support (no rclone needed) and simpler restore workflow.
- **What to back up:**
  - Container configs and compose files (this Git repo)
  - Vaultwarden data (CRITICAL -- your passwords)
  - Home Assistant config
  - Database dumps (PostgreSQL, SQLite files)
  - Personal files / Syncthing data
- **What NOT to back up:** Media files that can be re-downloaded (movies, TV shows). Back up your *arr databases and configs, not the media itself.
- **Automate it:** Use a cron job or a **borgmatic** / restic wrapper script. Run `restic check` weekly to verify backup integrity.
- **Test restores regularly.** A backup you've never tested is not a backup.

### 4.4. Secrets Management

**Decision:** How will you handle passwords, API keys, and tokens in your Docker Compose files?

**Recommendation:**
- Use a `.env` file at the root of your project (already in your `.gitignore`).
- Reference secrets in Compose files as `${VARIABLE_NAME}`.
- For extra safety, use Docker secrets or a tool like **SOPS** (Secrets OPerationS) with **age** encryption to store encrypted secrets in Git.
- **Never** commit plaintext secrets to this repository.

### 4.5. Network Architecture

**Decision:** How will your services be accessed internally and externally?

**Recommendation:**
- **Internal access:** All services behind Caddy reverse proxy at `https://service.home.yourdomain.com`. Configure your router to use AdGuard Home as its DNS, and AdGuard Home to resolve `*.home.yourdomain.com` to your server's local IP (DNS rewrite).
- **External access:** Use **Tailscale** (mesh VPN) for remote access. This means you do NOT need to open any ports on your router. All access goes through Tailscale's encrypted tunnel.
- **Do NOT expose services directly to the internet** unless you have a specific reason and understand the security implications. Tailscale eliminates the need for port forwarding.
- **Docker networking:** Create a shared Docker bridge network (e.g., `proxy-network`) that Caddy and your services join. Services communicate internally by container name.

### 4.6. Container Update Strategy

**Decision:** How will you keep container images up to date?

**Recommendation:**
- **Pin image versions** in your Compose files (e.g., `jellyfin/jellyfin:10.10.6` not `:latest`).
- Use **Watchtower** in monitor-only mode (`WATCHTOWER_MONITOR_ONLY=true`) to get notifications about available updates without auto-applying them.
- Review changelogs before updating. Apply updates manually by bumping the version in your Compose file and running `docker compose up -d`.
- Alternatively, use **Diun** (Docker Image Update Notifier) which only notifies and never auto-updates.

---

## Quick Reference: Complete Service Map

| Category | Service | Docker Image | RAM Estimate |
|----------|---------|-------------|-------------|
| **Reverse Proxy** | Caddy | `caddy:2` | ~30MB |
| **DNS/Ad-block** | AdGuard Home | `adguard/adguardhome:latest` | ~50MB |
| **VPN Access** | Tailscale | `tailscale/tailscale:latest` | ~30MB |
| **Monitoring** | Uptime Kuma | `louislam/uptime-kuma:1` | ~100MB |
| **Dashboard** | Homepage | `ghcr.io/gethomepage/homepage:latest` | ~100MB |
| **Passwords** | Vaultwarden | `vaultwarden/server:latest` | ~50MB |
| **File Sync** | Syncthing | `syncthing/syncthing:latest` | ~100MB |
| **Media Server** | Jellyfin | `jellyfin/jellyfin:latest` | ~300-500MB |
| **Music** | Navidrome | `deluan/navidrome:latest` | ~50MB |
| **TV Automation** | Sonarr | `linuxserver/sonarr:latest` | ~200MB |
| **Movie Automation** | Radarr | `linuxserver/radarr:latest` | ~200MB |
| **Indexer Manager** | Prowlarr | `linuxserver/prowlarr:latest` | ~150MB |
| **Subtitles** | Bazarr | `linuxserver/bazarr:latest` | ~150MB |
| **Requests** | Jellyseerr | `fallenbagel/jellyseerr:latest` | ~200MB |
| **Downloads** | qBittorrent | `linuxserver/qbittorrent:latest` | ~100MB |
| **VPN Tunnel** | Gluetun | `qmcgaw/gluetun:latest` | ~30MB |
| **CAPTCHA Solver** | FlareSolverr | `ghcr.io/flaresolverr/flaresolverr:latest` | ~150MB |
| **Smart Home** | Home Assistant | `ghcr.io/home-assistant/home-assistant:stable` | ~300MB |
| **MQTT** | Mosquitto | `eclipse-mosquitto:2` | ~10MB |
| **Zigbee** | Zigbee2MQTT | `koenkk/zigbee2mqtt:latest` | ~100MB |
| **Git Server** | Forgejo | `codeberg.org/forgejo/forgejo:9` | ~200MB |
| **CI Runner** | Forgejo Runner | `code.forgejo.org/forgejo/runner:latest` | ~100MB |
| **Database** | PostgreSQL | `postgres:17` | ~100-300MB |
| **Cache** | Redis | `redis:7-alpine` | ~30MB |
| **Books/Comics** | Kavita | `jvmilazz0/kavita:latest` | ~150MB |
| **Metrics** | Prometheus | `prom/prometheus:latest` | ~200MB |
| **Visualization** | Grafana | `grafana/grafana:latest` | ~200MB |
| **Host Metrics** | Node Exporter | `prom/node-exporter:latest` | ~20MB |
| **Container Metrics** | cAdvisor | `gcr.io/cadvisor/cadvisor:latest` | ~60MB |
| **Backup** | Restic | CLI tool (not a container) | N/A |

**Estimated total RAM for all services:** ~3.5-4.5 GB. An old HP desktop with 8GB RAM will handle Phases 1 and 2 comfortably. 16GB is recommended for the full stack including Phase 3.

---

## Sources

- [Switched from Docker Compose to Kubernetes - XDA Developers](https://www.xda-developers.com/switched-from-docker-compose-to-kubernetes-thoughts/)
- [Best Home Server OS + Proxmox VM vs LXC - SimpleHomelab](https://www.simplehomelab.com/udms-03-best-home-server-os/)
- [Why Containers Will Be More Important in the 2026 Home Lab - Virtualization Howto](https://www.virtualizationhowto.com/2025/12/why-containers-will-be-more-important-than-ever-in-the-2026-home-lab/)
- [Ultimate Home Lab Starter Stack for 2026 - Virtualization Howto](https://www.virtualizationhowto.com/2025/12/ultimate-home-lab-starter-stack-for-2026-key-recommendations/)
- [Proxmox vs Docker: Best Option in 2026 - WunderTech](https://www.wundertech.net/proxmox-vs-docker/)
- [Complete Guide to Proxmox Containers in 2025 - Virtualization Howto](https://www.virtualizationhowto.com/2025/11/complete-guide-to-proxmox-containers-in-2025-docker-vms-lxc-and-new-oci-support/)
- [CasaOS vs Cosmos Server Comparison 2026 - OpenAlternative](https://openalternative.co/compare/casaos/vs/cosmos-server)
- [Cosmos Server Review 2026 - Virtualization Howto](https://www.virtualizationhowto.com/2026/01/i-tested-cosmos-server-is-this-the-best-home-server-os-yet/)
- [Best Media Server 2026: Jellyfin vs Plex vs Emby - SelfHostHero](https://selfhosthero.com/jellyfin-vs-plex-vs-emby-home-media-server-comparison/)
- [Plex vs Jellyfin vs Emby - Best Plex Alternatives 2026 - WunderTech](https://www.wundertech.net/what-are-the-best-plex-alternatives/)
- [Jellyfin vs Plex Home Server - Android Authority](https://www.androidauthority.com/jellyfin-vs-plex-home-server-3360937/)
- [The Ultimate Arr Stack Compose Guide 2026 - CoreLab](https://corelab.tech/arr-stack-docker-compose-guide/)
- [TRaSH-Guides for Sonarr/Radarr](https://trash-guides.info/)
- [Arr Stack: Sonarr, Radarr, Prowlarr Explained - HomeLab Starter](https://homelabstarter.com/homelab-arr-stack-guide/)
- [Zigbee2MQTT Home Assistant 2026 Guide - TecnoYFoto](https://tecnoyfoto.com/en/zigbee2mqtt-home-assistant-guide-2026)
- [Best Zigbee Coordinators for Home Assistant 2026 - SmartHomeScene](https://smarthomescene.com/blog/best-zigbee-dongles-for-home-assistant-2023/)
- [Home Assistant Connect ZBT-2 Announcement](https://www.home-assistant.io/blog/2025/11/19/home-assistant-connect-zbt-2)
- [Tailscale vs WireGuard Comparison - HomeLab Starter](https://www.homelabstarter.com/tailscale-vs-wireguard-comparison/)
- [WireGuard vs Tailscale vs ZeroTier on VPS 2025 - Onidel](https://onidel.com/blog/wireguard-vs-tailscale-vps-2025)
- [Pi-hole vs AdGuard Home - 12 Key Differences - SimpleHomelab](https://www.simplehomelab.com/pi-hole-vs-adguard-home/)
- [AdGuard Home vs Pi-hole - WunderTech](https://www.wundertech.net/adguard-home-vs-pi-hole-best-ad-blocker/)
- [Reverse Proxy Comparison: Traefik vs Caddy vs Nginx - Programonaut](https://www.programonaut.com/reverse-proxies-compared-traefik-vs-caddy-vs-nginx-docker/)
- [Homelab Reverse Proxy Showdown - HomeLab Starter](https://www.homelabstarter.com/homelab-reverse-proxy-comparison/)
- [Nginx Proxy Manager vs Traefik vs Caddy - Docker Recipes](https://docker.recipes/docs/traefik-vs-nginx-vs-caddy)
- [Nextcloud vs Syncthing - Best Self-Hosted Dropbox Alternatives - SSD Nodes](https://www.ssdnodes.com/blog/nextcloud-vs-seafile-dropbox-alternative/)
- [Self-Hosted Git Platforms: GitLab vs Gitea vs Forgejo 2026 - DasRoot](https://dasroot.net/posts/2026/01/self-hosted-git-platforms-gitlab-gitea-forgejo-2026/)
- [Forgejo Comparison with Gitea](https://forgejo.org/compare-to-gitea/)
- [Forgejo Actions Runner with Docker Compose - Linus Groh](https://linus.dev/posts/setting-up-a-self-hosted-forgejo-actions-runner-with-docker-compose/)
- [Kavita vs Calibre-Web: Which Should You Self-Host - selfhosting.sh](https://selfhosting.sh/compare/kavita-vs-calibre-web/)
- [Self-Hosted Password Manager: Vaultwarden Setup Guide 2026 - DasRoot](https://dasroot.net/posts/2026/01/self-hosted-password-manager-vaultwarden-setup/)
- [Uptime Kuma - Official Site](https://uptimekuma.org/)
- [Homepage vs Homarr Dashboard Battle - Petkovsky](https://www.petkovsky.sk/home-sweet-home-the-battle-of-self-hosted-dashboards/)
- [Best Home Lab Dashboards - HomeLab Starter](https://www.homelabstarter.com/homelab-dashboard-homarr-dashy/)
- [Portainer Alternative Komodo - Virtualization Howto](https://www.virtualizationhowto.com/2024/12/portainer-alternative-komodo-for-docker-stack-management-and-deployment/)
- [Why I Ditched Portainer for Komodo - XDA Developers](https://www.xda-developers.com/why-ditched-portainer-komodo/)
- [Linux Backup Strategies: rsync, Borg, restic 2026 - DasRoot](https://dasroot.net/posts/2026/02/linux-backup-strategies-rsync-borg-restic/)
- [Restic vs BorgBackup vs Kopia 2025 - Onidel](https://onidel.com/blog/restic-vs-borgbackup-vs-kopia-2025)
- [3-2-1 Backup Rule - VitalVas Blog](https://blog.vitalvas.com/post/2026/01/01/backup-3-2-1-rule/)
