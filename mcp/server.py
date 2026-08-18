#!/usr/bin/env python3
"""
Home Server MCP — read-only Model Context Protocol server.

Exposes the server's operational state as MCP tools over streamable HTTP:
container status and logs via dockerproxy, host and container metrics via
Prometheus. Consumed by Claude Code (dev laptop) and Odysseus (local LLM
workspace) over the LAN / Tailscale, routed through Caddy at :8105.

Deliberately READ-ONLY: no restart/exec/write tools. Docker access goes
through dockerproxy, which blocks all POST endpoints (POST=0), so even a
misbehaving client can only look, never touch.
"""

import os
import time

import httpx
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

DOCKER = os.environ.get("DOCKER_PROXY_URL", "http://dockerproxy:2375")
PROM = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")

mcp = FastMCP(
    "home-server",
    instructions=(
        "Read-only visibility into the home server (Docker Compose services "
        "behind Caddy). Use list_services for a fleet overview, service_logs "
        "and service_details to debug one container, prometheus_query for "
        "ad-hoc PromQL, and health_summary for the full digest (containers, "
        "host, disk, temperatures, network). Nothing here can modify the "
        "server."
    ),
    host="0.0.0.0",
    port=8000,
    stateless_http=True,
)


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

async def _docker_get(path: str, params: dict | None = None, raw: bool = False):
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{DOCKER}{path}", params=params)
        resp.raise_for_status()
        return resp.content if raw else resp.json()


async def _prom(promql: str) -> list:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{PROM}/api/v1/query", params={"query": promql})
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success":
            raise RuntimeError(f"Prometheus error: {data.get('error', 'unknown')}")
        return data["data"]["result"]


def _val(item) -> float:
    return float(item["value"][1])


def _by_name(results: list) -> dict:
    return {r["metric"]["name"]: _val(r) for r in results if r["metric"].get("name")}


def _demux_logs(body: bytes) -> str:
    """Strip Docker's 8-byte multiplex frame headers from a log stream.

    TTY containers return a raw stream instead; fall back to plain decode
    when the frame structure doesn't hold.
    """
    out, i, n = [], 0, len(body)
    while i + 8 <= n:
        if body[i] not in (0, 1, 2) or body[i + 1:i + 4] != b"\x00\x00\x00":
            return body.decode("utf-8", "replace")
        size = int.from_bytes(body[i + 4:i + 8], "big")
        out.append(body[i + 8:i + 8 + size].decode("utf-8", "replace"))
        i += 8 + size
    if i < n:
        out.append(body[i:].decode("utf-8", "replace"))
    return "".join(out)


def _human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


# ---------------------------------------------------------------------------
# Tools — Docker (via dockerproxy, read-only)
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_services() -> list[dict]:
    """List all Docker containers with state, health, image, and uptime status.

    The fleet overview: call this first to see what exists and what is
    unhealthy, then drill into a specific service with service_details or
    service_logs.
    """
    containers = await _docker_get("/containers/json", params={"all": "true"})
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
    """Inspect one container: state, health-check history, restart count,
    exit code, OOM flag, and start time.

    `service` is the container name as shown by list_services (e.g.
    "qbittorrent", "gluetun", "jellyfin").
    """
    c = await _docker_get(f"/containers/{service}/json")
    state = c.get("State", {})
    health = state.get("Health") or {}
    return {
        "name": c.get("Name", "").lstrip("/"),
        "image": c.get("Config", {}).get("Image"),
        "state": state.get("Status"),
        "started_at": state.get("StartedAt"),
        "exit_code": state.get("ExitCode"),
        "oom_killed": state.get("OOMKilled"),
        "restart_count": c.get("RestartCount"),
        "health": health.get("Status"),
        "health_failing_streak": health.get("FailingStreak"),
        "recent_health_checks": [
            {
                "end": log.get("End"),
                "exit_code": log.get("ExitCode"),
                "output": (log.get("Output") or "")[:500],
            }
            for log in (health.get("Log") or [])[-3:]
        ],
    }


