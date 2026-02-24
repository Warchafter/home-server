#!/usr/bin/env bash
# =============================================================================
# Home Server Bootstrap Script
# =============================================================================
# Run this on your HP server to install everything needed for the Docker stack.
#
# What it does:
#   1. Detects your Linux distribution
#   2. Updates system packages
#   3. Installs Docker Engine + Docker Compose v2
#   4. Configures Docker log rotation
#   5. Installs Tailscale
#   6. Fixes systemd-resolved conflict (so AdGuard Home can use port 53)
#   7. Creates .env from template
#
# Usage:
#   cd ~/home-server && bash scripts/setup.sh
#
# This script is idempotent — safe to run multiple times.
# =============================================================================

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the repo root (parent of scripts/)
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Global: detected server IP (set by detect_server_ip, used in final output)
DETECTED_IP=""

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

confirm() {
    read -r -p "$1 [y/N] " response
    [[ "$response" =~ ^[Yy]$ ]]
}

# Package management functions (avoids eval)
pkg_update() {
    case "$DISTRO" in
        ubuntu|debian) sudo apt update && sudo apt upgrade -y ;;
        fedora) sudo dnf upgrade -y ;;
        *) info "Skipping package update for $DISTRO" ;;
    esac
}

pkg_install() {
    case "$DISTRO" in
        ubuntu|debian) sudo apt install -y "$@" ;;
        fedora) sudo dnf install -y "$@" ;;
        *) info "Skipping package install for $DISTRO: $*" ;;
    esac
}

# ---------------------------------------------------------------------------
# Step 1: Detect Linux distribution
# ---------------------------------------------------------------------------

detect_distro() {
    info "Detecting Linux distribution..."

    if [ -f /etc/os-release ]; then
        # shellcheck source=/dev/null
        . /etc/os-release
        DISTRO="$ID"
        DISTRO_VERSION="${VERSION_ID:-unknown}"
        ok "Detected: $PRETTY_NAME"
    else
        fail "Cannot detect distribution. /etc/os-release not found."
    fi

    case "$DISTRO" in
        ubuntu|debian|fedora)
            ;;
        *)
            warn "Unsupported distro: $DISTRO. This script supports Ubuntu, Debian, and Fedora."
            warn "Docker and Tailscale may need manual installation."
            if ! confirm "Continue anyway?"; then
                exit 1
            fi
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Step 2: Update system packages
# ---------------------------------------------------------------------------

update_system() {
    info "Updating system packages..."
    if confirm "Run system update? This may take a few minutes."; then
        pkg_update
        ok "System updated."
    else
        warn "Skipping system update."
    fi
}

# ---------------------------------------------------------------------------
# Step 3: Install Docker Engine + Compose v2
# ---------------------------------------------------------------------------
# We install from Docker's official repository, NOT from the distro repos
# or Snap. The official repo gives us the latest stable Docker Engine and
# the Compose v2 plugin (the `docker compose` command, not `docker-compose`).
# ---------------------------------------------------------------------------

install_docker() {
    if command -v docker &> /dev/null; then
        ok "Docker is already installed: $(docker --version)"
        if docker compose version &> /dev/null; then
            ok "Docker Compose plugin: $(docker compose version)"
        else
            warn "Docker Compose plugin not found. Will install it."
        fi

        # Still ensure current user is in docker group
        if ! groups "$USER" | grep -q docker; then
            info "Adding $USER to the docker group..."
            sudo usermod -aG docker "$USER"
            warn "You'll need to log out and back in for this to take effect."
        fi
        return
    fi

    info "Installing Docker Engine from official repository..."

    case "$DISTRO" in
        ubuntu|debian)
            # Remove old/conflicting packages
            sudo apt remove -y docker.io docker-doc docker-compose \
                podman-docker containerd runc 2>/dev/null || true

            # Install prerequisites
            pkg_install ca-certificates curl gnupg

            # Add Docker's official GPG key
            sudo install -m 0755 -d /etc/apt/keyrings
            curl -fsSL "https://download.docker.com/linux/$DISTRO/gpg" | \
                sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
            sudo chmod a+r /etc/apt/keyrings/docker.gpg

            # Add the repository
            echo \
                "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
                https://download.docker.com/linux/$DISTRO \
                $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
                sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

            sudo apt update
            pkg_install docker-ce docker-ce-cli containerd.io \
                docker-buildx-plugin docker-compose-plugin
            ;;

        fedora)
            sudo dnf remove -y docker docker-client docker-client-latest \
                docker-common docker-latest docker-latest-logrotate \
                docker-logrotate docker-engine podman runc 2>/dev/null || true

            pkg_install dnf-plugins-core
            sudo dnf config-manager --add-repo \
                https://download.docker.com/linux/fedora/docker-ce.repo
            pkg_install docker-ce docker-ce-cli containerd.io \
                docker-buildx-plugin docker-compose-plugin
            ;;

        *)
            warn "Cannot auto-install Docker on $DISTRO."
            warn "Install Docker manually: https://docs.docker.com/engine/install/"
            if ! command -v docker &> /dev/null; then
                fail "Docker is not installed and cannot be auto-installed on $DISTRO."
            fi
            return
            ;;
    esac

    # Start and enable Docker
    sudo systemctl enable --now docker

    # Add current user to docker group so you don't need sudo for every command
    sudo usermod -aG docker "$USER"

    ok "Docker installed: $(docker --version)"
    ok "Compose plugin: $(docker compose version)"
    warn "IMPORTANT: Log out and back in for docker group permissions to take effect."
    warn "Or run 'newgrp docker' to activate in this session."
}

