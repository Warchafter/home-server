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

## 1. Backblaze B2 (delete-resistant)

The point of an offsite copy is surviving the server being compromised or
encrypted by ransomware, so **the key on the server must not be able to delete
backups.** On B2, deleting a file through the S3 API without a version ID only
*hides* it (that needs `writeFiles`). Permanently destroying a version needs
`deleteFiles`, and the server's key won't have it. Hidden versions are kept for
30 days by the lifecycle rule, so anything an attacker "deletes" can be brought back.

1. Create a B2 account and a **private** bucket, e.g. `home-server-restic-<random>`.
   - *Lifecycle settings:* **Keep prior versions for this number of days: 30**
     (not "keep only the last version", which would purge hidden files the next day).
   - *Default encryption:* on (SSE-B2), as defence in depth on top of restic.
2. Create the **server key without delete rights**. The web UI's "Read and Write"
   includes `deleteFiles`, so use the B2 CLI on the laptop (`pipx install b2`, then
   `b2 account authorize` with your master key; check `b2 key create --help`
   for the exact syntax on your version):
   ```bash
   b2 key create --bucket <bucket> home-server-restic listBuckets,listFiles,readFiles,writeFiles
   ```
   Note the `keyID` and `applicationKey`, plus the bucket's S3 endpoint (e.g.
   `s3.us-west-004.backblazeb2.com`). Keep the master key off the server; it
   is only for recovery.
3. Cost of this setup: pruned data lingers 30 days as hidden versions, which
   adds roughly a month of churn to storage. That's pennies at this size.
4. On the server, add to `.env`:
   ```bash
   BACKREST_B2_KEY_ID=<keyID>
   BACKREST_B2_APP_KEY=<applicationKey>
   ```

## 2. First start

Backrest's UI can read every volume and `.env` and run shell hooks as root, so
it is not routed through Caddy. It listens only on the server's
`127.0.0.1:9898`.

```bash
cd ~/home-server
docker compose up -d backrest
```

From the laptop, tunnel to it and open `http://localhost:9898`:
```bash
ssh -N -L 9898:127.0.0.1:9898 -o GSSAPIAuthentication=no wachacha@100.82.82.78
```
Run it **on the laptop** (not in an SSH session on the server). After the
password it prints nothing — that's the tunnel holding open; leave it running.
(`100.82.82.78` is the server's Tailscale IP; at home `192.168.0.117` also works.)
Set an instance ID (`home-server`), a username, and a long unique password
(store it in Vaultwarden). **Never tick "Disable authentication".**

For everyday remote access after docs/security-hardening.md §4 (machine
renamed, HTTPS certificates on), serve it on the tailnet with a real cert:
```bash
sudo tailscale serve --bg --https=8443 http://127.0.0.1:9898
```
→ `https://<machine>.<tailnet>.ts.net:8443`.

## 3. Add the repository

*Repositories → Add Repository:*

| Field | Value |
|---|---|
| Name | `b2` |
| URI | `s3:https://s3.<region>.backblazeb2.com/<bucket>/home-server` |
| Password | generate a long random one (`openssl rand -base64 32`) |
| Env vars | none (the AWS_* keys come from `.env`) |
| Prune policy | weekly, max unused 10% (with the no-delete key, pruned packs become hidden versions that B2 purges after 30 days) |
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

## If the server is ever compromised

1. From the laptop, with the B2 master key: `b2 ls --versions --recursive b2://<bucket>/`.
   Hidden ("deleted") files are still listed for 30 days. Restore with the B2 web UI
   (*Browse Files → Show all versions → unhide*), or copy the bucket at a past
   point in time with rclone `--b2-versions` / `--b2-version-at`.
2. Rotate the server's B2 key (`b2 key delete`, then create a new one with the same
   capabilities), and the restic password if `backrest_config` may have been read.

## Restoring for real

Live SQLite files are copied while the apps run. For anything with a
database, restore the app's **own** backup first:

| App | Consistent copy inside the snapshot |
|---|---|
| Vaultwarden | `vaultwarden_backup` volume (daily zip). Procedure in stacks/vaultwarden-backup.yaml (RESTORE) |
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
