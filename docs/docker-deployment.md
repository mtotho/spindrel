# Running Agent Server in Docker

By default the server runs on the host with Python directly. This guide covers running the server itself inside Docker using the **sibling container pattern** — workspace and sandbox containers are peers on the host Docker daemon, not nested.

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

That's it. Your existing workspace data at `~/.spindrel-workspaces/` is mounted into the container. Existing workspace containers keep running (they're sibling containers on the host Docker daemon).

## How It Works

- The host Docker socket is mounted into the server container (`/var/run/docker.sock`)
- The server container has the Docker CLI installed (not the daemon)
- `WORKSPACE_LOCAL_DIR` (`/workspace-data`) is where the server reads/writes workspace files inside its own container
- `WORKSPACE_HOST_DIR` (`/home/you/.spindrel-workspaces`) is what gets passed to `docker -v` for child containers, since those mounts are resolved by the host daemon
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
| Docker CLI | Not in image | Installed (`docker.io` package) |
| docker-compose.yml | No socket mount | Mounts `/var/run/docker.sock` + workspace volume |
| Path handling | `os.path.expanduser(WORKSPACE_BASE_DIR)` everywhere | `local_workspace_base()` for file I/O, `local_to_host()` for docker `-v` args |
| Config | — | `WORKSPACE_HOST_DIR`, `WORKSPACE_LOCAL_DIR` in `app/config.py` |

## Networking

No changes needed. Workspace containers already get `--add-host host.docker.internal:host-gateway`. Since docker-compose exposes port 8000 on the host, `host.docker.internal:8000` reaches the server container via port forwarding. `SERVER_PUBLIC_URL` default is already `http://host.docker.internal:8000`.