@mcp.tool()
async def service_logs(service: str, lines: int = 100) -> str:
    """Fetch the last N log lines (stdout+stderr, timestamped) from a container.

    `service` is the container name (e.g. "gluetun"). `lines` is capped at
    1000 to keep responses manageable.
    """
    lines = max(1, min(int(lines), 1000))
    body = await _docker_get(
        f"/containers/{service}/logs",
        params={"stdout": "true", "stderr": "true", "tail": str(lines), "timestamps": "true"},
        raw=True,
    )
    return _demux_logs(body) or "(no log output)"


# ---------------------------------------------------------------------------
# Tools — Prometheus
# ---------------------------------------------------------------------------

@mcp.tool()
async def prometheus_query(promql: str) -> list[dict]:
    """Run an instant PromQL query against Prometheus.

    Available metric families: node_* (host CPU/mem/disk/net/hwmon via Node
    Exporter), container_* (per-container CPU/mem/net via cAdvisor, labeled
    by `name`). Example: 'container_memory_usage_bytes{name="jellyfin"}'.
    """
    return [
        {"metric": r["metric"], "value": r["value"][1], "timestamp": r["value"][0]}
        for r in await _prom(promql)
    ]


@mcp.tool()
async def prometheus_query_range(promql: str, hours: float = 6, step: str = "5m") -> list[dict]:
    """Run a PromQL range query over the last N hours (default 6, step 5m).

    Use for trends: memory growth, CPU spikes, temperature history.
    Retention is 30 days.
    """
    end = time.time()
    start = end - float(hours) * 3600
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            f"{PROM}/api/v1/query_range",
            params={"query": promql, "start": start, "end": end, "step": step},
        )
        resp.raise_for_status()
        data = resp.json()
    if data.get("status") != "success":
        raise RuntimeError(f"Prometheus error: {data.get('error', 'unknown')}")
    return [
        {"metric": r["metric"], "values": r["values"]}
        for r in data["data"]["result"]
    ]


# ---------------------------------------------------------------------------
# Tools — health digest (mirrors scripts/health-report.py)
# ---------------------------------------------------------------------------

