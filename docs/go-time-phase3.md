# Go Time: Phase 3 — Monitoring, Reading & Automation

*Phase 2 turned the box into actual infrastructure. Now we're adding
eyes on the whole thing (Prometheus + Grafana), a reading library
(Kavita + Calibre-Web), and automated quality profiles for the *arr
stack (Profilarr). Seven new containers, same drill as before.*

---

## Before You Start

Phase 2 must be fully operational. Verify on the HP:
```bash
cd ~/home-server
docker compose ps
```

You should see 15 containers running. If anything's down, fix that first.

---

## The Rundown (8 Steps)

### 1. Pull the latest config

From your **laptop**, push any local changes. Then on the **HP**:
```bash
cd ~/home-server
git pull
```

You should see 7 new stack files, config directories for Prometheus and
Grafana, and updated configs come down.

---

### 2. Re-run the setup script

The setup script has new Phase 3 steps — it creates the books and
comics directories under your media path:

```bash
bash scripts/setup.sh
```

It's idempotent, so it won't reinstall Docker or Tailscale. It will:
- Create `/srv/media/books/` for ebooks
- Create `/srv/media/comics/` for comics and manga

---

### 3. Update your .env

```bash
nano .env
```

Add these lines at the bottom:

```bash
# Grafana
GRAFANA_ADMIN_PASS=pick-a-strong-password
```

The Kavita credentials come later, after the service is running.

Save and exit (`Ctrl+X`, then `Y`, then `Enter`).

---

### 4. Fire it up

```bash
docker compose up -d
```

Docker pulls 7 new images (~1GB total on first run). This will take
a few minutes depending on your internet speed.

Check that everything came up:
```bash
docker compose ps
```

You want 22 containers with `running` status. If something says
`restarting`, check its logs:
```bash
docker compose logs grafana
```

---

### 5. Set up each service

Work through these in order. Each service has a first-run wizard or
initial config step.

#### Grafana (Metrics Dashboards)
Open `http://THE_IP:8100`

1. Log in with username `admin` and the password you set in `.env`
   (`GRAFANA_ADMIN_PASS`)
2. Prometheus is already configured as a data source (auto-provisioned)
3. Import community dashboards:
   - Go to **Dashboards > New > Import**
   - **Node Exporter Full**: paste ID `1860`, click Load, select
     Prometheus as the data source, click Import
   - **Docker/cAdvisor**: paste ID `14282`, click Load, select
     Prometheus, click Import
4. You should immediately see host metrics (CPU, RAM, disk, network)
   and per-container metrics

*Give Prometheus 2-3 minutes after startup to scrape its first round
of metrics before the dashboards populate.*

---

#### Kavita (Comics/Manga/Book Reader)
Open `http://THE_IP:8101`

1. Create an admin account
2. Add libraries: **Settings > Libraries > Add Library**
   - Name: `Comics` — Folders: `/comics` — Type: Comic
   - Name: `Books` — Folders: `/books` — Type: Book
3. Kavita scans the directories and indexes your content
4. Get your credentials ready for the Homepage widget (next step)

*Content goes in `/srv/media/books` and `/srv/media/comics` on the host.
You can use Syncthing to push files from your laptop/phone, or just
SCP/rsync them over.*

---

#### Calibre-Web (Ebook Server)
Open `http://THE_IP:8102`

1. Log in with default credentials: `admin` / `admin123`
2. **IMMEDIATELY change the admin password** (Admin > Edit User)
3. Set the Calibre library location to: `/books`
4. Calibre-Web needs a `metadata.db` file in the books directory

