#!/usr/bin/env bash
set -euo pipefail

# ── install-service.sh ───────────────────────────────────────────────────────
# Install the Thoth systemd service unit, create the thoth user if needed,
# and enable + start the service.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
UNIT_FILE="$REPO_DIR/systemd/thoth.service"
INSTALL_DIR="/opt/thoth"

if [ "$(id -u)" -ne 0 ]; then
    echo "error: This script must be run as root (or via sudo)." >&2
    exit 1
fi

# ── Create thoth user if needed ──────────────────────────────────────────────
if ! id -u thoth >/dev/null 2>&1; then
    echo "Creating system user 'thoth'..."
    useradd --system --create-home --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin thoth
    echo "User 'thoth' created."
else
    echo "User 'thoth' already exists."
fi

# ── Add thoth to docker group ────────────────────────────────────────────────
if getent group docker >/dev/null 2>&1; then
    if ! id -nG thoth | grep -qw docker; then
        echo "Adding 'thoth' to docker group..."
        usermod -aG docker thoth
    fi
else
    echo "warning: docker group does not exist. Docker commands may fail." >&2
fi

# ── Install systemd unit ─────────────────────────────────────────────────────
echo "Installing systemd unit file..."
cp "$UNIT_FILE" /etc/systemd/system/thoth.service
systemctl daemon-reload

# ── Enable + start ───────────────────────────────────────────────────────────
echo "Enabling thoth.service..."
systemctl enable thoth.service

echo "Starting thoth.service..."
systemctl start thoth.service

echo ""
echo "Thoth service installed and started."
echo "  Status:  systemctl status thoth"
echo "  Logs:    journalctl -u thoth -f"
