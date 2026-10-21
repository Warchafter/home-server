"""The apps' own view of things: Sonarr/Radarr/Prowlarr/Bazarr health and
queues, qBittorrent torrents and seeding limits, Jellyfin library/scan state
and stale entries, and the DNS path containers actually use."""

import asyncio
import os
import socket
import time
from collections import Counter, defaultdict

import httpx

from core import (
    APP_TIMEOUT,
    ARR,
    HOST_RESOLVE_DIR,
    JELLYFIN_API_KEY,
    MEDIA_ROOT,
    QB_PASS,
    QB_URL,
    QB_USER,
    TAILSCALE_MAGIC_DNS,
    arr_configured,
    arr_get,
    human_bytes,
    iso,
    jellyfin_get,
    mcp,
)
from docker_tools import _fetch_logs


async def _try(coro, default=None):
    """Run a sub-request; on failure return `default` or the error text."""
    try:
        return await coro
    except Exception as e:  # noqa: BLE001
        return default if default is not None else {"error": str(e)[:200]}


# ---------------------------------------------------------------------------
# Sonarr / Radarr / Prowlarr / Bazarr
# ---------------------------------------------------------------------------

def _queue_record(app: str, r: dict) -> dict:
    title = r.get("title")
    parent = (r.get("series") or {}).get("title") if app == "sonarr" else (r.get("movie") or {}).get("title")
    msgs = [m for s in (r.get("statusMessages") or []) for m in (s.get("messages") or [])]
    return {
        "title": title,
        "for": parent,
        "status": r.get("status"),
        "tracked": f"{r.get('trackedDownloadStatus')}/{r.get('trackedDownloadState')}",
        "size": human_bytes(r.get("size") or 0),
        "left": human_bytes(r.get("sizeleft") or 0),
        "client": r.get("downloadClient"),
        "messages": msgs[:3] or ([r["errorMessage"]] if r.get("errorMessage") else []),
    }


async def arr_overview(app: str) -> dict:
    if app in ("sonarr", "radarr"):
        unknown = "includeUnknownSeriesItems" if app == "sonarr" else "includeUnknownMovieItems"
        include = "includeSeries" if app == "sonarr" else "includeMovie"
        items_path = "series" if app == "sonarr" else "movie"
        status, health, queue, disk, roots, missing, items = await asyncio.gather(
            _try(arr_get(app, "system/status")),
            _try(arr_get(app, "health"), []),
            _try(arr_get(app, "queue", {"page": 1, "pageSize": 100, unknown: "true", include: "true"}), {}),
            _try(arr_get(app, "diskspace"), []),
            _try(arr_get(app, "rootfolder"), []),
            _try(arr_get(app, "wanted/missing", {"pageSize": 1, "monitored": "true"}), {}),
            _try(arr_get(app, items_path), []),
        )
        records = queue.get("records", []) if isinstance(queue, dict) else []
        attention = [r for r in records if r.get("trackedDownloadStatus") in ("warning", "error") or r.get("status") in ("warning", "failed")]
        return {
            "app": app,
            "version": status.get("version") if isinstance(status, dict) else None,
            "health": [{"type": h.get("type"), "message": h.get("message")} for h in health] if isinstance(health, list) else health,
            "library": {"items": len(items), "monitored": sum(1 for i in items if i.get("monitored"))} if isinstance(items, list) else items,
            "wanted_missing": missing.get("totalRecords") if isinstance(missing, dict) else missing,
            "queue": {"total": queue.get("totalRecords") if isinstance(queue, dict) else None, "needs_attention": len(attention), "items": [_queue_record(app, r) for r in records[:25]]},
            "root_folders": [{"path": r.get("path"), "accessible": r.get("accessible"), "free": human_bytes(r.get("freeSpace") or 0), "unmapped_folders": len(r.get("unmappedFolders") or [])} for r in roots] if isinstance(roots, list) else roots,
            "disk": [{"path": d.get("path"), "free": human_bytes(d.get("freeSpace") or 0), "total": human_bytes(d.get("totalSpace") or 0)} for d in disk] if isinstance(disk, list) else disk,
        }
    if app == "prowlarr":
        status, health, indexers, istatus = await asyncio.gather(
            _try(arr_get(app, "system/status")),
            _try(arr_get(app, "health"), []),
            _try(arr_get(app, "indexer"), []),
            _try(arr_get(app, "indexerstatus"), []),
        )
        st = {s.get("indexerId"): s for s in istatus} if isinstance(istatus, list) else {}
        rows = []
        for i in indexers if isinstance(indexers, list) else []:
            s = st.get(i.get("id"), {})
            rows.append({"name": i.get("name"), "enabled": i.get("enable"), "disabled_until": s.get("disabledTill"), "last_failure": s.get("mostRecentFailure")})
        return {
            "app": app,
            "version": status.get("version") if isinstance(status, dict) else None,
            "health": [{"type": h.get("type"), "message": h.get("message")} for h in health] if isinstance(health, list) else health,
            "indexers": rows,
            "indexers_in_backoff": [r["name"] for r in rows if r["disabled_until"]],
        }
    status, health = await asyncio.gather(_try(arr_get(app, "system/status")), _try(arr_get(app, "system/health"), {}))
    issues = health.get("data", []) if isinstance(health, dict) else health
    return {
        "app": app,
        "version": (status.get("data") or {}).get("bazarr_version") if isinstance(status, dict) else None,
        "health": [{"object": h.get("object"), "issue": h.get("issue")} for h in issues] if isinstance(issues, list) else issues,
    }


