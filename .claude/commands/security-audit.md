# Security Audit — Full Infrastructure Review

Run a 3-agent security audit of the entire home server stack, then cross-reference findings and produce actionable results.

## Instructions

**Step 1 — Launch all 3 agents in parallel**

Launch these 3 agents simultaneously. Each agent MUST first read the `## Security Context` section in `CLAUDE.md` to understand known tradeoffs, then read ALL config files (`stacks/*.yaml`, `caddy/Caddyfile`, `compose.yaml`, `prometheus/prometheus.yml`, `scripts/setup.sh`, `.gitignore`) from their security perspective:

1. **container-hardening** — Docker security: capabilities, privilege escalation, read-only filesystems, image pinning, resource limits, volume permissions
2. **network-exposure** — Network attack surface: port exposure, TLS, Caddy headers, DNS privacy, VPN kill switch, inter-container isolation
3. **secrets-encryption** — Secrets management: .env handling, git history, encryption at rest, backup security, service authentication, Docker socket

Each agent returns findings grouped by severity.

**Step 2 — Cross-reference findings**

After all 3 agents report back, look for:
- **Overlapping findings** — same issue flagged by multiple agents (higher confidence)
- **Cascading risks** — e.g., a missing capability restriction + an exposed port = compound risk
- **Contradictions** — one agent says PASS, another flags the same area

**Step 3 — Produce the consolidated security report**

Output a single consolidated report as a copyable markdown block:

```
## CRITICAL (fix immediately)
- ...

## HIGH (fix soon)
- ...

## MEDIUM (improve when convenient)
- ...

## LOW / HARDENING (nice to have)
- ...

## PASSED CHECKS
- Summary of what's already well-configured

## ATTACK SURFACE SUMMARY
- Brief narrative: what's exposed, what's protected, what's the biggest remaining risk

## TOP 3 PRIORITY ACTIONS
1. ...
2. ...
3. ...
```

**Step 4 — Offer to fix**
Ask: "Want me to implement the fixes I can do from here (config file changes), and list the server-side commands for the rest?"

Note: This machine cannot run Docker commands — only config file changes can be made here. Server-side actions (restarting containers, checking running state) must be done manually on the server.
