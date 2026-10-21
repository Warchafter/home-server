#!/usr/bin/env python3
"""
Home Server MCP — read-only Model Context Protocol server.

Exposes the server's operational state as MCP tools over streamable HTTP:
container status/logs/events via dockerproxy, host and container metrics via
Prometheus, media-tree forensics on a read-only mount, and the apps' own
health/queue/library views via their APIs. Consumed by Claude Code (dev
laptop) and Odysseus (local LLM workspace) over the LAN / Tailscale, routed
through Caddy at :8105.

Deliberately READ-ONLY: no restart/exec/write tools. Docker access goes
through dockerproxy, which blocks all POST endpoints (POST=0); app clients
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
    mcp.run(transport="streamable-http")