**If you don't have a Calibre library yet:**
- Install [Calibre](https://calibre-ebook.com/) on your laptop
- Create a new library, add a couple of books
- Copy the library folder contents to `/srv/media/books` on the HP
- The key file is `metadata.db` — Calibre-Web won't start without it

**If you already have a Calibre library:**
- Copy it to `/srv/media/books` on the HP
- Calibre-Web picks up the existing `metadata.db` automatically

*Calibre-Web and Kavita can share the same `/srv/media/books` directory.
Kavita reads the files directly (read-only mount). Calibre-Web manages
metadata through its own database.*

---

#### Profilarr (TRaSH Profile Sync)
Open `http://THE_IP:8103`

1. Connect Sonarr:
   - URL: `http://sonarr:8989`
   - API Key: your Sonarr API key (from `.env` or Sonarr > Settings > General)
2. Connect Radarr:
   - URL: `http://radarr:7878`
   - API Key: your Radarr API key
3. Import TRaSH Guides profiles and custom formats
4. Profilarr keeps them in sync automatically

---

### 6. Wire up the Homepage dashboard

Add the Kavita credentials to `.env` so the Homepage widget shows data:

```bash
nano .env
```

Add:
```bash
KAVITA_USER=your-kavita-username
KAVITA_PASS=your-kavita-password
```

Then reload Homepage:
```bash
docker compose up -d homepage
```

*Remember: `docker compose restart` does NOT reload environment
variables. Always use `docker compose up -d` when you change `.env`.*

---

### 7. Verify everything works

Open these URLs in your browser:

| What | URL | What you should see |
|------|-----|---------------------|
| Dashboard | `http://THE_IP` | All services with status badges |
| Grafana | `http://THE_IP:8100` | Metrics dashboards |
| Kavita | `http://THE_IP:8101` | Library with your books/comics |
| Calibre-Web | `http://THE_IP:8102` | Ebook library |
| Profilarr | `http://THE_IP:8103` | Connected to Sonarr/Radarr |

Verify Prometheus is scraping all targets:
```bash
curl -s http://localhost:9090/api/v1/targets | python3 -m json.tool | grep health
```
You should see three `"up"` entries (prometheus, node-exporter, cadvisor).

---

### 8. Add monitors in Uptime Kuma

Go to `http://THE_IP:8090` and add HTTP monitors for each new service.
Use the container names (not the host IP) since they're on the same
Docker network:

| Monitor | Type | URL |
|---------|------|-----|
| Grafana | HTTP(s) | `http://grafana:3000` |
| Prometheus | HTTP(s) | `http://prometheus:9090` |
| Node Exporter | HTTP(s) | `http://node-exporter:9100` |
| cAdvisor | HTTP(s) | `http://cadvisor:8080` |
| Kavita | HTTP(s) | `http://kavita:5000` |
| Calibre-Web | HTTP(s) | `http://calibre-web:8083` |
| Profilarr | HTTP(s) | `http://profilarr:6868` |

Add them to your "default" status page so the Homepage widget picks
them up.

---

## After It's Running

**Grafana dashboard recommendations:**
- **Node Exporter Full** (ID 1860) — the gold standard for host metrics.
  Shows CPU, RAM, disk I/O, network throughput, filesystem usage.
- **Docker/cAdvisor** (ID 14282) — per-container CPU, memory, network.
  Great for spotting which container is eating resources.
- You can create custom dashboards or import others from
  [grafana.com/grafana/dashboards](https://grafana.com/grafana/dashboards).

**Prometheus data retention** — set to 30 days by default. If you need
more history, edit `stacks/prometheus.yaml` and change
`--storage.tsdb.retention.time=30d` to whatever you want. More days =
more disk usage.

**Memory usage** — check how much RAM the full stack is using:
```bash
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}"
```
The monitoring stack (Prometheus + Grafana + Node Exporter + cAdvisor)
typically uses 300-500MB combined. If Grafana hits its 256m limit with
complex dashboards, increase it in `stacks/grafana.yaml`.

**Calibre-Web metadata.db** — this is the single most common issue.
If Calibre-Web shows "DB Location is not Valid," the `metadata.db` file
is missing from `/srv/media/books`. Create one with Calibre desktop.

**Volumes to back up** — Phase 3 adds these to your backup list:
`prometheus_data`, `grafana_data`, `kavita_config`, `calibreweb_config`,
`profilarr_config`.

---

## If Something Goes Wrong

**Container won't start:**
```bash
docker compose logs SERVICE_NAME
```

**Prometheus "no data" in Grafana:**
- Wait 2-3 minutes after startup for the first scrape
- Check targets: `curl http://localhost:9090/api/v1/targets`
- All three targets should show `"health":"up"`

**cAdvisor won't start (cgroup errors):**
- Ubuntu 22.04+ uses cgroup v2 by default
- Version v0.51.0 supports cgroup v2, but if you see errors:
  ```bash
  docker compose logs cadvisor
  ```
- If it mentions "mountpoint for cpu not found," your kernel may need
  cgroup v1 compatibility. This is rare on standard Ubuntu installs.

**Grafana "permission denied" on startup:**
- Grafana runs as UID 472 internally. If the volume was created by
  a different user, fix it:
  ```bash
  docker compose down grafana
  docker volume rm grafana_data
  docker compose up -d grafana
  ```

**Kavita can't find books:**
- Books must be in `/srv/media/books` on the host
- Check that the directory exists and has correct ownership:
  ```bash
  ls -la /srv/media/books/
  ```

**Calibre-Web "DB Location is not Valid":**
- The `/books` directory needs a `metadata.db` file
- Create one with Calibre desktop and copy it to `/srv/media/books/`

---

*That's Phase 3, chummer. You've got full observability into every
container and the host itself, a reading library for your books and
comics, and your *arr stack is running optimized TRaSH profiles
automatically. The HP box is now a proper home infrastructure node.
Next up would be Nextcloud for cloud storage replacement and WireGuard
for a traditional VPN gateway — but that's Phase 4 territory.*