@mcp.tool()
async def arr_status(app: str) -> dict:
    """What Sonarr, Radarr, Prowlarr or Bazarr think is wrong, in their own
    words: health warnings, the download queue with per-item status messages
    (import blocked, unknown series, client errors), wanted/missing counts,
    root-folder accessibility and free space, library size. Prowlarr adds
    per-indexer backoff state. Read-only; needs the app's API key in .env.
    """
    app = app.lower().strip()
    if app not in ARR:
        raise ValueError(f"app must be one of {', '.join(ARR)}")
    if not arr_configured(app):
        return {"app": app, "configured": False, "hint": f"set {app.upper()}_API_KEY in .env (the key Homepage already uses) and recreate the mcp container"}
    return await arr_overview(app)


# ---------------------------------------------------------------------------
# qBittorrent
# ---------------------------------------------------------------------------

_QB_GROUPS = {
    "downloading": {"downloading", "stalledDL", "metaDL", "forcedDL", "queuedDL", "checkingDL", "forcedMetaDL"},
    "seeding": {"uploading", "stalledUP", "forcedUP", "queuedUP", "checkingUP"},
    "paused": {"pausedDL", "pausedUP", "stoppedDL", "stoppedUP"},
    "errored": {"error", "missingFiles"},
}
_QB_ATTENTION = {"error", "missingFiles", "stalledDL", "metaDL"}
_QB_RATIO_ACT = {0: "pause", 1: "remove", 2: "enable super seeding", 3: "remove with content"}


async def _qb_client() -> httpx.AsyncClient:
    if not QB_PASS:
        raise RuntimeError("qbittorrent: QBITTORRENT_PASS not configured in .env")
    client = httpx.AsyncClient(base_url=QB_URL, timeout=APP_TIMEOUT, headers={"Referer": QB_URL, "Origin": QB_URL})
    try:
        r = await client.post("/api/v2/auth/login", data={"username": QB_USER, "password": QB_PASS})
        if r.text.strip() != "Ok.":
            raise RuntimeError(f"qbittorrent login failed: HTTP {r.status_code} {r.text.strip()[:80]}")
    except Exception:
        await client.aclose()
        raise
    return client


def _torrent(t: dict) -> dict:
    eta = t.get("eta")
    return {
        "name": t.get("name"),
        "state": t.get("state"),
        "progress": round((t.get("progress") or 0) * 100, 1),
        "size": human_bytes(t.get("size") or 0),
        "ratio": round(t.get("ratio") or 0, 2),
        "category": t.get("category") or None,
        "save_path": t.get("save_path"),
        "added": iso(t.get("added_on")),
        "last_activity": iso(t.get("last_activity")),
        "seeds": t.get("num_seeds"),
        "eta_min": None if eta in (None, 8640000) else round(eta / 60),
    }


async def qb_overview(state: str = "all", limit: int = 50) -> dict:
    client = await _qb_client()
    try:
        version, transfer, prefs, torrents = await asyncio.gather(
            client.get("/api/v2/app/version"),
            client.get("/api/v2/transfer/info"),
            client.get("/api/v2/app/preferences"),
            client.get("/api/v2/torrents/info"),
        )
    finally:
        await client.aclose()
    transfer, prefs, torrents = transfer.json(), prefs.json(), torrents.json()
    counts = Counter(t.get("state") for t in torrents)
    attention = [t for t in torrents if t.get("state") in _QB_ATTENTION or (t.get("state") in _QB_GROUPS["paused"] and (t.get("progress") or 0) < 1)]
    if state == "all":
        chosen = torrents
    elif state in _QB_GROUPS:
        chosen = [t for t in torrents if t.get("state") in _QB_GROUPS[state]]
    else:
        chosen = [t for t in torrents if t.get("state") == state]
    chosen = sorted(chosen, key=lambda t: -(t.get("added_on") or 0))[:limit]
    return {
        "version": version.text.strip(),
        "connection": transfer.get("connection_status"),
        "speeds": {"down": human_bytes(transfer.get("dl_info_speed") or 0) + "/s", "up": human_bytes(transfer.get("up_info_speed") or 0) + "/s"},
        "torrents_total": len(torrents),
        "by_state": dict(counts),
        "needs_attention": [_torrent(t) for t in attention[:25]],
        "seeding_limits": {
            "ratio": prefs.get("max_ratio") if prefs.get("max_ratio_enabled") else "off",
            "seeding_time_min": prefs.get("max_seeding_time") if prefs.get("max_seeding_time_enabled") else "off",
            "action_when_reached": _QB_RATIO_ACT.get(prefs.get("max_ratio_act"), prefs.get("max_ratio_act")),
        },
        "paths": {"save": prefs.get("save_path"), "incomplete": prefs.get("temp_path") if prefs.get("temp_path_enabled") else None},
        "queueing": {"enabled": prefs.get("queueing_enabled"), "max_active_downloads": prefs.get("max_active_downloads")},
        "filter": state,
        "torrents": [_torrent(t) for t in chosen],
    }


