#!/bin/sh
# =============================================================================
# install-tailscale.sh — Tailscale on a rooted LG webOS TV (Homebrew Channel)
# =============================================================================
# Puts the TV on the tailnet with a real network interface (kernel TUN), so the
# normal Jellyfin TV app can reach the home server at http://100.82.82.78:8093.
#
#   - Official static build from pkgs.tailscale.com, SHA-256 pinned below.
#   - Binaries: /media/developer/tailscale/bin   State: /var/lib/webosbrew/tailscale
#   - Boot: /var/lib/webosbrew/init.d/50-tailscale (Homebrew Channel run-parts)
#   - Joined with a tag:tv auth key, --shields-up (nothing on the tailnet can
#     connect TO the TV), no DNS/route changes, netfilter off (the TV kernel
#     has none). The tailnet policy limits tag:tv to Jellyfin only
#     (docs/lg-tv-tailscale.md).
#
# Run as root on the TV, from the directory holding this script and 50-tailscale:
#   sh install-tailscale.sh            # install/upgrade + join (prompts for key)
#   sh install-tailscale.sh uninstall  # stop, log out, remove everything
# To upgrade: bump VERSION and both SHA256 values, copy over, run again.
# =============================================================================
set -eu

VERSION=1.104.6
SHA256_ARM=98be19a248544f0d7809b71c2b6c3d1cb200aa347d3d0a47d9034dec5a26fc69
SHA256_ARM64=d0e4f297da3c428d02162c6235b9948e4ddc245c64502b7b05647da9b96a0971

BASE=/media/developer/tailscale
BIN=$BASE/bin
STATE=/var/lib/webosbrew/tailscale
INITD=/var/lib/webosbrew/init.d
HOOK=$INITD/50-tailscale
SOCK=/var/run/tailscale/tailscaled.sock
HERE=$(cd "$(dirname "$0")" && pwd)

die() { echo "ERROR: $*" >&2; exit 1; }
ts() { "$BIN/tailscale" --socket="$SOCK" "$@"; }
stop_daemon() {
  pkill -f "$BIN/tailscaled" 2>/dev/null || true
  for _ in 1 2 3 4 5; do pgrep -f "$BIN/tailscaled" >/dev/null 2>&1 || return 0; sleep 1; done
}

[ "$(id -u)" = 0 ] || die "run as root"

if [ "${1:-}" = uninstall ]; then
  [ -x "$BIN/tailscale" ] && ts logout 2>/dev/null || true
  stop_daemon
  rm -f "$HOOK"; rm -rf "$BASE" "$STATE" /var/run/tailscale
  echo "Removed. Also delete the 'lgtv' machine in the Tailscale admin console."
  exit 0
fi

[ -d "$INITD" ] || die "$INITD missing: Homebrew Channel not installed/rooted?"
[ -f "$HERE/50-tailscale" ] || die "50-tailscale must sit next to this script"
for c in curl sha256sum tar pkill; do command -v $c >/dev/null 2>&1 || die "missing tool: $c"; done

case "$(uname -m)" in
  aarch64) ARCH=arm64; SHA=$SHA256_ARM64 ;;
  arm*)    ARCH=arm;   SHA=$SHA256_ARM ;;
  *) die "unsupported CPU $(uname -m)" ;;
esac

# Kernel TUN — required for apps (Jellyfin) to use the tailnet
if [ ! -c /dev/net/tun ]; then
  modprobe tun 2>/dev/null || true
  mkdir -p /dev/net; [ -c /dev/net/tun ] || mknod /dev/net/tun c 10 200
fi
[ -c /dev/net/tun ] || die "/dev/net/tun unavailable: this TV can't run Tailscale as a real interface"

echo "Downloading Tailscale $VERSION ($ARCH)..."
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
curl -fsSL -o "$TMP/ts.tgz" "https://pkgs.tailscale.com/stable/tailscale_${VERSION}_${ARCH}.tgz"
GOT=$(sha256sum "$TMP/ts.tgz" | cut -d' ' -f1)
[ "$GOT" = "$SHA" ] || die "checksum mismatch (got $GOT) — not installing"
tar -xzf "$TMP/ts.tgz" -C "$TMP"

stop_daemon
mkdir -p "$BIN" "$STATE"; chmod 700 "$STATE"
cp "$TMP/tailscale_${VERSION}_${ARCH}/tailscale" "$TMP/tailscale_${VERSION}_${ARCH}/tailscaled" "$BIN/"
chmod 755 "$BIN/tailscale" "$BIN/tailscaled"
cp "$HERE/50-tailscale" "$HOOK"; chmod 755 "$HOOK"

echo "Starting tailscaled..."
sh "$HOOK"
for _ in $(seq 1 20); do ts status >/dev/null 2>&1 && break; [ -S "$SOCK" ] && break; sleep 1; done

STATE_NOW=$(ts status --json 2>/dev/null | grep -o '"BackendState": *"[A-Za-z]*"' | grep -o '[A-Za-z]*"$' | tr -d '"' || true)
if [ "$STATE_NOW" = Running ]; then
  echo "Already joined; re-applying settings."
  ts set --hostname=lgtv --accept-dns=false --accept-routes=false --shields-up=true
else
  printf 'Paste the tag:tv auth key (input hidden): '
  stty -echo 2>/dev/null || true; read -r KEY; stty echo 2>/dev/null || true; echo
  [ -n "$KEY" ] || die "no key entered"
  ts up --auth-key="$KEY" --hostname=lgtv --advertise-tags=tag:tv \
     --accept-dns=false --accept-routes=false --netfilter-mode=off --shields-up
  unset KEY
fi

echo
ts status | head -5
echo
ip addr show tailscale0 2>/dev/null | grep -E 'inet ' || echo "WARNING: no tailscale0 interface"
printf 'Jellyfin reachable: '
curl -s -m 10 -o /dev/null -w '%{http_code}\n' http://100.82.82.78:8093/health || echo "no"
echo "In the Jellyfin TV app, add server: http://100.82.82.78:8093"
