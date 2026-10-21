#!/usr/bin/env python3
"""
selftest.py — exercise the MCP server's pure helpers without a server.

    python3 mcp/selftest.py

Stubs the `mcp` and `httpx` packages if they are not installed locally, builds
a throwaway media tree with real hardlinks to check the orphan accounting,
and feeds canned Docker events / log text through the aggregation code.
"""

import asyncio
import json
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# --- stubs for packages the dev machine may not have ---------------------------
try:
    import mcp.server.fastmcp  # noqa: F401
except ImportError:
    fast = types.ModuleType("mcp.server.fastmcp")

    class FastMCP:  # minimal: decorators return the function unchanged
        def __init__(self, *a, **k): ...
        def tool(self, *a, **k): return lambda f: f
        def custom_route(self, *a, **k): return lambda f: f
        def run(self, *a, **k): ...

    fast.FastMCP = FastMCP
    pkg = types.ModuleType("mcp"); srv = types.ModuleType("mcp.server")
    pkg.server = srv; srv.fastmcp = fast
    sys.modules.update({"mcp": pkg, "mcp.server": srv, "mcp.server.fastmcp": fast})
try:
    import httpx  # noqa: F401
except ImportError:
    hx = types.ModuleType("httpx")

    class _E(Exception): ...
    class AsyncClient:  # never used in the self-test
        def __init__(self, *a, **k): ...
    hx.AsyncClient = AsyncClient; hx.HTTPStatusError = _E
    sys.modules["httpx"] = hx
try:
    import starlette.requests  # noqa: F401
except ImportError:
    st = types.ModuleType("starlette"); rq = types.ModuleType("starlette.requests"); rs = types.ModuleType("starlette.responses")
    rq.Request = object; rs.PlainTextResponse = object
    sys.modules.update({"starlette": st, "starlette.requests": rq, "starlette.responses": rs})

# --- media tree with hardlinks ------------------------------------------------
tmp = tempfile.mkdtemp(prefix="mcp-selftest-")
os.environ["MEDIA_ROOT"] = tmp
os.environ["HOST_RESOLVE_DIR"] = os.path.join(tmp, "resolve")
os.makedirs(os.path.join(tmp, "downloads/complete/Show.S01E01-GRP"))
os.makedirs(os.path.join(tmp, "downloads/complete/Orphan.Movie.2020"))
os.makedirs(os.path.join(tmp, "downloads/incomplete"))
os.makedirs(os.path.join(tmp, "tv/Show/Season 1"))
os.makedirs(os.path.join(tmp, "resolve"))
big = b"x" * (2 * 1024 * 1024)
with open(os.path.join(tmp, "downloads/complete/Show.S01E01-GRP/ep.mkv"), "wb") as f: f.write(big)
os.link(os.path.join(tmp, "downloads/complete/Show.S01E01-GRP/ep.mkv"), os.path.join(tmp, "tv/Show/Season 1/Show - S01E01.mkv"))
with open(os.path.join(tmp, "downloads/complete/Show.S01E01-GRP/info.nfo"), "wb") as f: f.write(b"n" * 100)
with open(os.path.join(tmp, "downloads/complete/Orphan.Movie.2020/movie.mkv"), "wb") as f: f.write(big * 3)
with open(os.path.join(tmp, "downloads/incomplete/part.mkv"), "wb") as f: f.write(big)
with open(os.path.join(tmp, "resolve/resolv.conf"), "w") as f: f.write("nameserver 100.100.100.100\nnameserver 192.168.0.1\nsearch example.ts.net\n")

import core  # noqa: E402
import docker_tools  # noqa: E402
import media_tools  # noqa: E402
import apps  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails += 1


# parse_duration / up_minutes / demux
check("parse_duration", core.parse_duration("30m") == 1800 and core.parse_duration("2h") == 7200 and core.parse_duration("1d") == 86400 and core.parse_duration("", 5) == 5 and core.parse_duration(45) == 45)
try:
    core.parse_duration("soon"); check("parse_duration rejects junk", False)
except ValueError:
    check("parse_duration rejects junk", True)
um = core.up_minutes
check("up_minutes", um("Up 23 seconds (health: starting)") < 1 and um("Up About a minute") == 1 and um("Up 5 minutes (health: starting)") == 5 and um("Up 2 months") == 86400 and um("Exited (1) 2 minutes ago") is None)
frame = b"\x01\x00\x00\x00\x00\x00\x00\x05hello" + b"\x02\x00\x00\x00\x00\x00\x00\x06 world"
check("demux_logs", core.demux_logs(frame) == "hello world" and core.demux_logs(b"plain text\n") == "plain text\n")

