"""Mission Control container launcher.

Manages the Docker lifecycle for the Mission Control dashboard container.
Designed to be run as a subprocess by ProcessManager — blocks in foreground
and handles SIGTERM for graceful shutdown.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys


def _get_config():
    """Load config, works both inside and outside server process."""
    try:
        from integrations.mission_control.config import settings
        return settings
    except ImportError:
        pass

    # Fallback: read from env
    class _Env:
        MISSION_CONTROL_IMAGE = os.environ.get("MISSION_CONTROL_IMAGE", "mission-control:latest")
        MISSION_CONTROL_PORT = int(os.environ.get("MISSION_CONTROL_PORT", "9100"))
        MISSION_CONTROL_CONTAINER_NAME = os.environ.get("MISSION_CONTROL_CONTAINER_NAME", "mission-control")
        WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", os.path.expanduser("~/.agent-workspaces"))
        AGENT_SERVER_URL = os.environ.get("AGENT_SERVER_URL", "http://host.docker.internal:8000")

    return _Env()


def _container_exists(name: str) -> bool:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", name],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def _container_running(name: str) -> bool:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", name],
        capture_output=True, text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "running"


def main():
    cfg = _get_config()
    name = cfg.MISSION_CONTROL_CONTAINER_NAME

    # Graceful shutdown handler
    def _stop(*_args):
        print(f"[mission-control] Stopping container {name}...")
        subprocess.run(["docker", "stop", name], capture_output=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    # Verify docker is available
    docker_check = subprocess.run(["docker", "info"], capture_output=True)
    if docker_check.returncode != 0:
        print("[mission-control] ERROR: Docker is not available. Is the Docker daemon running?")
        sys.exit(1)

    # Verify workspace root exists
    ws_root = cfg.WORKSPACE_ROOT
    if not os.path.isdir(ws_root):
        print(f"[mission-control] WARNING: Workspace root {ws_root} does not exist, creating it...")
        os.makedirs(ws_root, exist_ok=True)

    api_key = os.environ.get("AGENT_API_KEY", "")

    if _container_running(name):
        print(f"[mission-control] Container {name} already running, attaching...")
        proc = subprocess.run(["docker", "logs", "-f", name])
        sys.exit(proc.returncode)

    if _container_exists(name):
        print(f"[mission-control] Starting existing container {name}...")
        proc = subprocess.run(["docker", "start", "-a", name])
        if proc.returncode != 0:
            print(f"[mission-control] Container failed to start (exit {proc.returncode}). Removing and recreating...")
            subprocess.run(["docker", "rm", name], capture_output=True)
        else:
            sys.exit(proc.returncode)

    # Check if image exists
    image = cfg.MISSION_CONTROL_IMAGE
    img_check = subprocess.run(["docker", "image", "inspect", image], capture_output=True)
    if img_check.returncode != 0:
        print(f"[mission-control] ERROR: Docker image '{image}' not found.")
        print(f"[mission-control] Build it with: cd integrations/mission_control/dashboard && docker build -t {image} .")
        sys.exit(1)

    # Build the docker run command
    cmd = [
        "docker", "run",
        "--name", name,
        "-v", f"{ws_root}:/workspaces:ro",
        "-p", f"{cfg.MISSION_CONTROL_PORT}:3000",
        "-e", f"AGENT_SERVER_URL={cfg.AGENT_SERVER_URL}",
        "-e", f"AGENT_SERVER_API_KEY={api_key}",
        "--add-host", "host.docker.internal:host-gateway",
        image,
    ]

    # Redact secrets from logged command
    safe_cmd = [c if not c.startswith("AGENT_SERVER_API_KEY=") else "AGENT_SERVER_API_KEY=***" for c in cmd]
    print(f"[mission-control] Starting container: {' '.join(safe_cmd)}")
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        print(f"[mission-control] Container exited with code {proc.returncode}")
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
