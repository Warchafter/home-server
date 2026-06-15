#!/usr/bin/env python3
"""
health-report.py — Pull a digest of server health from Prometheus.

Prometheus is internal-only (monitoring network, no published port), so every
query is issued from a throwaway curl container attached to that network. The
output is a compact, analysis-friendly digest covering the things that have
actually broken on this box: container restarts, memory pressure vs. limits,
CPU throttling, disk fill trajectory, host load, and network drops.

Run ON THE SERVER:
    python3 scripts/health-report.py            # last-instant snapshot + 7d trends
    python3 scripts/health-report.py --window 30d   # widen the restart/lookback window

Paste the output back to Claude for analysis, or just read it yourself.
"""

import argparse
import json
import subprocess
import sys

PROM = "http://prometheus:9090/api/v1/query"
NETWORK = "monitoring"
CURL_IMAGE = "curlimages/curl:latest"


def q(promql: str):
    """Run an instant query against Prometheus from a curl container."""
    try:
        out = subprocess.run(
            ["docker", "run", "--rm", "--network", NETWORK, CURL_IMAGE,
             "-s", "-G", "--data-urlencode", f"query={promql}", PROM],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(out.stdout)
        if data.get("status") != "success":
            return []
        return data["data"]["result"]
    except Exception as e:
        print(f"  ! query failed: {e}", file=sys.stderr)
        return []


def val(result_item):
    return float(result_item["value"][1])


def by_name(results):
    """Map cAdvisor results keyed by container name, dropping empty names."""
    out = {}
    for r in results:
        name = r["metric"].get("name", "")
        if name:
            out[name] = val(r)
    return out


def human_bytes(n):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def human_duration(seconds):
    if seconds < 0:
        return "already full / shrinking fast"
    if seconds > 365 * 86400:
        return ">1yr"
    d = seconds / 86400
    if d >= 1:
        return f"{d:.1f}d"
    return f"{seconds/3600:.1f}h"


def section(title):
    print(f"\n=== {title} ===")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="7d", help="lookback for restart counts (default 7d)")
    args = ap.parse_args()
    W = args.window

    print("HOME SERVER HEALTH REPORT (source: Prometheus, 30d retention)")

    # ---- Containers ----
    section("CONTAINERS — memory vs limit, restarts, CPU throttle")
    usage = by_name(q('container_memory_usage_bytes{name!=""}'))
    limit = by_name(q('container_spec_memory_limit_bytes{name!=""}'))
    restarts = by_name(q(f'changes(container_start_time_seconds{{name!=""}}[{W}])'))
    thr = by_name(q('rate(container_cpu_cfs_throttled_periods_total{name!=""}[1h])'))
    per = by_name(q('rate(container_cpu_cfs_periods_total{name!=""}[1h])'))

    names = sorted(usage.keys())
    if not names:
        print("  (no container metrics — is cAdvisor scraping? check Prometheus targets)")
    print(f"  {'container':<22}{'mem':>10}{'limit':>10}{'mem%':>7}{'restarts/'+W:>13}{'throttle%':>11}")
    for n in names:
        u = usage.get(n, 0)
        lim = limit.get(n, 0)
        pct = (u / lim * 100) if lim > 0 else 0
        rs = int(restarts.get(n, 0))
        tpct = (thr.get(n, 0) / per[n] * 100) if per.get(n, 0) > 0 else 0
        flag = "  <-- " if (pct >= 85 or rs >= 3 or tpct >= 5) else ""
        lims = human_bytes(lim) if lim > 0 else "none"
        print(f"  {n:<22}{human_bytes(u):>10}{lims:>10}{pct:>6.0f}%{rs:>13}{tpct:>10.1f}%{flag}")

    # ---- Host ----
    section("HOST — CPU, load, memory, swap")
    cpu = q('100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)')
    load1 = q('node_load1')
    memavail = q('node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes * 100')
    swapused = q('node_memory_SwapTotal_bytes - node_memory_SwapFree_bytes')
    if cpu:    print(f"  CPU busy:        {val(cpu[0]):.1f}%")
    if load1:  print(f"  Load (1m):       {val(load1[0]):.2f}")
    if memavail: print(f"  Mem available:   {val(memavail[0]):.1f}%")
    if swapused: print(f"  Swap used:       {human_bytes(val(swapused[0]))}")

    # ---- Disk ----
    section("DISK — usage now + projected time-to-full (linear from last 6h)")
    avail = q('node_filesystem_avail_bytes{fstype!~"tmpfs|overlay|squashfs"}')
    size = q('node_filesystem_size_bytes{fstype!~"tmpfs|overlay|squashfs"}')
    predict = q('predict_linear(node_filesystem_avail_bytes{fstype!~"tmpfs|overlay|squashfs"}[6h], 7*86400)')
    size_by_mp = {r["metric"].get("mountpoint", "?"): val(r) for r in size}
    pred_by_mp = {r["metric"].get("mountpoint", "?"): val(r) for r in predict}
    if not avail:
        print("  (no filesystem metrics — check node-exporter mounts/labels)")
    for r in sorted(avail, key=lambda x: x["metric"].get("mountpoint", "")):
        mp = r["metric"].get("mountpoint", "?")
        a = val(r)
        s = size_by_mp.get(mp, 0)
        usedpct = ((s - a) / s * 100) if s > 0 else 0
        # seconds until avail hits 0, from current avail and 6h slope
        p7 = pred_by_mp.get(mp)
        ttf = ""
        if p7 is not None and p7 < a:  # shrinking
            slope_per_s = (a - p7) / (7 * 86400)
            if slope_per_s > 0:
                ttf = "  full in ~" + human_duration(a / slope_per_s)
        flag = "  <--" if usedpct >= 85 else ""
        print(f"  {mp:<14}{human_bytes(a):>10} free / {human_bytes(s):>10}  ({usedpct:.0f}% used){ttf}{flag}")

    # ---- Network ----
    section("NETWORK — receive drops (last 5m rate, real NICs only)")
    drops = q('rate(node_network_receive_drop_total{device!~"lo|veth.*|docker.*|br.*|tailscale.*"}[5m])')
    any_drop = False
    for r in drops:
        d = val(r)
        if d > 0:
            any_drop = True
            print(f"  {r['metric'].get('device','?'):<12}{d:.2f} drops/s  <--")
    if not any_drop:
        print("  no receive drops on physical NICs")

    print("\n(Thresholds flagged with <-- : mem>=85%, restarts>=3, throttle>=5%, disk>=85%)")


if __name__ == "__main__":
    main()
