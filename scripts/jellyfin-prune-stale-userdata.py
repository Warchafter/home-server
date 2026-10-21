#!/usr/bin/env python3
"""
jellyfin-prune-stale-userdata.py — unstick Jellyfin 10.11 library refreshes.

Jellyfin 10.11 (still broken in 10.11.11; fixed only in 12.0) can abort EVERY
library refresh with:
    SQLite Error 19: 'UNIQUE constraint failed: UserData.ItemId, UserData.UserId, UserData.CustomDataKey'
It happens when Jellyfin removes an item whose files are gone and tries to
tombstone that item's watch-state rows. Symptoms: shows deleted in Sonarr or
Radarr linger with blank posters, and NEW shows never appear, because the
refresh dies before it reaches them. Upstream: jellyfin/jellyfin#16975, #15343.

Fix: delete the UserData rows that belong to library items whose file or
folder no longer exists on disk, so the removal has nothing to tombstone.
The only thing lost is watched-state for files that are already gone.

Run ON THE SERVER, as root (the Docker volume directory is root-only):
    cd ~/home-server && docker compose stop jellyfin
    sudo python3 scripts/jellyfin-prune-stale-userdata.py            # dry run: list what would go
    sudo python3 scripts/jellyfin-prune-stale-userdata.py --delete   # back up the DB, then delete
    docker compose start jellyfin
    # then Jellyfin > Dashboard > Libraries > Scan All Libraries, and confirm with
    # docker logs jellyfin --since 5m 2>&1 | grep -E 'Removing item|UNIQUE constraint|Scan Media Library'
"""

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONTAINER = "jellyfin"
VOLUME = "jellyfin_config"
CONTAINER_MEDIA = "/media"   # where the stacks mount MEDIA_PATH inside Jellyfin


def media_path() -> str:
    p = REPO / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if line.startswith("MEDIA_PATH="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "/srv/media"


def docker(*args: str) -> str:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=True).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--delete", action="store_true", help="actually delete (default is a dry run)")
    ap.add_argument("--db", help="path to jellyfin.db (default: found via `docker volume inspect`)")
    ap.add_argument("--force", action="store_true", help="proceed even if the jellyfin container is running")
    args = ap.parse_args()

    if os.geteuid() != 0:
        print("run with sudo: the Docker volume directory is only readable by root", file=sys.stderr)
        return 2

    try:
        running = docker("inspect", "-f", "{{.State.Running}}", CONTAINER) == "true"
    except subprocess.CalledProcessError:
        running = False
    if running and not args.force:
        print(f"{CONTAINER} is running. Stop it first: cd ~/home-server && docker compose stop {CONTAINER}", file=sys.stderr)
        return 2

    db_path = Path(args.db) if args.db else Path(docker("volume", "inspect", VOLUME, "-f", "{{.Mountpoint}}")) / "data" / "jellyfin.db"
    if not db_path.exists():
        print(f"database not found: {db_path}", file=sys.stderr)
        return 2

    host_media = media_path()
    db = sqlite3.connect(db_path)
    rows = db.execute("SELECT Id, Path FROM BaseItems WHERE Path LIKE ?", (CONTAINER_MEDIA + "/%",)).fetchall()
    stale = [(i, p) for i, p in rows if not os.path.exists(host_media + p[len(CONTAINER_MEDIA):])]
    ids = [i for i, _ in stale]

    print(f"database: {db_path}")
    print(f"library items checked: {len(rows)}   with missing file/folder: {len(stale)}")
    if not stale:
        print("nothing stale — if refreshes still fail, the cause is something else")
        return 0

    by_root = Counter(p.split("/")[3] if p.count("/") >= 3 else p for _, p in stale)
    for root, n in sorted(by_root.items()):
        print(f"  {n:>4}  {CONTAINER_MEDIA}/{'/'.join(next(p for _, p in stale if p.split('/')[3:4] == [root]).split('/')[2:4])}")
    marks = ",".join("?" * len(ids))
    n_ud = db.execute(f"SELECT count(*) FROM UserData WHERE ItemId IN ({marks})", ids).fetchone()[0]
    print(f"UserData rows attached to them: {n_ud}")

    if not args.delete:
        print("\ndry run — re-run with --delete to remove those UserData rows")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    owner_home = Path(os.path.expanduser("~" + os.environ.get("SUDO_USER", ""))) if os.environ.get("SUDO_USER") else Path.home()
    backup_dir = owner_home / f"jellyfin-db-backup-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        src = Path(str(db_path) + suffix)
        if src.exists():
            shutil.copy2(src, backup_dir / src.name)
    print(f"backup: {backup_dir}")

    cur = db.execute(f"DELETE FROM UserData WHERE ItemId IN ({marks})", ids)
    db.commit()
    db.close()
    print(f"deleted {cur.rowcount} UserData rows")
    print(f"now: cd ~/home-server && docker compose start {CONTAINER}, then Dashboard > Libraries > Scan All Libraries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