@mcp.tool()
async def health_summary(window: str = "7d") -> str:
    """Full health digest: container memory/restarts/CPU-throttle, host
    CPU/load/memory/swap, disk usage with time-to-full projection,
    temperatures, network drops, and any non-running/unhealthy containers.

    `window` sets the restart-count lookback (default "7d", max useful "30d").
    Lines flagged with <-- exceed a threshold and deserve attention.
    """
    lines: list[str] = ["HOME SERVER HEALTH SUMMARY"]

    # Containers not running / unhealthy (dockerproxy)
    containers = await _docker_get("/containers/json", params={"all": "true"})
    problems = [
        f"  {c['Names'][0].lstrip('/'):<22}{c['State']:<12}{c['Status']}"
        for c in containers
        if c["State"] != "running" or "unhealthy" in c["Status"]
    ]
    lines.append(f"\n=== CONTAINER STATES ({len(containers)} total) ===")
    lines.extend(problems or ["  all running and healthy"])

    # Container resources (cAdvisor)
    usage = _by_name(await _prom('container_memory_usage_bytes{name!=""}'))
    limit = _by_name(await _prom('container_spec_memory_limit_bytes{name!=""}'))
    restarts = _by_name(await _prom(f'changes(container_start_time_seconds{{name!=""}}[{window}])'))
    thr = _by_name(await _prom('rate(container_cpu_cfs_throttled_periods_total{name!=""}[1h])'))
    per = _by_name(await _prom('rate(container_cpu_cfs_periods_total{name!=""}[1h])'))
    lines.append(f"\n=== CONTAINERS — memory vs limit, restarts/{window}, CPU throttle ===")
    for name in sorted(usage):
        mem, lim = usage[name], limit.get(name, 0)
        pct = mem / lim * 100 if lim > 0 else 0
        rs = int(restarts.get(name, 0))
        tpct = thr.get(name, 0) / per[name] * 100 if per.get(name, 0) > 0 else 0
        flag = "  <--" if (pct >= 85 or rs >= 3 or tpct >= 5) else ""
        lims = _human_bytes(lim) if lim > 0 else "none"
        lines.append(
            f"  {name:<22}{_human_bytes(mem):>10} / {lims:<8} {pct:>4.0f}%"
            f"  restarts:{rs:<3} throttle:{tpct:.1f}%{flag}"
        )

    # Host
    lines.append("\n=== HOST ===")
    for label, promql, fmt in (
        ("CPU busy", '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)', "{:.1f}%"),
        ("Load (1m)", "node_load1", "{:.2f}"),
        ("Mem available", "node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes * 100", "{:.1f}%"),
        ("Swap used (MB)", "(node_memory_SwapTotal_bytes - node_memory_SwapFree_bytes) / 1048576", "{:.0f}"),
    ):
        result = await _prom(promql)
        if result:
            lines.append(f"  {label:<16}{fmt.format(_val(result[0]))}")

    # Disk + time-to-full projection (linear from last 6h)
    lines.append("\n=== DISK ===")
    avail = await _prom('node_filesystem_avail_bytes{fstype!~"tmpfs|overlay|squashfs"}')
    size = await _prom('node_filesystem_size_bytes{fstype!~"tmpfs|overlay|squashfs"}')
    predict = await _prom(
        'predict_linear(node_filesystem_avail_bytes{fstype!~"tmpfs|overlay|squashfs"}[6h], 7*86400)'
    )
    size_by_mp = {r["metric"].get("mountpoint"): _val(r) for r in size}
    pred_by_mp = {r["metric"].get("mountpoint"): _val(r) for r in predict}
    for r in sorted(avail, key=lambda x: x["metric"].get("mountpoint", "")):
        mp = r["metric"].get("mountpoint", "?")
        a, s = _val(r), size_by_mp.get(mp, 0)
        used_pct = (s - a) / s * 100 if s > 0 else 0
        ttf = ""
        p7 = pred_by_mp.get(mp)
        if p7 is not None and p7 < a:
            slope = (a - p7) / (7 * 86400)
            if slope > 0:
                days = a / slope / 86400
                ttf = f"  full in ~{days:.1f}d" if days < 365 else ""
        flag = "  <--" if used_pct >= 85 else ""
        lines.append(f"  {mp:<14}{_human_bytes(a):>10} free / {_human_bytes(s)} ({used_pct:.0f}% used){ttf}{flag}")

    # Temperatures (NVMe hotspot has hit critical before — watch it)
    temps = await _prom("node_hwmon_temp_celsius")
    if temps:
        lines.append("\n=== TEMPERATURES ===")
        for r in sorted(temps, key=lambda x: -_val(x)):
            m = r["metric"]
            label = m.get("chip", "?") + "/" + (m.get("sensor") or "?")
            t = _val(r)
            lines.append(f"  {label:<40}{t:>6.1f}C{'  <--' if t >= 75 else ''}")

    # Network drops on physical NICs
    drops = await _prom(
        'rate(node_network_receive_drop_total{device!~"lo|veth.*|docker.*|br.*|tailscale.*"}[5m])'
    )
    dropped = [f"  {r['metric'].get('device', '?'):<12}{_val(r):.2f} drops/s  <--" for r in drops if _val(r) > 0]
    lines.append("\n=== NETWORK ===")
    lines.extend(dropped or ["  no receive drops on physical NICs"])

    lines.append("\n(<-- flags: mem>=85%, restarts>=3, throttle>=5%, disk>=85%, temp>=75C)")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
