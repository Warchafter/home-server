"""health_summary: the one-call digest. Containers, monitoring, resources,
host, disk, temperatures, network — plus what the apps themselves report."""

import asyncio

from apps import arr_overview, dns_overview, jellyfin_overview, qb_overview
from core import (
    ARR,
    JELLYFIN_API_KEY,
    QB_PASS,
    STUCK_STARTING_MIN,
    arr_configured,
    by_name,
    docker_get,
    human_bytes,
    mcp,
    prom_safe,
    up_minutes,
    val,
)
from media_tools import _orphans


async def _bounded(coro, seconds: float = 25):
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:160]}


@mcp.tool()
async def health_summary(window: str = "7d") -> str:
    """Full health digest in one call: container states (incl. containers
    stuck in health=starting, the crash-loop signature), Prometheus scrape
    health, container memory/restarts/CPU-throttle, host CPU/load/memory/swap,
    disk usage with time-to-full projection and reclaimable download orphans,
    temperatures, network drops, and a SERVICES section with what Sonarr,
    Radarr, Prowlarr, qBittorrent and Jellyfin report about themselves plus a
    DNS-path check.

    `window` sets the restart-count lookback (default "7d", max useful "30d").
    Lines flagged with <-- exceed a threshold and deserve attention. "no data"
    means Prometheus is not returning samples — on this box that has meant a
    full disk (its WAL stops writing and the head empties).
    """
    lines: list[str] = ["HOME SERVER HEALTH SUMMARY"]
    notes: list[str] = []

    # Kick off the slow app checks now; they run while the Prometheus part is built.
    app_tasks = {
        "sonarr": asyncio.create_task(_bounded(arr_overview("sonarr"))) if arr_configured("sonarr") else None,
        "radarr": asyncio.create_task(_bounded(arr_overview("radarr"))) if arr_configured("radarr") else None,
        "prowlarr": asyncio.create_task(_bounded(arr_overview("prowlarr"))) if arr_configured("prowlarr") else None,
        "qbittorrent": asyncio.create_task(_bounded(qb_overview("errored", 10))) if QB_PASS else None,
        "jellyfin": asyncio.create_task(_bounded(jellyfin_overview(True), 40)) if JELLYFIN_API_KEY else None,
        "dns": asyncio.create_task(_bounded(dns_overview("relays.syncthing.net"), 15)),
        "orphans": asyncio.create_task(_bounded(asyncio.to_thread(_orphans, 100.0, 5), 60)),
    }

    # Containers not running / unhealthy / stuck starting (dockerproxy)
    containers = await docker_get("/containers/json", params={"all": "true"})
    problems = []
    for c in containers:
        name, state, status = c["Names"][0].lstrip("/"), c["State"], c["Status"]
        note = None
        if state != "running":
            note = "not running"
        elif "unhealthy" in status:
            note = "unhealthy"
        elif "health: starting" in status:
            mins = up_minutes(status)
            if mins is not None and mins >= STUCK_STARTING_MIN:
                note = "stuck in health=starting — crash/restart loop?"
        if note:
            problems.append(f"  {name:<22}{state:<12}{status}  <-- {note}")
    lines.append(f"\n=== CONTAINER STATES ({len(containers)} total) ===")
    lines.extend(problems or ["  all running and healthy"])

    # Prometheus itself
    lines.append("\n=== MONITORING ===")
    targets = await prom_safe("up", notes)
    if not targets:
        lines.append("  no samples from Prometheus at all — storage unwritable (full disk?) or Prometheus down  <--")
    else:
        down = [f"{r['metric'].get('job', '?')} ({r['metric'].get('instance', '?')})" for r in targets if val(r) == 0]
        lines.append(f"  {len(targets)} scrape targets, {len(down)} down" + (f": {', '.join(down)}  <--" if down else ""))

    # Container resources (cAdvisor)
    usage = by_name(await prom_safe('container_memory_usage_bytes{name!=""}', notes))
    limit = by_name(await prom_safe('container_spec_memory_limit_bytes{name!=""}', notes))
    wset = by_name(await prom_safe('container_memory_working_set_bytes{name!=""}', notes))
    restarts = by_name(await prom_safe(f'changes(container_start_time_seconds{{name!=""}}[{window}])', notes))
    thr = by_name(await prom_safe('rate(container_cpu_cfs_throttled_periods_total{name!=""}[1h])', notes))
    per = by_name(await prom_safe('rate(container_cpu_cfs_periods_total{name!=""}[1h])', notes))
    lines.append(f"\n=== CONTAINERS — working set (usage incl. cache) vs limit, restarts/{window}, CPU throttle ===")
    if not usage:
        lines.append("  no data (cAdvisor metrics missing from Prometheus)")
    for name in sorted(usage):
        mem, lim, ws = usage[name], limit.get(name, 0), wset.get(name, usage[name])
        pct = ws / lim * 100 if lim > 0 else 0
        rs = int(restarts.get(name, 0))
        tpct = thr.get(name, 0) / per[name] * 100 if per.get(name, 0) > 0 else 0
        flag = "  <--" if (pct >= 85 or rs >= 3 or tpct >= 5) else ""
        lims = human_bytes(lim) if lim > 0 else "none"
        lines.append(
            f"  {name:<22}{human_bytes(ws):>9} ({human_bytes(mem):>8}) / {lims:<8} {pct:>4.0f}%"
            f"  restarts:{rs:<3} throttle:{tpct:.1f}%{flag}"
        )

    # Host
    lines.append("\n=== HOST ===")
    host_lines = 0
    for label, promql, fmt in (
        ("CPU busy", '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)', "{:.1f}%"),
        ("Load (1m)", "node_load1", "{:.2f}"),
        ("Mem available", "node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes * 100", "{:.1f}%"),
        ("Swap used (MB)", "(node_memory_SwapTotal_bytes - node_memory_SwapFree_bytes) / 1048576", "{:.0f}"),
    ):
        result = await prom_safe(promql, notes)
        if result:
            lines.append(f"  {label:<16}{fmt.format(val(result[0]))}")
            host_lines += 1
    if not host_lines:
        lines.append("  no data (node-exporter metrics missing from Prometheus)")

    # Disk + time-to-full projection (linear from last 6h)
    lines.append("\n=== DISK ===")
    fs = '{fstype!~"tmpfs|overlay|squashfs"}'
    avail = await prom_safe(f"node_filesystem_avail_bytes{fs}", notes)
    size = await prom_safe(f"node_filesystem_size_bytes{fs}", notes)
    predict = await prom_safe(f"predict_linear(node_filesystem_avail_bytes{fs}[6h], 7*86400)", notes)
    size_by_mp = {r["metric"].get("mountpoint"): val(r) for r in size}
    pred_by_mp = {r["metric"].get("mountpoint"): val(r) for r in predict}
    if not avail:
        lines.append("  no data (node-exporter filesystem metrics missing from Prometheus)")
    for r in sorted(avail, key=lambda x: x["metric"].get("mountpoint", "")):
        mp = r["metric"].get("mountpoint", "?")
        a, s = val(r), size_by_mp.get(mp, 0)
        used_pct = (s - a) / s * 100 if s > 0 else 0
        ttf = ""
        p7 = pred_by_mp.get(mp)
        if p7 is not None and p7 < a:
            slope = (a - p7) / (7 * 86400)
            if slope > 0:
                days = a / slope / 86400
                ttf = f"  full in ~{days:.1f}d" if days < 365 else ""
        flag = "  <--" if used_pct >= 85 else ""
        lines.append(f"  {mp:<14}{human_bytes(a):>10} free / {human_bytes(s)} ({used_pct:.0f}% used){ttf}{flag}")
    orph = await app_tasks["orphans"]
    if isinstance(orph, dict) and "orphans" in orph:
        o = orph["orphans"]
        inc = orph.get("incomplete_downloads") or {}
        flag = "  <--" if o["reclaimable_bytes"] >= 10 * 1024**3 else ""
        lines.append(f"  download orphans: {o['reclaimable']} in {o['files']} files (not in library; see download_orphans){flag}; incomplete: {inc.get('size', '?')}")
    elif isinstance(orph, dict) and "error" in orph:
        lines.append(f"  download orphans: unavailable ({orph['error']})")

    # Temperatures (NVMe hotspot has hit critical before — watch it)
    temps = await prom_safe("node_hwmon_temp_celsius", notes)
    if temps:
        lines.append("\n=== TEMPERATURES ===")
        for r in sorted(temps, key=lambda x: -val(x)):
            m = r["metric"]
            label = m.get("chip", "?") + "/" + (m.get("sensor") or "?")
            t = val(r)
            lines.append(f"  {label:<40}{t:>6.1f}C{'  <--' if t >= 75 else ''}")

    # Network drops on physical NICs
    drops = await prom_safe(
        'rate(node_network_receive_drop_total{device!~"lo|veth.*|docker.*|br.*|tailscale.*"}[5m])', notes
    )
    dropped = [f"  {r['metric'].get('device', '?'):<12}{val(r):.2f} drops/s  <--" for r in drops if val(r) > 0]
    lines.append("\n=== NETWORK ===")
    lines.extend(dropped or ["  no receive drops on physical NICs"])

    # What the apps say about themselves
    lines.append("\n=== SERVICES ===")
    for app in ("sonarr", "radarr", "prowlarr"):
        t = app_tasks[app]
        if t is None:
            lines.append(f"  {app:<12}not configured ({app.upper()}_API_KEY)")
            continue
        r = await t
        if "error" in r:
            lines.append(f"  {app:<12}error: {r['error']}  <--")
            continue
        health = r.get("health") or []
        bits = [f"v{r.get('version')}"]
        if isinstance(health, list):
            bits.append(f"{len(health)} health issue(s)" + (f": {health[0]['message'][:70]}" if health else ""))
        q = r.get("queue") or {}
        if q.get("total") is not None:
            bits.append(f"queue {q['total']} ({q['needs_attention']} need attention)")
        if r.get("wanted_missing") is not None:
            bits.append(f"missing {r['wanted_missing']}")
        if r.get("indexers_in_backoff"):
            bits.append(f"indexers in backoff: {', '.join(r['indexers_in_backoff'])}")
        bad_roots = [x["path"] for x in (r.get("root_folders") or []) if isinstance(x, dict) and x.get("accessible") is False]
        if bad_roots:
            bits.append(f"root folder inaccessible: {', '.join(bad_roots)}")
        flag = "  <--" if (health or q.get("needs_attention") or r.get("indexers_in_backoff") or bad_roots) else ""
        lines.append(f"  {app:<12}" + ", ".join(bits) + flag)
    t = app_tasks["qbittorrent"]
    if t is None:
        lines.append("  qbittorrent not configured (QBITTORRENT_PASS)")
    else:
        r = await t
        if "error" in r:
            lines.append(f"  qbittorrent error: {r['error']}  <--")
        else:
            att = r.get("needs_attention") or []
            sl = r.get("seeding_limits") or {}
            bs = r.get("by_state") or {}
            dl = sum(v for k, v in bs.items() if k in ("downloading", "stalledDL", "metaDL", "forcedDL", "queuedDL"))
            flag = "  <--" if att else ""
            lines.append(
                f"  qbittorrent v{r.get('version')}, {r.get('connection')}, {r.get('torrents_total')} torrents ({dl} downloading), "
                f"{len(att)} need attention, seeding limits ratio={sl.get('ratio')} time={sl.get('seeding_time_min')} action={sl.get('action_when_reached')}{flag}"
            )
            for x in att[:5]:
                lines.append(f"      {x['state']:<12}{x['progress']:>5}%  {x['name'][:60]}")
    t = app_tasks["jellyfin"]
    if t is None:
        lines.append("  jellyfin not configured (JELLYFIN_API_KEY)")
    else:
        r = await t
        if "error" in r:
            lines.append(f"  jellyfin error: {r['error']}  <--")
        else:
            scan = r.get("library_scan") or {}
            stale = r.get("stale_items") or {}
            n_stale = stale.get("stale") if isinstance(stale, dict) else None
            errs = r.get("refresh_errors_24h", 0)
            flag = "  <--" if (errs or n_stale or scan.get("last_status") not in (None, "Completed")) else ""
            lines.append(
                f"  jellyfin v{r.get('version')}, last scan {scan.get('last_status')} at {scan.get('last_end')}, "
                f"refresh errors 24h: {errs}, stale library items: {n_stale if n_stale is not None else '?'}, "
                f"playing: {len(r.get('active_sessions') or [])}{flag}"
            )
    r = await app_tasks["dns"]
    if "error" in r:
        lines.append(f"  dns error: {r['error']}  <--")
    else:
        ok = r["lookup_from_mcp_container"].get("ok")
        flag = "  <--" if (not ok or r.get("tailscale_in_host_dns")) else ""
        lines.append(f"  dns {'ok' if ok else 'FAILING'} from containers; host uplink: {', '.join(r.get('host_uplink_nameservers') or ['?'])}{flag}")

    if notes:
        lines.append("\n=== NOTES ===")
        lines.extend(f"  {n}" for n in dict.fromkeys(notes))

    lines.append(
        "\n(<-- flags: working set>=85%, restarts>=3, throttle>=5%, disk>=85%, temp>=75C, "
        f"health=starting>={STUCK_STARTING_MIN}min, orphans>=10GB, any app health issue)"
    )
    return "\n".join(lines)