@mcp.tool()
async def qbittorrent_status(state: str = "all", limit: int = 50) -> dict:
    """qBittorrent's view: connection state and speeds, torrent counts by
    state, every torrent needing attention (errored, missing files, stalled,
    paused-incomplete), seeding-limit settings (ratio / time / action — the
    thing that decides whether deleted shows ever free space), and a torrent
    list filtered by `state`: all, downloading, seeding, paused, errored, or
    an exact qBittorrent state name. Read-only.
    """
    if not QB_PASS:
        return {"configured": False, "hint": "set QBITTORRENT_USER/QBITTORRENT_PASS in .env and recreate the mcp container"}
    return await qb_overview(state.strip() or "all", max(1, min(int(limit), 500)))


# ---------------------------------------------------------------------------
# Jellyfin
# ---------------------------------------------------------------------------

async def _jf_admin_user_id() -> str | None:
    users = await jellyfin_get("Users")
    if not users:
        return None
    admins = [u for u in users if (u.get("Policy") or {}).get("IsAdministrator")]
    return (admins or users)[0].get("Id")


def _exists_batch(paths: list[str]) -> list[bool]:
    return [os.path.exists(p) for p in paths]


async def jellyfin_stale_items(limit_groups: int = 25) -> dict:
    """Library entries whose Path no longer exists on the shared media mount."""
    uid = await _jf_admin_user_id()
    base = f"Users/{uid}/Items" if uid else "Items"
    items, start, total = [], 0, None
    while total is None or start < total:
        page = await jellyfin_get(base, {"Recursive": "true", "IncludeItemTypes": "Movie,Series,Season,Episode", "Fields": "Path", "Limit": 2000, "StartIndex": start})
        batch = page.get("Items", []) if page else []
        total = page.get("TotalRecordCount", 0) if page else 0
        items.extend(batch)
        start += len(batch)
        if not batch:
            break
    paths = [(i.get("Type"), i.get("Path")) for i in items if i.get("Path") and i["Path"].startswith(MEDIA_ROOT + "/")]
    exists = await asyncio.to_thread(_exists_batch, [p for _, p in paths])
    stale = [(t, p) for (t, p), ok in zip(paths, exists) if not ok]
    groups: dict[str, int] = defaultdict(int)
    for _, p in stale:
        parts = p[len(MEDIA_ROOT) + 1:].split("/")
        groups["/".join(parts[:2])] += 1
    return {
        "items_checked": len(paths),
        "stale": len(stale),
        "stale_by_folder": [{"folder": k, "items": v} for k, v in sorted(groups.items(), key=lambda kv: -kv[1])[:limit_groups]],
        "hint": None if not stale else (
            "Jellyfin should remove these on its next refresh. If 'refresh_errors' below is non-zero it "
            "cannot (10.11 UNIQUE-constraint bug): run scripts/jellyfin-prune-stale-userdata.py on the server."
        ),
    }


