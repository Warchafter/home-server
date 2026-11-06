# Backups (Backrest → Backblaze B2)

The server is one NVMe. Until this is set up, a dead disk loses every app's
configuration, the Vaultwarden database *and* its backups at the same time.
Backrest (`stacks/backrest.yaml`) runs restic on a schedule: encrypted,
deduplicated, incremental snapshots sent to B2.

**What gets backed up:** Docker volumes (all app configs and databases,
including Vaultwarden and its daily dumps), this repo with `.env`, Syncthing
data, and the book/comic library.
**What doesn't:** movies/TV and downloads. They can be downloaded again, and
the Sonarr/Radarr databases that list them *are* backed up.

**Privacy:** restic encrypts on the server before upload. B2 stores only
ciphertext, and can see sizes and upload times, nothing else.

Cost: roughly 10–30 GB of data, about $0.06–0.18/month on B2 ($6/TB).

---

## 1. Backblaze B2

1. Create a B2 account and a **private** bucket, e.g. `home-server-restic-<random>`.
   - *Lifecycle settings:* **Keep only the last version** (restic manages its own history).
   - *Default encryption:* on (SSE-B2), as defence in depth on top of restic.
2. *Application Keys → Add a New Application Key:* allow access to **that bucket
   only**, Read and Write. Note the `keyID`, the `applicationKey` and the bucket's
   S3 endpoint (e.g. `s3.us-west-004.backblazeb2.com`).
3. On the server, add to `.env`:
   ```bash
   BACKREST_B2_KEY_ID=<keyID>
   BACKREST_B2_APP_KEY=<applicationKey>
   ```

## 2. First start (finish it immediately — the UI is open until you do)

```bash
cd ~/home-server
docker compose up -d backrest
```

Open `http://SERVER_IP:8106`, set an instance ID (`home-server`), a username,
and a long unique password (store it in Vaultwarden).

## 3. Add the repository

*Repositories → Add Repository:*

| Field | Value |
|---|---|
| Name | `b2` |
| URI | `s3:https://s3.<region>.backblazeb2.com/<bucket>/home-server` |
| Password | generate a long random one (`openssl rand -base64 32`) |
| Env vars | none (the AWS_* keys come from `.env`) |
| Prune policy | weekly, max unused 10% |
| Check policy | monthly, read 5% of data |

**Store the repository password in two places that survive the server dying:**
Vaultwarden, since clients keep an offline copy of the vault, *and* paper or a
second password manager. Without it the backups can't be decrypted, by you
or by anyone else.

## 4. Add the plan

*Plans → Add Plan:*

| Field | Value |
|---|---|
| Repository | `b2` |
| Paths | `/userdata` |
| Excludes | see below |
| Schedule | daily, 03:00 |
| Retention | time-bucketed: 7 daily, 4 weekly, 12 monthly |

Excludes (one per line):
```
/userdata/docker-volumes/backrest_*
/userdata/docker-volumes/prometheus_data
/userdata/docker-volumes/diun_data
/userdata/docker-volumes/autoheal_sock
/userdata/docker-volumes/*/_data/**/cache
/userdata/docker-volumes/*/_data/**/Cache
/userdata/docker-volumes/*/_data/**/logs
/userdata/docker-volumes/*/_data/**/transcodes
/userdata/docker-volumes/*jellyfin_config/_data/metadata
/userdata/home-server/.git
```
Prometheus history and Jellyfin's downloaded artwork come back on their own.
The Backrest volumes are excluded so it doesn't back up its own cache.

*Hooks (optional):* add a Discord or Telegram hook on **CONDITION_SNAPSHOT_ERROR**
and **CONDITION_ANY_ERROR**, so a failing backup alerts you instead of failing
silently.

Run the plan once by hand (*Backup Now*) and watch the first snapshot finish.

## 5. Test a restore (do this once now, then every few months)

*Snapshots → pick one → Restore*, path `/userdata/docker-volumes/vaultwarden_backup`,
target `/restore/test`. Then on the server:
```bash
docker run --rm -v backrest_restore:/r busybox ls -la /r/test
```
You should see the dated Vaultwarden dump files. Clear the scratch volume afterwards
(*Snapshots → Restore* writes only to `/restore`; everything else is mounted read-only):
```bash
docker run --rm -v backrest_restore:/r busybox sh -c 'rm -rf /r/*'
```

## Restoring for real

Live SQLite files are copied while the apps run. For anything with a
database, restore the app's **own** backup first:

| App | Consistent copy inside the snapshot |
|---|---|
| Vaultwarden | `vaultwarden_backup` volume (daily dump) → `docker exec -it vaultwarden-backup restore` |
| Sonarr / Radarr / Prowlarr | `<app>_config/_data/Backups/scheduled/*.zip` → *System → Backup → Restore* |
| Home Assistant | `homeassistant_config/_data/backups/*.tar` |
| Everything else | stop the container, restore its volume's `_data`, start it |

Full disaster recovery on a new machine: install Ubuntu + Docker, restore
`/userdata/home-server` (repo + `.env`), run `bash scripts/setup.sh`, create
the volumes with `docker compose create`, restore each `docker-volumes/<name>/_data`
into `/var/lib/docker/volumes/<name>/_data` with the containers stopped, then
`docker compose up -d`.

## Later: a local copy (3-2-1)

B2 is the offsite copy. Once the SATA drive is in, add a second repository
pointing at it (for example `/backup` mounted read-write only for Backrest) and a second
plan with the same paths. That gives you fast local restores, and a copy that
doesn't depend on the internet connection or B2.