# ---------------------------------------------------------------------------
# Step 3b: Configure Docker log rotation
# ---------------------------------------------------------------------------
# Without this, Docker logs grow unbounded and will eventually fill your disk.
# This sets a 10MB max per log file, keeping 3 rotated files per container.
# ---------------------------------------------------------------------------

configure_docker_logging() {
    local daemon_json="/etc/docker/daemon.json"

    if [ -f "$daemon_json" ] && grep -q "max-size" "$daemon_json" 2>/dev/null; then
        ok "Docker log rotation is already configured."
        return
    fi

    info "Configuring Docker log rotation..."

    if [ -f "$daemon_json" ]; then
        warn "$daemon_json already exists. Please add log rotation manually:"
        echo '  "log-driver": "json-file", "log-opts": {"max-size": "10m", "max-file": "3"}'
        return
    fi

    sudo tee "$daemon_json" > /dev/null <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF

    # Restart Docker to apply (only if Docker is running)
    if systemctl is-active --quiet docker 2>/dev/null; then
        sudo systemctl restart docker
    fi

    ok "Docker log rotation configured (10MB max, 3 files per container)."
}

# ---------------------------------------------------------------------------
# Step 4: Install Tailscale
# ---------------------------------------------------------------------------
# Tailscale runs on the HOST (not in Docker) so it can provide VPN access
# to your entire local network, not just Docker containers.
# ---------------------------------------------------------------------------

install_tailscale() {
    if command -v tailscale &> /dev/null; then
        ok "Tailscale is already installed: $(tailscale version | head -1)"
        info "Current status: $(tailscale status --self 2>/dev/null || echo 'not connected')"
        return
    fi

    info "Installing Tailscale..."

    local installer="/tmp/tailscale-install.sh"
    curl -fsSL https://tailscale.com/install.sh -o "$installer"

    if confirm "Run the Tailscale installer?"; then
        sh "$installer"
        rm -f "$installer"
        ok "Tailscale installed."
    else
        rm -f "$installer"
        warn "Skipping Tailscale installation."
        return
    fi

    info "After setup completes, run:"
    echo "  sudo tailscale up --advertise-routes=192.168.x.0/24"
    echo "  (replace 192.168.x.0/24 with your actual LAN subnet)"
    echo ""
    info "See docs/tailscale-setup.md for the full guide."
}

# ---------------------------------------------------------------------------
# Step 5: Fix systemd-resolved (port 53 conflict)
# ---------------------------------------------------------------------------
# On Ubuntu (and some Debian installs), systemd-resolved runs a DNS stub
# listener on 127.0.0.53:53. This conflicts with AdGuard Home, which needs
# to bind to port 53 to serve DNS for your entire network.
#
# This function disables the stub listener while keeping systemd-resolved
# running for other purposes.
# ---------------------------------------------------------------------------

