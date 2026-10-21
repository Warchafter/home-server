"""Container tools: list, inspect, logs (with server-side grep), restart events, Docker disk usage."""

import json
import re
import time
from collections import defaultdict

import httpx

from core import DOCKER, demux_logs, docker_get, human_bytes, iso, mcp, parse_duration


@mcp.tool()
async def list_services() -> list[dict]:
    """List all Docker containers with state, health, image, and uptime status.

    The fleet overview: call this first to see what exists and what is
    unhealthy, then drill into a specific service with service_details or
    service_logs.
    """
    containers = await docker_get("/containers/json", params={"all": "true"})
    return sorted(
        (
            {
                "name": c["Names"][0].lstrip("/"),
                "state": c["State"],
                "status": c["Status"],
                "image": c["Image"],
            }
            for c in containers
        ),
        key=lambda c: c["name"],
    )


@mcp.tool()
async def service_details(service: str) -> dict:
    """Inspect one container: state, health-check history and config, restart
    count/policy, exit code, OOM flag, start/created time, CPU/memory limits,
    DNS servers, network mode, mounts (source -> destination, ro/rw).

    Environment variables are deliberately NOT returned (they hold secrets).
    `service` is the container name as shown by list_services.
    """
    c = await docker_get(f"/containers/{service}/json")
    state = c.get("State", {})
    health = state.get("Health") or {}
    hc = (c.get("Config", {}).get("Healthcheck") or {})
    host = c.get("HostConfig", {})
    return {
        "name": c.get("Name", "").lstrip("/"),
        "image": c.get("Config", {}).get("Image"),
        "created": c.get("Created"),
        "state": state.get("Status"),
        "started_at": state.get("StartedAt"),
        "exit_code": state.get("ExitCode"),
        "oom_killed": state.get("OOMKilled"),
        "restart_count": c.get("RestartCount"),
        "restart_policy": (host.get("RestartPolicy") or {}).get("Name"),
        "cpu_limit": (host.get("NanoCpus") or 0) / 1e9 or None,
        "memory_limit": human_bytes(host["Memory"]) if host.get("Memory") else None,
        "network_mode": host.get("NetworkMode"),
        "dns": host.get("Dns") or [],
        "health": health.get("Status"),
        "health_failing_streak": health.get("FailingStreak"),
        "healthcheck": {
            "test": " ".join(hc.get("Test") or []) or None,
            "interval_s": (hc.get("Interval") or 0) / 1e9 or None,
            "timeout_s": (hc.get("Timeout") or 0) / 1e9 or None,
            "start_period_s": (hc.get("StartPeriod") or 0) / 1e9 or None,
            "retries": hc.get("Retries"),
        } if hc else None,
        "recent_health_checks": [
            {
                "end": log.get("End"),
                "exit_code": log.get("ExitCode"),
                "output": (log.get("Output") or "")[:500],
            }
            for log in (health.get("Log") or [])[-3:]
        ],
        "mounts": [
            {"source": m.get("Source") or m.get("Name"), "destination": m.get("Destination"), "mode": "rw" if m.get("RW") else "ro", "type": m.get("Type")}
            for m in c.get("Mounts", [])
        ],
    }


async def _fetch_logs(service: str, lines: int, since: str) -> str:
    params = {"stdout": "true", "stderr": "true", "tail": str(lines), "timestamps": "true"}
    secs = parse_duration(since)
    if secs:
        params["since"] = str(int(time.time() - secs))
    body = await docker_get(f"/containers/{service}/logs", params=params, raw=True, timeout=30)
    return demux_logs(body)


@mcp.tool()
async def service_logs(service: str, lines: int = 100, since: str = "") -> str:
    """Fetch the last N log lines (stdout+stderr, timestamped) from a container.

    `lines` is capped at 1000. `since` optionally limits to a window such as
    "30m", "2h" or "1d". For anything larger than a few hundred lines, use
    service_logs_grep instead and let the server do the filtering.
    """
    lines = max(1, min(int(lines), 1000))
    return await _fetch_logs(service, lines, since) or "(no log output)"


