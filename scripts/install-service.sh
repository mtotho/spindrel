#!/usr/bin/env bash
set -euo pipefail

# ── install-service.sh ───────────────────────────────────────────────────────
# Set up the Python venv, install deps, run migrations, and install the
# agent-server systemd service unit.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CURRENT_USER="${SUDO_USER:-$USER}"
VENV_DIR="$REPO_DIR/.venv"

if [ "$(id -u)" -ne 0 ]; then
    echo "error: This script must be run as root (or via sudo)." >&2
    exit 1
fi

# ── 1. Create .venv with python3.12 if it doesn't exist ─────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python 3.12 virtual environment …"
    python3.12 -m venv "$VENV_DIR"
    chown -R "$CURRENT_USER:$CURRENT_USER" "$VENV_DIR"
fi

# ── 2. Install requirements ─────────────────────────────────────────────────
echo "Installing Python dependencies …"
sudo -u "$CURRENT_USER" "$VENV_DIR/bin/pip" install --quiet -r "$REPO_DIR/requirements.txt"

# ── 3. Run database migrations ──────────────────────────────────────────────
echo "Running database migrations …"
sudo -u "$CURRENT_USER" bash -c "cd '$REPO_DIR' && source '$REPO_DIR/.env' 2>/dev/null; '$VENV_DIR/bin/alembic' upgrade head"

# ── 4. Write systemd unit file ──────────────────────────────────────────────
echo "Writing /etc/systemd/system/agent-server.service …"
cat > /etc/systemd/system/agent-server.service <<EOF
[Unit]
Description=Thoth Agent Server
After=network.target docker.service
Requires=docker.service

[Service]
User=$CURRENT_USER
WorkingDirectory=$REPO_DIR
EnvironmentFile=$REPO_DIR/.env
ExecStartPre=/usr/bin/docker compose -f $REPO_DIR/docker-compose.yml up -d postgres searxng playwright
ExecStart=$VENV_DIR/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ── 5. Enable and start ─────────────────────────────────────────────────────
echo "Enabling and starting agent-server.service …"
systemctl daemon-reload
systemctl enable agent-server.service
systemctl start agent-server.service

# ── 6. Print status ─────────────────────────────────────────────────────────
echo ""
echo "agent-server service installed and started."
systemctl status agent-server.service --no-pager || true
echo ""
echo "  Status:  systemctl status agent-server"
echo "  Logs:    journalctl -u agent-server -f"