fix_resolved() {
    # Check if systemd-resolved is even running
    if ! systemctl is-active --quiet systemd-resolved 2>/dev/null; then
        ok "systemd-resolved is not running. No conflict to fix."
        return
    fi

    # Check if port 53 is already free (check both TCP and UDP)
    if ! sudo ss -tulnp | grep -q ':53 '; then
        ok "Port 53 is already available. No fix needed."
        return
    fi

    # Check if it's systemd-resolved holding port 53
    if ! sudo ss -tulnp | grep ':53 ' | grep -q 'resolved'; then
        warn "Port 53 is in use, but not by systemd-resolved. Check manually:"
        sudo ss -tulnp | grep ':53 '
        return
    fi

    info "systemd-resolved is using port 53. Fixing for AdGuard Home..."

    if confirm "Disable systemd-resolved's DNS stub listener?"; then
        # Disable the stub listener
        sudo mkdir -p /etc/systemd/resolved.conf.d
        echo -e "[Resolve]\nDNSStubListener=no" | \
            sudo tee /etc/systemd/resolved.conf.d/no-stub.conf > /dev/null

        # /etc/resolv.conf may be a symlink (Ubuntu default). Remove it first
        # so we write a real file, not through the symlink.
        sudo rm -f /etc/resolv.conf

        # Temporary resolver so the server has DNS during the transition
        echo "nameserver 1.1.1.1" | sudo tee /etc/resolv.conf > /dev/null

        # Restart to apply
        sudo systemctl restart systemd-resolved

        # Now point resolv.conf to systemd-resolved's full resolver
        sudo ln -sf /run/systemd/resolve/resolv.conf /etc/resolv.conf

        ok "DNS stub listener disabled. Port 53 is now available for AdGuard Home."
        info "To undo: sudo rm /etc/systemd/resolved.conf.d/no-stub.conf && sudo systemctl restart systemd-resolved"
    else
        warn "Skipped. AdGuard Home may fail to start if port 53 is occupied."
    fi
}

# ---------------------------------------------------------------------------
# Step 6: Detect server IP and create .env
# ---------------------------------------------------------------------------

detect_server_ip() {
    DETECTED_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -1)

    if [ -z "$DETECTED_IP" ]; then
        DETECTED_IP="192.168.1.100"
        warn "Could not auto-detect IP. Using placeholder: $DETECTED_IP"
    else
        ok "Detected server IP: $DETECTED_IP"
    fi
}

setup_env() {
    if [ -f "$REPO_DIR/.env" ]; then
        warn ".env already exists. Not overwriting."
        info "To recreate: rm .env && bash scripts/setup.sh"
        return
    fi

    info "Creating .env from template..."
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"

    # Replace placeholder values with detected ones
    sed -i "s/^SERVER_IP=.*/SERVER_IP=$DETECTED_IP/" "$REPO_DIR/.env"

    # Detect timezone
    local tz
    tz=$(timedatectl show --property=Timezone --value 2>/dev/null || echo "America/Chicago")
    sed -i "s|^TZ=.*|TZ=$tz|" "$REPO_DIR/.env"

    # Detect PUID/PGID
    sed -i "s/^PUID=.*/PUID=$(id -u)/" "$REPO_DIR/.env"
    sed -i "s/^PGID=.*/PGID=$(id -g)/" "$REPO_DIR/.env"

    ok "Created .env with detected values."
    info "Review it: nano $REPO_DIR/.env"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    echo ""
    echo "=========================================="
    echo "  Home Server Bootstrap"
    echo "=========================================="
    echo ""

    # Check sudo access
    if ! sudo -n true 2>/dev/null; then
        info "This script requires sudo access. You may be prompted for your password."
        sudo true || fail "Cannot obtain sudo. Run as a user with sudo access."
    fi

    detect_distro
    echo ""
    update_system
    echo ""
    install_docker
    echo ""
    configure_docker_logging
    echo ""
    install_tailscale
    echo ""
    fix_resolved
    echo ""
    detect_server_ip
    echo ""
    setup_env

    echo ""
    echo "=========================================="
    echo "  Setup complete!"
    echo "=========================================="
    echo ""
    echo "  Next steps:"
    echo ""
    echo "  1. Log out and back in (for Docker group permissions)"
    echo "     Or run: newgrp docker"
    echo "  2. Review your config:  nano .env"
    echo "  3. Start the stack:     docker compose up -d"
    echo "  4. Open dashboard:      http://$DETECTED_IP"
    echo "  5. AdGuard first-time:  http://$DETECTED_IP:3000 (one-time wizard)"
    echo "     AdGuard after setup: http://$DETECTED_IP:8091"
    echo "  6. Set up Tailscale:    see docs/tailscale-setup.md"
    echo ""
    echo "  IMPORTANT: Set a static IP for this server on your router"
    echo "  (DHCP reservation for $DETECTED_IP) to prevent IP changes."
    echo ""
    echo "=========================================="
}

# Run if executed directly (not sourced)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
