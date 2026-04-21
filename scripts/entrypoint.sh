#!/bin/bash
set -e

STARTUP_SCRIPT="${WORKSPACE_DATA_DIR:-/workspace-data}/startup.sh"

run_startup_as() {
    if [ -f "$STARTUP_SCRIPT" ]; then
        if [ -n "$1" ]; then
            echo "[entrypoint] Running workspace startup script as $1: $STARTUP_SCRIPT"
            gosu "$1" bash "$STARTUP_SCRIPT"
        else
            echo "[entrypoint] Running workspace startup script: $STARTUP_SCRIPT"
            bash "$STARTUP_SCRIPT"
        fi
    fi
}

# Drop from root to the unprivileged 'spindrel' user when possible.
# Keeps any RCE (e.g. via workspace exec, malicious tool, compromised
# bot) contained to UID 1000 instead of host-root. Volume ownership is
# left to the host; if the host user is not UID 1000, set it manually
# once (chown -R 1000:1000 <volume>) or skip this branch by running the
# container as an explicit --user.
if [ "$(id -u)" = "0" ] && id spindrel >/dev/null 2>&1; then
    chown -R spindrel:spindrel /app 2>/dev/null || true
    chown -R spindrel:spindrel /workspace-data 2>/dev/null || true
    # /home/spindrel is the persistent install-cache volume (npm-global,
    # pip cache, playwright browsers, agent ~/.local). First boot after
    # adding the volume leaves it root-owned — align to UID 1000.
    chown -R spindrel:spindrel /home/spindrel 2>/dev/null || true
    # /opt/spindrel-pkg holds dpkg-extracted apt packages (chromium, gh,
    # etc.) so they survive image rebuilds. Owned by spindrel so
    # install_system_package can dpkg -x into it without sudo; this keeps
    # the /etc/sudoers.d/spindrel-apt rule narrow (apt-get only).
    mkdir -p /opt/spindrel-pkg 2>/dev/null || true
    chown -R spindrel:spindrel /opt/spindrel-pkg 2>/dev/null || true
    chmod 0755 /opt/spindrel-pkg 2>/dev/null || true

    # The spindrel user needs the host docker-socket GID in its group
    # list to use /var/run/docker.sock (integration sidecar containers,
    # docker_stacks service).
    if [ -S /var/run/docker.sock ]; then
        DOCKER_GID="$(stat -c '%g' /var/run/docker.sock)"
        if ! getent group "$DOCKER_GID" >/dev/null 2>&1; then
            groupadd -g "$DOCKER_GID" hostdocker >/dev/null 2>&1 || true
        fi
        GROUP_NAME="$(getent group "$DOCKER_GID" | cut -d: -f1 || true)"
        if [ -n "$GROUP_NAME" ]; then
            usermod -aG "$GROUP_NAME" spindrel >/dev/null 2>&1 || true
        fi
    fi

    # Expose dpkg-extracted packages (see install_system_package) to every
    # child process. These env vars are the whole reason the persistent
    # /opt/spindrel-pkg layout works: binaries are NOT in /usr/bin but
    # shutil.which() still finds them, so the "is dep already installed?"
    # check in integration_deps.py skips reinstall on rebuild.
    export PATH="/opt/spindrel-pkg/usr/bin:/opt/spindrel-pkg/usr/local/bin:/opt/spindrel-pkg/usr/sbin:${PATH}"
    export LD_LIBRARY_PATH="/opt/spindrel-pkg/usr/lib/x86_64-linux-gnu:/opt/spindrel-pkg/usr/lib:${LD_LIBRARY_PATH:-}"

    run_startup_as spindrel
    exec gosu spindrel \
        env PATH="$PATH" LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
        uvicorn app.main:app --host 0.0.0.0 --port 8000
fi

# Fallback: non-root base image or spindrel user unavailable. Run as-is.
export PATH="/opt/spindrel-pkg/usr/bin:/opt/spindrel-pkg/usr/local/bin:/opt/spindrel-pkg/usr/sbin:${PATH}"
export LD_LIBRARY_PATH="/opt/spindrel-pkg/usr/lib/x86_64-linux-gnu:/opt/spindrel-pkg/usr/lib:${LD_LIBRARY_PATH:-}"
run_startup_as ""
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
