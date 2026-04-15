#!/bin/bash
set -e

# Run workspace startup script if present (lives on persistent volume).
# Integrations and bots can append install commands here; they survive
# container restarts and image rebuilds.
STARTUP_SCRIPT="${WORKSPACE_DATA_DIR:-/workspace-data}/startup.sh"
if [ -f "$STARTUP_SCRIPT" ]; then
    echo "[entrypoint] Running workspace startup script: $STARTUP_SCRIPT"
    bash "$STARTUP_SCRIPT"
fi

# Start the server
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
