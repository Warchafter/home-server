"""
Shared plumbing for the home-server MCP: the FastMCP instance, backend
clients (dockerproxy, Prometheus, app APIs), and small parsing helpers.

Everything here is read-only by construction: dockerproxy blocks POST, the
app clients only issue GETs (qBittorrent needs one POST to log in, nothing
else), and the media root is mounted read-only.
"""

import os
import re
import time

import httpx
from mcp.server.fastmcp import FastMCP

DOCKER = os.environ.get("DOCKER_PROXY_URL", "http://dockerproxy:2375")
PROM = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")

# Media root as mounted into this container (read-only). The media stacks
# mount the same host path at /media, so paths line up 1:1 with Jellyfin's.
MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/media")
DOWNLOADS_COMPLETE = os.environ.get("DOWNLOADS_COMPLETE", "downloads/complete")
DOWNLOADS_INCOMPLETE = os.environ.get("DOWNLOADS_INCOMPLETE", "downloads/incomplete")

# Host's systemd-resolved directory, bind-mounted read-only (DNS canary).
HOST_RESOLVE_DIR = os.environ.get("HOST_RESOLVE_DIR", "/host/resolve")
TAILSCALE_MAGIC_DNS = "100.100.100.100"

# App APIs. URLs are the compose service names on the proxy network; keys
# come from .env (the same ones Homepage uses). A missing key just makes the
# corresponding tool report "not configured".
ARR = {
    "sonarr": {"url": os.environ.get("SONARR_URL", "http://sonarr:8989"), "key": os.environ.get("SONARR_API_KEY", ""), "api": "api/v3"},
    "radarr": {"url": os.environ.get("RADARR_URL", "http://radarr:7878"), "key": os.environ.get("RADARR_API_KEY", ""), "api": "api/v3"},
    "prowlarr": {"url": os.environ.get("PROWLARR_URL", "http://prowlarr:9696"), "key": os.environ.get("PROWLARR_API_KEY", ""), "api": "api/v1"},
    "bazarr": {"url": os.environ.get("BAZARR_URL", "http://bazarr:6767"), "key": os.environ.get("BAZARR_API_KEY", ""), "api": "api"},
}
JELLYFIN_URL = os.environ.get("JELLYFIN_URL", "http://jellyfin:8096")
JELLYFIN_API_KEY = os.environ.get("JELLYFIN_API_KEY", "")
QB_URL = os.environ.get("QBITTORRENT_URL", "http://gluetun:8080")
QB_USER = os.environ.get("QBITTORRENT_USER", "admin")
QB_PASS = os.environ.get("QBITTORRENT_PASS", "")

APP_TIMEOUT = 15

mcp = FastMCP(
    "home-server",
    instructions=(
        "Read-only visibility into the home server (Docker Compose services "
        "behind Caddy). Start with health_summary for the full digest. Then: "
        "list_services / service_details / service_logs / service_logs_grep / "
        "restart_events for containers; prometheus_query(_range) for metrics; "
        "media_usage and download_orphans for disk forensics on the media "
        "tree; arr_status, qbittorrent_status and jellyfin_status for the "
        "apps' own view of queues, health warnings, torrents and library "
        "scans; dns_check for the container/host DNS path; docker_disk_usage "
        "for images/volumes. Nothing here can modify the server."
    ),
    host="0.0.0.0",
    port=8000,
    stateless_http=True,
)


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

async def docker_get(path: str, params: dict | None = None, raw: bool = False, timeout: float = 15):
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(f"{DOCKER}{path}", params=params)
        resp.raise_for_status()
        return resp.content if raw else resp.json()


async def prom(promql: str) -> list:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{PROM}/api/v1/query", params={"query": promql})
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success":
            raise RuntimeError(f"Prometheus error: {data.get('error', 'unknown')}")
        return data["data"]["result"]


async def prom_safe(promql: str, notes: list[str]) -> list:
    """prom() that degrades instead of failing the whole digest."""
    try:
        return await prom(promql)
    except Exception as e:  # noqa: BLE001
        notes.append(f"Prometheus query failed: {e}")
        return []


def arr_configured(app: str) -> bool:
    return bool(ARR.get(app, {}).get("key"))


async def arr_get(app: str, path: str, params: dict | None = None):
    cfg = ARR[app]
    if not cfg["key"]:
        raise RuntimeError(f"{app}: API key not configured ({app.upper()}_API_KEY in .env)")
    header = "X-API-KEY" if app == "bazarr" else "X-Api-Key"
    async with httpx.AsyncClient(timeout=APP_TIMEOUT, headers={header: cfg["key"]}) as client:
        resp = await client.get(f"{cfg['url']}/{cfg['api']}/{path.lstrip('/')}", params=params)
        resp.raise_for_status()
        return resp.json()


async def jellyfin_get(path: str, params: dict | None = None):
    if not JELLYFIN_API_KEY:
        raise RuntimeError("jellyfin: API key not configured (JELLYFIN_API_KEY in .env)")
    headers = {"Authorization": f'MediaBrowser Token="{JELLYFIN_API_KEY}", Client="home-server-mcp", Device="mcp", DeviceId="mcp", Version="1"'}
    async with httpx.AsyncClient(timeout=APP_TIMEOUT, headers=headers) as client:
        resp = await client.get(f"{JELLYFIN_URL}/{path.lstrip('/')}", params=params)
        resp.raise_for_status()
        return resp.json() if resp.content else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def val(item) -> float:
    return float(item["value"][1])


def by_name(results: list) -> dict:
    return {r["metric"]["name"]: val(r) for r in results if r["metric"].get("name")}


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


_DUR_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhdw]?)\s*$", re.I)
_DUR_UNIT = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text: str | float | int, default_seconds: float = 0) -> float:
    """'30m' / '2h' / '1d' / '45' (seconds) -> seconds. Empty -> default."""
    if text in (None, ""):
        return default_seconds
    if isinstance(text, (int, float)):
        return float(text)
    m = _DUR_RE.match(str(text))
    if not m:
        raise ValueError(f"bad duration {text!r}; use e.g. 30m, 2h, 1d")
    return float(m.group(1)) * _DUR_UNIT[m.group(2).lower()]


_UP_RE = re.compile(r"^Up (?:(About a|About an|Less than a|\d+) )?(second|minute|hour|day|week|month|year)s?", re.I)
_UNIT_MIN = {"second": 1 / 60, "minute": 1, "hour": 60, "day": 1440, "week": 10080, "month": 43200, "year": 525600}
STUCK_STARTING_MIN = 5


def up_minutes(status: str) -> float | None:
    """Minutes a container has been up, parsed from Docker's Status text ("Up 2 minutes (healthy)")."""
    m = _UP_RE.match(status or "")
    if not m:
        return None
    qty, unit = m.group(1), m.group(2).lower()
    if qty in (None, "About a", "About an"):
        n = 1.0
    elif qty == "Less than a":
        n = 0.0
    else:
        n = float(qty)
    return n * _UNIT_MIN[unit]


def demux_logs(body: bytes) -> str:
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


def iso(ts: float | int | None) -> str | None:
    if not ts:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(ts)))
