# Security & Privacy Hardening (host, Tailscale, apps)

Already handled in the repo (deployed via docs/upgrade-2026-11.md): every image
current, autoheal behind a restart-only Docker API proxy instead of the raw
socket, MCP bearer-token auth, Homepage host allowlist, Grafana telemetry off,
encrypted offsite backups (docs/backups.md), patch alerts in alert-check.py.
This guide covers what can't: host settings, the Tailscale admin console, and
settings that live inside each app's own database. Work top to bottom — the
order matters for SSH (don't lock yourself out) and for Tailscale Serve
(rename the machine *before* a certificate publishes its name).

Threat model this is tuned for: LAN-only, no port forwarding, remote access
only via Tailscale. The realistic risks are (1) one compromised device on the
LAN or tailnet reaching everything, (2) the single NVMe dying with no copy of
the data, (3) unpatched software, and (4) metadata leaking to third parties
(DNS queries to the ISP, telemetry, discovery servers, CT logs).

---

## 1. SSH: keys only

From the **laptop** (keep an existing server session open until the last check below passes):

```bash
ssh-copy-id -i ~/.ssh/id_ed25519_personal.pub -o GSSAPIAuthentication=no wachacha@192.168.0.117
ssh -i ~/.ssh/id_ed25519_personal -o GSSAPIAuthentication=no -o PasswordAuthentication=no wachacha@192.168.0.117 true && echo KEY OK
```

Only continue if it prints `KEY OK`. Then **on the server**:

```bash
cd ~/home-server
sudo install -m 0644 host/ssh/00-hardening.conf /etc/ssh/sshd_config.d/
sudo sshd -t                                   # syntax check — must print nothing
sudo sshd -T | grep -Ei '^(passwordauthentication|kbdinteractive|permitrootlogin|authenticationmethods)'
sudo systemctl reload ssh
```

`sshd -T` must show `passwordauthentication no`. Verify from a **new** laptop
terminal that both a key login works and a password login is refused:

```bash
ssh -o GSSAPIAuthentication=no wachacha@192.168.0.117 true && echo KEY OK
ssh -o PubkeyAuthentication=no -o GSSAPIAuthentication=no wachacha@192.168.0.117   # expect: Permission denied (publickey)
```

Rollback (from the still-open session or the console): `sudo rm /etc/ssh/sshd_config.d/00-hardening.conf && sudo systemctl reload ssh`.

## 2. OS patching

```bash
sudo apt update && sudo apt full-upgrade
sudo apt install unattended-upgrades
sudo install -m 0644 host/apt/52unattended-upgrades-local /etc/apt/apt.conf.d/
sudo unattended-upgrade --dry-run --debug 2>&1 | tail -5
sudo reboot
```

From then on Ubuntu security updates install daily on their own. Docker and
Tailscale are excluded (a Docker daemon restart takes every container down) —
upgrade those by hand. `scripts/alert-check.py` now alerts when security
updates are pending or a reboot has been required for 3+ days.

## 3. Tailscale

**Upgrade** (server was on 1.94.2; check the laptop too):
```bash
sudo apt update && sudo apt install --only-upgrade tailscale && tailscale version
```

**Keep the server off MagicDNS** (it *is* the DNS server; Tailscale has
re-enabled this twice after a `tailscale up`):
```bash
sudo tailscale set --accept-dns=false
resolvectl status | grep -E 'Current DNS|resolv.conf mode'   # must NOT list 100.100.100.100
```

**Admin console** (login.tailscale.com/admin):
- *Machines → server → Disable key expiry.* The always-on node should never
  silently drop off the tailnet again (2026-09-07 outage).
- *Settings → Device management → Device approval: on.* A stolen auth key or
  login can no longer add a device without you approving it.
- *Access controls:* replace the default allow-all policy. Your devices can
  reach the server, the LAN subnet route, and the internet via the exit node;
  the server can't initiate connections to your laptop/phone; Tailscale SSH
  stays off:
  ```json
  {
    "grants": [
      {"src": ["autogroup:member"], "dst": ["autogroup:self"],   "ip": ["*"]},
      {"src": ["autogroup:member"], "dst": ["100.82.82.78"],     "ip": ["*"]},
      {"src": ["autogroup:member"], "dst": ["192.168.0.0/24"],   "ip": ["*"]},
      {"src": ["autogroup:member"], "dst": ["autogroup:internet"], "ip": ["*"]}
    ],
    "ssh": []
  }
  ```
  If you share the tailnet with anyone, narrow `autogroup:member` to your own
  login. Use the editor's *Preview rules* before saving.
- *Optional — Tailnet Lock* (`tailscale lock init`, see Tailscale docs). This is
  what Headscale was on the roadmap for: with it, Tailscale's coordination
  server can't add a node to your tailnet even if it were compromised. It needs
  two signing devices (laptop + phone) and every new node must be signed.

**Exit node** (replaces the WireGuard/wg-easy plan — routes a device's traffic
through home when on untrusted Wi-Fi, no port forwarding):
```bash
sudo tailscale set --advertise-exit-node
```
Approve it in *Machines → server → Edit route settings → Use as exit node*,
then pick it on the phone/laptop when needed. Traffic leaves via your home
ISP, and DNS goes through AdGuard (section 5).

## 4. Vaultwarden over real HTTPS (Tailscale Serve)

The Bitwarden mobile apps reject the self-signed cert. Tailscale Serve gives a
Let's Encrypt cert for `<machine>.<tailnet>.ts.net`, no domain needed.

**Privacy first:** issuing that certificate writes the full hostname to the
public Certificate Transparency logs, permanently. The current machine name
`wachacha-server-dev` contains your username. Rename it before enabling HTTPS:
*Machines → server → Edit machine name* (e.g. `home`). The Tailscale IP does
not change; update anything that uses the MagicDNS name.

Then: *DNS → HTTPS Certificates → Enable*, and on the server:
```bash
sudo tailscale serve --bg --https=443 https+insecure://localhost:8092
tailscale serve status
```

`https+insecure` is fine here: the hop is localhost → container, and
Vaultwarden keeps its own self-signed TLS for LAN clients on :8092. Point the
mobile apps and browser extension at `https://home.<tailnet>.ts.net`. Once
every client uses that URL, set `VAULTWARDEN_DOMAIN=https://home.<tailnet>.ts.net`
in `.env` and `docker compose up -d vaultwarden` — Vaultwarden needs DOMAIN to
match the URL for passkey/FIDO2 2FA and attachment links.

Serve is only reachable from the tailnet (Funnel stays off — check with
`tailscale funnel status`).

## 5. DNS privacy (AdGuard)

If AdGuard's upstream is a plain IP such as 1.1.1.1 (what docs/go-time.md
suggested), queries leave in plaintext and your ISP sees every domain every
device looks up. Check and switch to encrypted upstreams. *AdGuard → Settings → DNS settings*:

- **Upstream DNS servers** (encrypted):
  ```
  https://dns.quad9.net/dns-query
  https://cloudflare-dns.com/dns-query
  ```
  Mode: *Load-balancing* or *Parallel requests*.
- **Bootstrap DNS**: `9.9.9.9` and `1.1.1.1` (used only to resolve the DoH hostnames).
- **Enable DNSSEC**: on.
- Leave *Disable resolving of IPv6 addresses* as it is.

Self-hosted Unbound (recursive) was on the roadmap; it removes the resolver
operator from the picture but sends every query to authoritative servers in
plaintext, i.e. back in view of the ISP. Encrypted upstream is the better
privacy trade for a home connection.

## 6. Syncthing privacy

Syncthing announces your device ID and public IP to syncthing.net discovery
servers and may relay traffic through community relays. With Tailscale you
need neither. On **every** device (*Actions → Settings → Connections*):

- *Global Discovery*: off. *Enable Relaying*: off. *Enable NAT traversal*: off.
- Keep *Local Discovery* on (LAN).
- *Actions → Settings → General → Anonymous Usage Reporting*: disabled.

Then for each remote device (*Edit device → Advanced → Addresses*) replace
`dynamic` with its Tailscale address, e.g. `tcp://100.82.82.78:22000, dynamic`
on the phone/laptop entries for the server. Devices must have Tailscale up to
sync when away from home. This also ends the `relays.syncthing.net` retry loop.

**GUI password:** *Actions → Settings → GUI → GUI Authentication User/Password*
must be set — the Syncthing UI (via Caddy :8099) can add shares and read
every synced file.

## 7. App settings checklist (live in each app's database)

Authentication — every UI is reachable by any LAN/tailnet device:

| App | Setting |
|---|---|
| Sonarr / Radarr / Prowlarr | Settings → General → Authentication *Forms*, Authentication Required *Enabled* (not "Disabled for local addresses" — Docker traffic via Caddy counts as local) |
| Bazarr | Settings → General → Security → Authentication *Form* |
| qBittorrent | Web UI → keep *Bypass authentication for clients on localhost* (Gluetun port sync needs it); make sure *Bypass for clients in whitelisted IP subnets* is **off** |
| Calibre-Web | Change the default `admin` / `admin123` login if it was never changed |
| Syncthing | GUI user/password (section 6) |
| AdGuard, Grafana, Kavita, Uptime Kuma, Home Assistant, Seerr, Cleanuparr, Backrest | have their own login — use unique passwords stored in Vaultwarden |
| MCP | `MCP_AUTH_TOKEN` in `.env` (stacks/mcp.yaml) |
| Homepage | optional login (`HOMEPAGE_AUTH_*` in `.env`). Recommended once you browse by the MagicDNS name: it also closes the unauthenticated `/api/services/proxy` widget endpoints that serve queue/torrent data |

Telemetry — turn off where it exists:

| App | Setting |
|---|---|
| Sonarr / Radarr / Prowlarr | Settings → General → Analytics → *Send Anonymous Usage Data*: off |
| Bazarr | Settings → General → Analytics: off |
| Home Assistant | Settings → System → Analytics: everything off |
| Syncthing | Anonymous Usage Reporting: off (section 6) |
| Grafana | done in stacks/grafana.yaml (`GF_ANALYTICS_*`) |
| Kavita | Settings → Server → *Allow anonymous usage collection* (if present): off |

## 8. Verify

```bash
python3 scripts/alert-check.py --print          # no pending security updates / reboot
sudo sshd -T | grep passwordauthentication       # no
tailscale status && tailscale serve status       # serve → :8092 only; no funnel
resolvectl status | grep 'Current DNS'           # not 100.100.100.100
```
Then run `/security-audit` from the dev machine.