async def jellyfin_overview(stale_check: bool = True) -> dict:
    info, folders, tasks, counts, sessions = await asyncio.gather(
        _try(jellyfin_get("System/Info")),
        _try(jellyfin_get("Library/VirtualFolders"), []),
        _try(jellyfin_get("ScheduledTasks"), []),
        _try(jellyfin_get("Items/Counts"), {}),
        _try(jellyfin_get("Sessions"), []),
    )
    scan = next((t for t in tasks if t.get("Name") == "Scan Media Library"), {}) if isinstance(tasks, list) else {}
    last = scan.get("LastExecutionResult") or {}
    logs = await _try(_fetch_logs("jellyfin", 5000, "24h"), "")
    refresh_errors = sum(1 for line in logs.splitlines() if "UNIQUE constraint" in line or "Error refreshing item" in line)
    playing = [s for s in sessions if s.get("NowPlayingItem")] if isinstance(sessions, list) else []
    out = {
        "version": info.get("Version") if isinstance(info, dict) else None,
        "pending_restart": info.get("HasPendingRestart") if isinstance(info, dict) else None,
        "libraries": [{"name": f.get("Name"), "type": f.get("CollectionType"), "paths": f.get("Locations")} for f in folders] if isinstance(folders, list) else folders,
        "counts": {k: counts.get(k) for k in ("MovieCount", "SeriesCount", "EpisodeCount")} if isinstance(counts, dict) else counts,
        "library_scan": {"state": scan.get("State"), "last_status": last.get("Status"), "last_start": last.get("StartTimeUtc"), "last_end": last.get("EndTimeUtc"), "last_error": last.get("ErrorMessage")},
        "refresh_errors_24h": refresh_errors,
        "active_sessions": [{"user": s.get("UserName"), "client": s.get("Client"), "playing": (s.get("NowPlayingItem") or {}).get("Name"), "transcoding": bool(s.get("TranscodingInfo"))} for s in playing],
    }
    if stale_check:
        out["stale_items"] = await _try(jellyfin_stale_items())
    return out


@mcp.tool()
async def jellyfin_status(stale_check: bool = True) -> dict:
    """Jellyfin's state: version, libraries and their paths, item counts, the
    last library scan (status/time/error), refresh errors in the last 24h of
    logs (UNIQUE constraint / Error refreshing item = the 10.11 bug that
    blocks new shows from appearing), active playback sessions, and with
    `stale_check` the library entries whose files no longer exist on disk,
    grouped by folder. Read-only; needs JELLYFIN_API_KEY.
    """
    if not JELLYFIN_API_KEY:
        return {"configured": False, "hint": "set JELLYFIN_API_KEY in .env and recreate the mcp container"}
    return await jellyfin_overview(stale_check)


# ---------------------------------------------------------------------------
# DNS
# ---------------------------------------------------------------------------

def _nameservers(path: str) -> list[str] | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return [line.split()[1] for line in f if line.startswith("nameserver") and len(line.split()) > 1]
    except OSError:
        return None


async def dns_overview(hostname: str) -> dict:
    host_ns = _nameservers(os.path.join(HOST_RESOLVE_DIR, "resolv.conf"))
    stub_ns = _nameservers(os.path.join(HOST_RESOLVE_DIR, "stub-resolv.conf"))
    own_ns = _nameservers("/etc/resolv.conf")
    loop = asyncio.get_running_loop()
    t0 = time.monotonic()
    try:
        infos = await asyncio.wait_for(loop.getaddrinfo(hostname, None), timeout=10)
        v4 = sorted({i[4][0] for i in infos if i[0] == socket.AF_INET})
        v6 = sorted({i[4][0] for i in infos if i[0] == socket.AF_INET6})
        result = {"ok": True, "ipv4": v4, "ipv6": v6, "ms": round((time.monotonic() - t0) * 1000)}
    except Exception as e:  # noqa: BLE001
        result = {"ok": False, "error": str(e)[:200], "ms": round((time.monotonic() - t0) * 1000)}
    tailscale = bool(host_ns) and TAILSCALE_MAGIC_DNS in host_ns
    verdict = []
    if host_ns is None:
        verdict.append("host resolv.conf not mounted (/host/resolve) — host DNS state unknown")
    elif tailscale:
        verdict.append(f"host uplink DNS lists {TAILSCALE_MAGIC_DNS} (Tailscale MagicDNS) — containers without a dns: pin will SERVFAIL; fix: sudo tailscale set --accept-dns=false")
    if not result["ok"]:
        verdict.append("lookup from this container FAILED — any container inheriting host DNS is broken too")
    return {
        "hostname": hostname,
        "lookup_from_mcp_container": result,
        "mcp_container_resolv_conf": own_ns,
        "host_uplink_nameservers": host_ns,
        "host_stub_nameservers": stub_ns,
        "tailscale_in_host_dns": tailscale,
        "verdict": verdict or ["ok"],
        "note": "the mcp container has no dns: pin on purpose — it resolves the way an unpinned container would, so this is the canary for the host-inherited path",
    }


@mcp.tool()
async def dns_check(hostname: str = "relays.syncthing.net") -> dict:
    """Is container DNS healthy? Resolves `hostname` from inside the mcp
    container (which deliberately inherits host DNS like an unpinned
    container would) and reads the host's systemd-resolved nameserver list,
    flagging Tailscale's 100.100.100.100 — the thing that broke Syncthing and
    Jellyfin lookups twice. Also shows the mcp container's own resolv.conf.
    """
    return await dns_overview(hostname.strip() or "relays.syncthing.net")
