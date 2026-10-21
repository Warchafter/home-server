"""Prometheus tools: instant and range PromQL."""

import time

import httpx

from core import PROM, mcp, prom


@mcp.tool()
async def prometheus_query(promql: str) -> list[dict]:
    """Run an instant PromQL query against Prometheus.

    Available metric families: node_* (host CPU/mem/disk/net/hwmon via Node
    Exporter), container_* (per-container CPU/mem/net via cAdvisor, labeled
    by `name`). Example: 'container_memory_usage_bytes{name="jellyfin"}'.
    Note: `a or b` drops series from b whose labels match a — use
    label_replace to tell them apart, or query separately.
    """
    return [
        {"metric": r["metric"], "value": r["value"][1], "timestamp": r["value"][0]}
        for r in await prom(promql)
    ]


@mcp.tool()
async def prometheus_query_range(promql: str, hours: float = 6, step: str = "5m") -> list[dict]:
    """Run a PromQL range query over the last N hours (default 6, step 5m).

    Use for trends: memory growth, CPU spikes, temperature history (e.g.
    max_over_time(node_hwmon_temp_celsius{sensor="temp3"}[1h]) with step 1h
    over 168 hours shows a week of NVMe hotspot peaks). Retention is 30 days.
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
