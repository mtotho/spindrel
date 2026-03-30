#!/usr/bin/env bash
set -euo pipefail

# ── install-service.sh ───────────────────────────────────────────────────────
# Install Spindrel systemd services: the main server + any integration services
# discovered under integrations/*/service.
#
# Paths are resolved from where the repo actually lives. User/group default
# to the owner of the repo directory (override with -u/-g flags).
#
# Usage:
#   sudo ./scripts/install-service.sh              # auto-detect user from repo owner
#   sudo ./scripts/install-service.sh -u myuser    # explicit user
#   sudo ./scripts/install-service.sh -u myuser -g mygroup

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Parse flags ──────────────────────────────────────────────────────────────
SVC_USER=""
SVC_GROUP=""
while getopts "u:g:" opt; do
    case $opt in
        u) SVC_USER="$OPTARG" ;;
        g) SVC_GROUP="$OPTARG" ;;
        *) echo "Usage: $0 [-u user] [-g group]" >&2; exit 1 ;;
    esac
done

# Default user/group to repo directory owner
if [ -z "$SVC_USER" ]; then
    SVC_USER="$(stat -c '%U' "$REPO_DIR")"
fi
if [ -z "$SVC_GROUP" ]; then
    SVC_GROUP="$(stat -c '%G' "$REPO_DIR")"
fi

# ── Detect venv directory name ───────────────────────────────────────────────
if [ -d "$REPO_DIR/.venv" ]; then
    VENV=".venv"
elif [ -d "$REPO_DIR/venv" ]; then
    VENV="venv"
else
    echo "error: No virtualenv found at $REPO_DIR/.venv or $REPO_DIR/venv" >&2
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "error: This script must be run as root (or via sudo)." >&2
    exit 1
fi

echo "Install dir:  $REPO_DIR"
echo "Venv:         $VENV"
echo "User/group:   $SVC_USER:$SVC_GROUP"
echo ""

# ── Create user if needed ────────────────────────────────────────────────────
if ! id -u "$SVC_USER" >/dev/null 2>&1; then
    echo "Creating system user '$SVC_USER'..."
    useradd --system --create-home --shell /usr/sbin/nologin "$SVC_USER"
fi

# ── Add user to docker group ────────────────────────────────────────────────
if getent group docker >/dev/null 2>&1; then
    if ! id -nG "$SVC_USER" | grep -qw docker; then
        echo "Adding '$SVC_USER' to docker group..."
        usermod -aG docker "$SVC_USER"
    fi
else
    echo "warning: docker group does not exist. Docker commands may fail." >&2
fi

# ── Helper: substitute placeholders and install a service file ───────────────
install_unit() {
    local template="$1"
    local unit_name="$2"

    echo "Installing $unit_name..."
    sed \
        -e "s|__INSTALL_DIR__|$REPO_DIR|g" \
        -e "s|__VENV__|$VENV|g" \
        -e "s|__USER__|$SVC_USER|g" \
        -e "s|__GROUP__|$SVC_GROUP|g" \
        "$template" > "/etc/systemd/system/$unit_name"
}

# ── Stop and remove old services ─────────────────────────────────────────────
# Kill anything on port 8000 (stale processes from renamed/removed services)
echo "Cleaning up old services..."
OLD_PID="$(ss -tlnp | grep ':8000 ' | grep -oP 'pid=\K\d+' || true)"
if [ -n "$OLD_PID" ]; then
    echo "Killing stale process on port 8000 (pid $OLD_PID)..."
    kill "$OLD_PID" 2>/dev/null || true
    sleep 1
fi

# Stop+disable any old services (catches old names like thoth.service, agent-server.service)
for old_unit in /etc/systemd/system/spindrel*.service /etc/systemd/system/thoth*.service /etc/systemd/system/agent-server*.service; do
    [ -f "$old_unit" ] || continue
    unit_name="$(basename "$old_unit")"
    echo "Stopping old service: $unit_name"
    systemctl stop "$unit_name" 2>/dev/null || true
    systemctl disable "$unit_name" 2>/dev/null || true
    rm -f "$old_unit"
done
systemctl daemon-reload

UNITS=()

# ── Main service ─────────────────────────────────────────────────────────────
install_unit "$REPO_DIR/systemd/spindrel.service" "spindrel.service"
UNITS+=("spindrel.service")

# ── Integration services (auto-discover) ─────────────────────────────────────
for svc_file in "$REPO_DIR"/integrations/*/service; do
    [ -f "$svc_file" ] || continue
    integration_id="$(basename "$(dirname "$svc_file")")"
    install_unit "$svc_file" "spindrel-$integration_id.service"
    UNITS+=("spindrel-$integration_id.service")
done

# ── Build Docker images (before starting services) ──────────────────────────
echo "Building Docker images..."
sudo -u "$SVC_USER" /usr/bin/docker compose -f "$REPO_DIR/docker-compose.yml" build

# ── Reload + enable + start ──────────────────────────────────────────────────
systemctl daemon-reload

for unit in "${UNITS[@]}"; do
    echo "Enabling $unit..."
    systemctl enable "$unit"
done

# Start main service first, then integrations
echo "Starting ${UNITS[0]}..."
systemctl start "${UNITS[0]}"

for unit in "${UNITS[@]:1}"; do
    echo "Starting $unit..."
    systemctl start "$unit"
done

echo ""
echo "Installed ${#UNITS[@]} service(s):"
for unit in "${UNITS[@]}"; do
    echo "  - $unit"
done

# ── Install spindrel CLI symlink ─────────────────────────────────────────────
CLI_SCRIPT="$REPO_DIR/scripts/spindrel"
CLI_LINK="/usr/local/bin/spindrel"
if [ -x "$CLI_SCRIPT" ]; then
    ln -sf "$CLI_SCRIPT" "$CLI_LINK"
    echo ""
    echo "CLI installed: $CLI_LINK → $CLI_SCRIPT"
fi

echo ""
echo "Commands:"
echo "  spindrel status    Show service status"
echo "  spindrel restart   Restart services"
echo "  spindrel logs      Tail logs"
echo "  spindrel --help    All commands"
