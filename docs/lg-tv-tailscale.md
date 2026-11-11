# LG TV on the tailnet (Jellyfin away from home)

Puts a **rooted** LG webOS TV (Homebrew Channel, root SSH) on the tailnet with a
real network interface, so the normal Jellyfin TV app can reach the home server
at `http://100.82.82.78:8093` from any location. No laptop + HDMI needed.

Files: `host/lgtv/install-tailscale.sh` (installer, pinned official build,
SHA-256 checked) and `host/lgtv/50-tailscale` (Homebrew Channel boot hook).

**The TV is treated as untrusted.** It joins as `tag:tv`, with these limits:
- **`--shields-up`:** nothing on the tailnet can connect to it.
- **Tailnet policy:** it can reach **only Jellyfin (TCP 8093) on the server**.
  No Vaultwarden, SSH, other ports, or your other devices.
- **No changes to the TV's network:** it doesn't take Tailscale DNS or routes.
  The kernel has no netfilter, so netfilter mode is off.

---

## 1. Tailnet policy (admin console → Access controls)

Add the tag owner, and stop the allow-all rule from covering tagged devices.

Find the existing allow-all rule. It looks like either of these:
```jsonc
"grants": [{"src": ["*"], "dst": ["*"], "ip": ["*"]}]
"acls":   [{"action": "accept", "src": ["*"], "dst": ["*:*"]}]
```
Change its `"src": ["*"]` to `"src": ["autogroup:member"]`. Your own devices
keep full access; tagged devices no longer get it. Then add:
```jsonc
"tagOwners": {"tag:tv": ["autogroup:admin"]},
```
and, in the same list as that rule, the TV's only permission:
```jsonc
// grants syntax:
{"src": ["tag:tv"], "dst": ["100.82.82.78"], "ip": ["tcp:8093"]},
// or acls syntax:
{"action": "accept", "src": ["tag:tv"], "dst": ["100.82.82.78:8093"]},
```
Optionally add tests; the editor refuses to save if one fails:
```jsonc
"tests": [
  {"src": "tag:tv", "accept": ["100.82.82.78:8093"], "deny": ["100.82.82.78:22", "100.82.82.78:8092"]}
]
```
If you later apply the `tag:server` policy from security-hardening.md §3,
change the TV rule's destination to `tag:server` / `tag:server:8093`.

## 2. Auth key (admin console → Settings → Keys → Generate auth key)

| Setting | Value |
|---|---|
| Description | `lgtv` |
| Reusable | off |
| Expiration | 1 day (it's only for joining; tagged nodes don't expire) |
| Ephemeral | off |
| Tags | `tag:tv` |
| Pre-approved | on (needed if device approval is enabled) |

Copy the key. You'll paste it into the installer's hidden prompt, never into
chat or a file.

## 3. Install (from the laptop, on the TV's network)

```bash
scp -O host/lgtv/install-tailscale.sh host/lgtv/50-tailscale root@<tv-ip>:/tmp/
ssh root@<tv-ip> 'cd /tmp && sh install-tailscale.sh'
```
`scp -O` matters: the TV's SSH server (dropbear) has no SFTP, and modern scp
uses SFTP by default.

The installer checks root, Homebrew Channel and `/dev/net/tun`, verifies the
download checksum, installs the boot hook, starts `tailscaled` and prompts for
the key. It ends by printing `tailscale status`, the `tailscale0` address and
`Jellyfin reachable: 200`.

Run the same `ssh` line to upgrade (after bumping VERSION and both SHA256s in the
script and copying it again) or to re-apply settings. `sh install-tailscale.sh uninstall`
removes everything.

## 4. Jellyfin app on the TV

*Add server* → `http://100.82.82.78:8093`, then log in as usual. If playback
buffers, set a lower *Max streaming bitrate* in the app's playback settings.
Streams away from home are capped by the home connection's **upload** speed,
and Jellyfin transcodes (VAAPI) to fit.

## 5. Harden the TV itself

- **Root password:** Homebrew Channel's SSH starts with root password `alpine`.
  Change it (`passwd` on the TV), or switch to key-only login in Homebrew
  Channel's settings. Anyone on the TV's local network can otherwise get root.
- After a TV firmware update, check root and Homebrew Channel still work
  (`ssh root@<tv-ip> 'pgrep -fl tailscaled'`). LG updates can remove root.

## Troubleshooting

```bash
ssh root@<tv-ip> '/media/developer/tailscale/bin/tailscale --socket=/var/run/tailscale/tailscaled.sock status; tail -30 /var/lib/webosbrew/tailscale/tailscaled.log'
```
- **`Jellyfin reachable: 000`, but status shows the server online:** check the
  policy's `tag:tv` rule (test with the "tests" block above).
- **No `tailscale0`:** the kernel TUN device is missing. This model can't run
  Tailscale as a real interface. Use a Google TV / Android TV stick with the
  official Tailscale and Jellyfin apps instead.