# media: hardlink-aware usage + orphans
u = media_tools._usage("downloads/complete", 10)
by = {e["name"]: e for e in u["entries"]}
check("usage shared vs unique", by["Show.S01E01-GRP"]["shared"] == "2.0MB" and by["Orphan.Movie.2020"]["unique"] == "6.0MB", str(by))
o = media_tools._orphans(1, 10)
check("orphans: only the single-link movie", o["orphans"]["files"] == 1 and o["orphans"]["reclaimable"] == "6.0MB" and o["by_torrent"][0]["name"] == "Orphan.Movie.2020", json.dumps(o["orphans"]))
check("orphans: nfo below size floor ignored", o["small_orphans_ignored"] == "100.0B", o["small_orphans_ignored"])
check("orphans: hardlinked bytes counted", o["hardlinked_into_library"]["size"] == "2.0MB" and o["incomplete_downloads"]["size"] == "2.0MB")
try:
    media_tools._safe_path("../etc"); check("path traversal blocked", False)
except ValueError:
    check("path traversal blocked", True)

# docker: restart_events aggregation and log grep with patched backends
events = "\n".join(json.dumps(e) for e in [
    {"Type": "container", "Action": "start", "Actor": {"Attributes": {"name": "radarr"}}, "time": 1700000000},
    {"Type": "container", "Action": "die", "Actor": {"Attributes": {"name": "radarr", "exitCode": "1"}}, "time": 1700000030},
    {"Type": "container", "Action": "start", "Actor": {"Attributes": {"name": "radarr"}}, "time": 1700000060},
    {"Type": "container", "Action": "die", "Actor": {"Attributes": {"name": "radarr", "exitCode": "1"}}, "time": 1700000090},
    {"Type": "container", "Action": "start", "Actor": {"Attributes": {"name": "radarr"}}, "time": 1700000120},
    {"Type": "container", "Action": "health_status: unhealthy", "Actor": {"Attributes": {"name": "radarr"}}, "time": 1700000150},
    {"Type": "container", "Action": "start", "Actor": {"Attributes": {"name": "caddy"}}, "time": 1700000200},
]).encode()


async def fake_docker_get(path, params=None, raw=False, timeout=15):
    if path == "/events":
        return events
    if path.endswith("/logs"):
        return b"2026-10-05T22:31:48Z level=error msg=\"write to WAL: no space left on device\"\n2026-10-05T22:32:01Z info ok\n2026-10-05T22:33:02Z level=error no space left on device again\n"
    raise AssertionError(path)

docker_tools.docker_get = fake_docker_get
ev = asyncio.run(docker_tools.restart_events("1h"))
r = ev["containers"][0]
check("restart_events aggregation", r["container"] == "radarr" and r["starts"] == 3 and r["dies"] == 2 and r["exit_codes"] == {"1": 2} and r["unhealthy"] == 1 and r["flag"] == "restart loop?", json.dumps(r))
g = asyncio.run(docker_tools.service_logs_grep("prometheus", "no space left", since="1h", max_matches=5))
check("service_logs_grep", g["matches"] == 2 and g["lines_scanned"] == 3 and g["first_match"].startswith("2026-10-05T22:31") and len(g["sample"]) == 2, json.dumps(g))

# apps: nameserver parsing + queue record shaping
ns = apps._nameservers(os.path.join(tmp, "resolve/resolv.conf"))
check("nameservers parsed", ns == ["100.100.100.100", "192.168.0.1"], str(ns))
qr = apps._queue_record("radarr", {"title": "Movie.2020", "movie": {"title": "Movie"}, "status": "completed", "trackedDownloadStatus": "warning", "trackedDownloadState": "importBlocked", "size": 5e9, "sizeleft": 0, "statusMessages": [{"title": "x", "messages": ["No files found are eligible for import"]}]})
check("queue record", qr["for"] == "Movie" and qr["tracked"] == "warning/importBlocked" and qr["messages"] == ["No files found are eligible for import"], json.dumps(qr))
t = apps._torrent({"name": "n", "state": "missingFiles", "progress": 1, "size": 1e9, "ratio": 1.234, "eta": 8640000, "added_on": 1700000000})
check("torrent shaping", t["progress"] == 100 and t["ratio"] == 1.23 and t["eta_min"] is None and t["added"] == "2023-11-14T22:13:20Z", json.dumps(t))

print(f"\n{'ALL OK' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
