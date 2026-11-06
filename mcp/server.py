#!/usr/bin/env python3
"""
Home Server MCP — read-only Model Context Protocol server.

Exposes the server's operational state as MCP tools over streamable HTTP:
container status/logs/events via dockerproxy, host and container metrics via
Prometheus, media-tree forensics on a read-only mount, and the apps' own
health/queue/library views via their APIs. Consumed by Claude Code (dev
laptop) and Odysseus (local LLM workspace) over the LAN / Tailscale, routed
through Caddy at :8105.

Bearer-token auth is mandatory (MCP_AUTH_TOKEN, >= 32 chars, see auth.py);
the server refuses to start without it. /health stays open for the Docker
healthcheck.

Deliberately READ-ONLY: no restart/exec/write tools. Docker access goes
through dockerproxy's GET-only allowlist (dockerproxy/haproxy.cfg); app clients
only GET (qBittorrent needs one POST to log in); /media is mounted ro.

Modules register their tools on import:
    core          FastMCP instance, backends, helpers
    docker_tools  list_services, service_details, service_logs, service_logs_grep,
                  restart_events, docker_disk_usage
    prom_tools    prometheus_query, prometheus_query_range
    media_tools   media_usage, download_orphans
    apps          arr_status, qbittorrent_status, jellyfin_status, dns_check
    digest        health_summary
"""

from starlette.requests import Request
from starlette.responses import PlainTextResponse

from core import mcp
import docker_tools  # noqa: F401,E402
import prom_tools  # noqa: F401,E402
import media_tools  # noqa: F401,E402
import apps  # noqa: F401,E402
import digest  # noqa: F401,E402


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


if __name__ == "__main__":
    import logging
    import os

    import uvicorn

    from auth import BearerAuth

    token = os.environ.get("MCP_AUTH_TOKEN", "")
    if len(token) < 32:
        # Fail closed: an empty or short token would leave container logs and
        # app APIs readable by anyone on the LAN/tailnet.
        logging.critical("MCP_AUTH_TOKEN missing or shorter than 32 chars (openssl rand -hex 32); refusing to start")
        raise SystemExit(1)
    uvicorn.run(BearerAuth(mcp.streamable_http_app(), token), host="0.0.0.0", port=8000)
