# Running Spindrel in Docker

Docker Compose is the normal self-hosted path for Spindrel. This guide covers the server container, the mounted workspace directory, and the **sibling container pattern** used by optional Docker sandboxes and integration sidecars.

## Quick Start

1. Add two lines to `.env`:

```bash
WORKSPACE_HOST_DIR=/home/you/.spindrel-workspaces
WORKSPACE_LOCAL_DIR=/workspace-data
```

2. Run the full stack:

```bash
docker compose up
```

That's it. Workspace data at `~/.spindrel-workspaces/` is mounted into the server container at `/workspace-data`. Normal command execution runs as server-side subprocesses against that mounted directory. Optional Docker sandboxes and integration-managed sidecars are sibling containers on the host Docker daemon.

## How It Works

- The host Docker socket is mounted into the server container (`/var/run/docker.sock`) for optional sandboxes and integration sidecars
- The server container has the Docker CLI installed (not the daemon)
- `WORKSPACE_LOCAL_DIR` (`/workspace-data`) is where the server reads/writes workspace files inside its own container
- `WORKSPACE_HOST_DIR` (`/home/you/.spindrel-workspaces`) is the host-side path used when optional sibling containers need the same workspace mounted, since those mounts are resolved by the host daemon
- When both vars are empty (default), the path translation is a no-op — identical to running on the host

## Switching Back to Host Mode

Comment out or remove the two env vars, then run the server on the host as before:

```bash
# WORKSPACE_HOST_DIR=
# WORKSPACE_LOCAL_DIR=
./scripts/dev-server.sh
```

Your workspace data at `~/.spindrel-workspaces/` is untouched either way.

## What Changed

| Component | Before | After |
|-----------|--------|-------|
| Docker CLI | Not in image | Installed (`docker-ce-cli` from official Docker repo) |
| docker-compose.yml | Host/dev server only | Mounts `/var/run/docker.sock` + workspace volume |
| Path handling | Single host path | `local_workspace_base()` for server file I/O, `local_to_host()` for optional sibling container `-v` args |
| Config | — | `WORKSPACE_HOST_DIR`, `WORKSPACE_LOCAL_DIR` in `app/config.py` |

## Networking

No changes needed. Workspace containers already get `--add-host host.docker.internal:host-gateway`. Since docker-compose exposes port 8000 on the host, `host.docker.internal:8000` reaches the server container via port forwarding. `SERVER_PUBLIC_URL` default is already `http://host.docker.internal:8000`.
