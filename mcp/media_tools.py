"""Media-tree forensics on the read-only /media mount: sizes with hardlink
awareness, and the download-orphan analysis that found 86 GB in Oct 2026."""

import asyncio
import os
import time
from collections import defaultdict

from core import DOWNLOADS_COMPLETE, DOWNLOADS_INCOMPLETE, MEDIA_ROOT, human_bytes, mcp


def _safe_path(rel: str) -> str:
    root = os.path.realpath(MEDIA_ROOT)
    full = os.path.realpath(os.path.join(root, rel.strip("/")))
    if full != root and not full.startswith(root + os.sep):
        raise ValueError(f"path escapes the media root: {rel!r}")
    return full


def _walk_stats(path: str) -> dict:
    """Bytes under `path`, split by link count. Files with st_nlink == 1 exist
    nowhere else; st_nlink > 1 means the bytes are shared with another path
    (e.g. a Sonarr import hardlinked from downloads/)."""
    total = unique = shared = 0
    files = 0
    newest = 0.0
    seen: set[tuple[int, int]] = set()
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            st = e.stat(follow_symlinks=False)
                            key = (st.st_dev, st.st_ino)
                            if key in seen:
                                continue  # same inode reached twice inside this subtree
                            seen.add(key)
                            files += 1
                            total += st.st_size
                            if st.st_nlink > 1:
                                shared += st.st_size
                            else:
                                unique += st.st_size
                            newest = max(newest, st.st_mtime)
                    except OSError:
                        continue
        except OSError:
            continue
    return {"bytes": total, "unique_bytes": unique, "shared_bytes": shared, "files": files, "newest_mtime": newest}


def _usage(rel: str, top: int) -> dict:
    base = _safe_path(rel)
    entries = []
    with os.scandir(base) as it:
        for e in it:
            try:
                if e.is_dir(follow_symlinks=False):
                    s = _walk_stats(e.path)
                    kind = "dir"
                elif e.is_file(follow_symlinks=False):
                    st = e.stat(follow_symlinks=False)
                    s = {"bytes": st.st_size, "unique_bytes": st.st_size if st.st_nlink == 1 else 0, "shared_bytes": st.st_size if st.st_nlink > 1 else 0, "files": 1, "newest_mtime": st.st_mtime}
                    kind = "file"
                else:
                    continue
            except OSError:
                continue
            entries.append({"name": e.name, "kind": kind, **s})
    entries.sort(key=lambda x: -x["bytes"])
    tot = sum(x["bytes"] for x in entries)
    uniq = sum(x["unique_bytes"] for x in entries)
    out = [
        {
            "name": x["name"],
            "kind": x["kind"],
            "size": human_bytes(x["bytes"]),
            "unique": human_bytes(x["unique_bytes"]),
            "shared": human_bytes(x["shared_bytes"]),
            "files": x["files"],
            "newest": time.strftime("%Y-%m-%d", time.gmtime(x["newest_mtime"])) if x["newest_mtime"] else None,
        }
        for x in entries[:top]
    ]
    try:
        sv = os.statvfs(base)
        fs = {"size": human_bytes(sv.f_frsize * sv.f_blocks), "avail_to_services": human_bytes(sv.f_frsize * sv.f_bavail), "used_pct_for_services": round((1 - sv.f_bavail / sv.f_blocks) * 100, 1)}
    except OSError:
        fs = None
    return {"path": "/" + rel.strip("/"), "entries": out, "total": human_bytes(tot), "total_unique": human_bytes(uniq), "total_shared": human_bytes(tot - uniq), "filesystem": fs,
            "note": "unique = bytes in files with a single hard link (exist nowhere else); shared = hardlinked elsewhere, e.g. downloads <-> library, counted once per subtree"}


@mcp.tool()
async def media_usage(path: str = "", top: int = 30) -> dict:
    """Disk usage of the media tree, one level under `path` (relative to the
    media root, e.g. "" or "tv" or "downloads/complete"), hardlink-aware.

    Each entry shows total size, how much is unique (single hard link) vs
    shared with another path, file count and newest file date. Also reports
    the filesystem's space as seen by non-root services. Walks the tree on
    every call; a 200 GB library takes a second or two.
    """
    return await asyncio.to_thread(_usage, path, max(1, min(int(top), 200)))


def _orphans(min_size_mb: float, top: int) -> dict:
    base = _safe_path(DOWNLOADS_COMPLETE)
    min_bytes = min_size_mb * 1024 * 1024
    groups: dict[str, dict] = defaultdict(lambda: {"bytes": 0, "files": 0})
    orphan_bytes = orphan_files = small_orphan_bytes = linked_bytes = linked_files = 0
    base_len = len(base.rstrip(os.sep)) + 1
    stack = [base]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                            continue
                        if not e.is_file(follow_symlinks=False):
                            continue
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if st.st_nlink > 1:
                        linked_bytes += st.st_size
                        linked_files += 1
                        continue
                    if st.st_size < min_bytes:
                        small_orphan_bytes += st.st_size
                        continue
                    orphan_bytes += st.st_size
                    orphan_files += 1
                    top_name = e.path[base_len:].split(os.sep, 1)[0]
                    g = groups[top_name]
                    g["bytes"] += st.st_size
                    g["files"] += 1
        except OSError:
            continue
    ranked = sorted(groups.items(), key=lambda kv: -kv[1]["bytes"])
    try:
        inc = _walk_stats(_safe_path(DOWNLOADS_INCOMPLETE))
        incomplete = {"size": human_bytes(inc["bytes"]), "files": inc["files"]}
    except (OSError, ValueError):
        incomplete = None
    return {
        "scanned": "/" + DOWNLOADS_COMPLETE,
        "min_size_mb": min_size_mb,
        "orphans": {"files": orphan_files, "reclaimable": human_bytes(orphan_bytes), "reclaimable_bytes": orphan_bytes},
        "small_orphans_ignored": human_bytes(small_orphan_bytes),
        "hardlinked_into_library": {"files": linked_files, "size": human_bytes(linked_bytes)},
        "incomplete_downloads": incomplete,
        "by_torrent": [{"name": n, "size": human_bytes(g["bytes"]), "files": g["files"]} for n, g in ranked[:top]],
        "meaning": (
            "orphans = files with a single hard link under downloads/complete: the library copy was "
            "deleted (or never imported) and only the seeding torrent holds the bytes. Deleting in "
            "Sonarr/Radarr never frees these. Reclaim by removing the torrent in qBittorrent with "
            "'Remove and delete files', or on the server: "
            f"sudo find {os.path.join('/srv/media', DOWNLOADS_COMPLETE)} -type f -links 1 -size +{int(min_size_mb)}M -delete "
            "&& docker compose restart qbittorrent, then remove the Errored torrents in its UI."
        ),
    }


@mcp.tool()
async def download_orphans(min_size_mb: float = 100, top: int = 40) -> dict:
    """Find download data that exists nowhere else: files under
    downloads/complete with a single hard link and size >= `min_size_mb`,
    grouped by torrent folder, plus how much is still hardlinked into the
    library and how much sits in downloads/incomplete.

    This is the check that explained the Oct 2026 disk-full: deleting shows in
    Sonarr/Radarr only drops the library link; the torrent copy keeps the
    bytes. The size floor keeps .nfo/screenshot files out of the list so
    torrents whose video is still in the library are left alone.
    """
    return await asyncio.to_thread(_orphans, float(min_size_mb), max(1, min(int(top), 200)))
