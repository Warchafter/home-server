# Project Instructions

## Project Overview

- Docker Compose-based home server running 24 containers on an HP EliteDesk 705 G4 DM (AMD Ryzen 5 PRO 2400G)
- Main compose file: `compose.yaml` (includes all stacks via `include:`)
- Individual service configs: `stacks/*.yaml`
- Reverse proxy: `caddy/Caddyfile`
- Monitoring: `prometheus/prometheus.yml`, `grafana/` dashboards
- Deployment guide: `docs/deployment.md`

## Identity & Git Attribution

- This is a **personal project**. All commits must use the personal identity:
  - **Email:** kevin.arriaga@gmail.com
  - **Username:** Warchafter
- Before any `git commit` or `git push`, verify with `git config user.email` that it returns the personal email.
- Remote URL must use the personal SSH alias: `git@github-personal:Warchafter/home-server.git`
- Do **not** use `git@github.com` directly — it maps to the work SSH key.

## Environment Isolation

- All file reads and searches must be restricted to this project directory (`~/Personal/home-server/`).
- Do **not** pull context, environment variables, or snippets from `~/work/` or any work-related directories.
- Do **not** use company-specific Jira tags, internal ticket formatting, or work conventions in commit messages.

## Remote Workflow

- This development machine is **separate** from the home server at 192.168.0.117.
- **Never** run `docker exec`, `docker logs`, `docker compose`, or any Docker commands — they won't work from here. Those must be run manually on the server.
- Code changes are committed and pushed here, then pulled and applied on the server separately.
- When giving deployment instructions, provide the exact commands the user should run on the server — do not attempt to run them.

## Changing Service Configurations

- **Always check healthchecks before changing ports or enabling new service features.** Enabling Gluetun's HTTP control server once broke its healthcheck, which cascaded and took down qBittorrent too (via `network_mode: service:gluetun`).
- When asked to restart services, restart **all** the services requested — not a subset. Claude has repeatedly only restarted some of the requested services.
- When modifying a stack file, check for `depends_on`, `network_mode: service:*`, and healthcheck configurations that could be affected by your change.
- Services that share network namespaces (e.g., qBittorrent through Gluetun) are especially fragile — changes to one affect the other.

## Security Context

These facts calibrate the security audit agents so they don't flag known tradeoffs as vulnerabilities:

- **LAN-only** — no public domain configured yet. No port forwarding on the router. All services are reachable only from 192.168.0.x and Tailscale.
- **Ports bound to 0.0.0.0 intentionally** — required for Tailscale access. Binding to `${SERVER_IP}` would break Tailscale connectivity. This is an accepted tradeoff given the LAN-only + no port forwarding setup.
- **No TLS on Caddy (expected)** — Caddy runs HTTP because there's no domain. `tls internal` would generate self-signed certs causing browser warnings on every device. This becomes a real finding only when a public domain is added.
- **cAdvisor requires `/var/run` + `SYS_ADMIN`** — this is a known cAdvisor requirement for cgroup access and container metrics, not a misconfiguration. The mitigation is `cap_drop: ALL` with only `SYS_ADMIN` and `DAC_READ_SEARCH` added.
- **Jellyfin CSP/X-Frame-Options removed intentionally** — the LG webOS Jellyfin app renders via iframe, which `SAMEORIGIN` blocks (error -27). If re-adding CSP, scope `frame-ancestors` to LG webOS origins, never use a wildcard.
- **Docker socket on autoheal** — autoheal needs Docker socket access to restart unhealthy containers. Verify it goes through dockerproxy; if not, flag it.

## Security Audit

- Run `/security-audit` to perform a full 3-agent infrastructure security review.
- Agents: **container-hardening** (Docker security), **network-exposure** (network attack surface), **secrets-encryption** (secrets/encryption/auth).
- The audit reads all config files and produces a prioritized report with actionable fixes.
- Config file changes can be made from here; server-side commands must be run manually on the server.
- Run this audit after any significant infrastructure change (new service, port change, network config).
- **Agents must read the Security Context section above** before producing findings — do not flag known tradeoffs as vulnerabilities.

## Commit Style

- Keep commit messages clean and personal-project appropriate.
- Use conventional commit style (e.g., `feat:`, `fix:`, `docs:`, `chore:`).
- **Never** add `Co-Authored-By` lines to commit messages.