@mcp.tool()
async def service_logs_grep(
    service: str,
    pattern: str,
    since: str = "24h",
    max_lines: int = 5000,
    max_matches: int = 100,
    context: int = 0,
    ignore_case: bool = True,
) -> dict:
    """Regex-search a container's logs server-side and return only the hits.

    Scans up to `max_lines` (cap 20000) of the most recent output within
    `since` (e.g. "1h", "24h", "7d"), returns match count, first/last match
    timestamps, and up to `max_matches` matching lines (with `context` lines
    around each). Far cheaper than pulling raw logs: use it for things like
    "no space left", "UNIQUE constraint", "SERVFAIL", "Error refreshing".
    """
    max_lines = max(1, min(int(max_lines), 20000))
    text = await _fetch_logs(service, max_lines, since)
    rows = text.splitlines()
    rx = re.compile(pattern, re.I if ignore_case else 0)
    hits = [i for i, line in enumerate(rows) if rx.search(line)]
    sample: list[str] = []
    seen: set[int] = set()
    for i in hits[: max(1, int(max_matches))]:
        lo, hi = max(0, i - context), min(len(rows), i + context + 1)
        for j in range(lo, hi):
            if j not in seen:
                seen.add(j)
                sample.append(("> " if j == i else "  ") + rows[j][:400])
    ts = lambda line: line.split(" ", 1)[0] if line else None  # noqa: E731
    return {
        "service": service,
        "pattern": pattern,
        "since": since,
        "lines_scanned": len(rows),
        "matches": len(hits),
        "first_match": ts(rows[hits[0]]) if hits else None,
        "last_match": ts(rows[hits[-1]]) if hits else None,
        "sample": sample,
    }


@mcp.tool()
async def restart_events(window: str = "24h") -> dict:
    """Container lifecycle events from the Docker daemon over the last `window`
    ("1h", "24h", "7d"): per-container counts of start / die (with exit codes)
    / OOM / unhealthy transitions, plus the most recent events. This is how a
    crash-restart loop shows up as a number ("radarr: 412 starts in 8h")
    rather than something you infer from "Up 23 seconds".
    """
    secs = parse_duration(window, 86400)
    until = int(time.time())
    since = until - int(secs)
    filters = json.dumps({"type": ["container"], "event": ["start", "die", "oom", "kill", "restart", "health_status"]})
    body = await docker_get("/events", params={"since": str(since), "until": str(until), "filters": filters}, raw=True, timeout=30)
    per: dict[str, dict] = defaultdict(lambda: {"start": 0, "die": 0, "oom": 0, "kill": 0, "unhealthy": 0, "exit_codes": defaultdict(int), "last_event": None})
    recent: list[dict] = []
    total = 0
    for line in body.decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        total += 1
        action = ev.get("Action", "")
        attrs = (ev.get("Actor") or {}).get("Attributes") or {}
        name = attrs.get("name", "?")
        p = per[name]
        if action == "start":
            p["start"] += 1
        elif action == "die":
            p["die"] += 1
            p["exit_codes"][attrs.get("exitCode", "?")] += 1
        elif action == "oom":
            p["oom"] += 1
        elif action == "kill":
            p["kill"] += 1
        elif action.startswith("health_status") and "unhealthy" in action:
            p["unhealthy"] += 1
        else:
            continue
        p["last_event"] = {"action": action, "time": iso(ev.get("time"))}
        recent.append({"time": iso(ev.get("time")), "container": name, "action": action, "exit_code": attrs.get("exitCode")})
    summary = []
    for name, p in sorted(per.items(), key=lambda kv: -kv[1]["start"]):
        summary.append({
            "container": name,
            "starts": p["start"],
            "dies": p["die"],
            "exit_codes": dict(p["exit_codes"]),
            "oom": p["oom"],
            "unhealthy": p["unhealthy"],
            "last_event": p["last_event"],
            "flag": "restart loop?" if p["start"] >= 3 else None,
        })
    return {"window": window, "events": total, "containers": summary, "recent": recent[-25:]}


@mcp.tool()
async def docker_disk_usage() -> dict:
    """What Docker itself occupies on disk: images (total/reclaimable),
    container writable layers, named volumes by size, build cache. Needs
    SYSTEM=1 on dockerproxy; explains itself if that is off.
    Note: Docker reports image space as 'reclaimable' even when in use
    (containerd image store quirk) — trust the volume numbers more.
    """
    try:
        d = await docker_get("/system/df", timeout=120)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            return {"error": "dockerproxy denies /system/df — set SYSTEM=1 in stacks/dockerproxy.yaml"}
        raise
    images = d.get("Images") or []
    containers = d.get("Containers") or []
    volumes = d.get("Volumes") or []
    cache = d.get("BuildCache") or []
    img_total = sum(i.get("Size", 0) for i in images)
    vols = sorted(
        ({"name": v.get("Name"), "size": human_bytes((v.get("UsageData") or {}).get("Size", 0)), "bytes": (v.get("UsageData") or {}).get("Size", 0), "refs": (v.get("UsageData") or {}).get("RefCount", 0)} for v in volumes),
        key=lambda v: -v["bytes"],
    )
    return {
        "images": {"count": len(images), "total": human_bytes(img_total)},
        "containers": {"count": len(containers), "writable_layers": human_bytes(sum(c.get("SizeRw", 0) or 0 for c in containers))},
        "volumes": {"count": len(volumes), "total": human_bytes(sum(v["bytes"] for v in vols)), "largest": vols[:15], "unused": [v["name"] for v in vols if v["refs"] == 0]},
        "build_cache": human_bytes(sum(b.get("Size", 0) for b in cache)),
    }
