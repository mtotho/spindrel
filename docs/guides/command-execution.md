# Command Execution

![Chat command execution — Orion runs a Python snippet via `exec_command` and the assistant turn shows the EXEC COMMAND tool badge plus the raw stdout in a fenced code block](../images/chat-command-execution.png)

Spindrel bots can execute shell commands in several ways, each with different isolation levels, security controls, and client compatibility. This guide explains when to use each mode and how to configure them.

## Quick Decision Guide

| I want to... | Use | Works from |
|---|---|---|
| Run code in an isolated container | [Docker Workspace](#docker-workspace) | All clients |
| Run commands on the server host | [Host Workspace](#host-workspace) or [Host Exec](#host-exec-legacy) | All clients |
| Run commands on the user's local machine | [Client Tools](#client-tools-shell_exec) | CLI only |
| Run commands asynchronously (fire-and-forget) | [Deferred Execution](#deferred-execution) | All clients |

!!! tip "Recommended default"
    **Docker Workspace** is the safest and most portable option. Start here unless you have a specific reason to use host execution.

---

## Where Commands Run

Understanding **where** a command executes is the most important distinction:

```
┌─────────────────────────────────────────────────────────┐
│  Server Host                                            │
│  ┌──────────────────────┐  ┌─────────────────────────┐  │
│  │  Docker Workspace    │  │  Host Workspace /       │  │
│  │  (container)         │  │  Host Exec              │  │
│  │                      │  │  (native process)       │  │
│  │  Isolated filesystem │  │  Direct host access     │  │
│  │  Optional network    │  │  Configurable allowlist │  │
│  └──────────────────────┘  └─────────────────────────┘  │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  User's Machine (CLI client only)                       │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Client Tool: shell_exec                         │   │
│  │  Runs with user's full permissions               │   │
│  │  Only accessible from the CLI agent client       │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

**Key point:** Docker Workspace and Host Workspace/Host Exec run on the **server** and work from **any client** (Slack, Discord, web UI, CLI). Client tools (`shell_exec`) run on the **user's local machine** and only work from the **CLI client**.

---

## Docker Workspace

The recommended approach. Commands run inside a Docker container on the server.

### Bot YAML Configuration

```yaml
workspace:
  enabled: true
  type: docker
  docker:
    image: python:3.12-slim     # any Docker image
    network: none               # "none" (isolated) or "bridge" (internet access)
    env:                        # environment variables inside container
      PYTHONUNBUFFERED: "1"
    mounts:                     # host directories to mount
      - host_path: /home/user/projects
        container_path: /workspace/projects
        mode: rw                # "ro" or "rw"
    user: ""                    # container user (empty = image default)
    read_only_root: false       # lock down root filesystem
    cpus: 2.0                   # CPU limit
    memory: 1gb                 # memory limit
  timeout: 60                   # command timeout (seconds)
  max_output_bytes: 1048576     # output size cap

local_tools:
  - exec_command                # synchronous execution
  - delegate_to_exec            # supports async/deferred mode
```

### What You Get

- **Isolation**: Commands run in a container, not on the host
- **Reproducible environment**: Pin the image version for consistent behavior
- **Startup scripts**: Place a `startup.sh` in the workspace root to install dependencies on container start
- **File indexing**: Enable `workspace.indexing.enabled: true` for semantic search over workspace files
- **Works from all clients**: Slack, Discord, web UI, CLI — any way you talk to the bot

### When to Use

- Code execution (Python, Node, etc.)
- Build and test pipelines
- Any untrusted or experimental command
- When you want network isolation (`network: none`)

---

## Host Workspace

Commands run directly on the server host, scoped to a workspace directory.

### Bot YAML Configuration

```yaml
workspace:
  enabled: true
  type: host
  host:
    working_dirs:               # directories the bot can execute in
      - /home/user/projects
    commands:                   # optional command allowlist
      - name: git
        subcommands: [pull, push, commit, log, status, diff]
      - name: python
        subcommands: []         # empty = all subcommands
    blocked_patterns: []        # additional regex patterns to block
    env_passthrough:            # env vars to expose to commands
      - PATH
      - HOME
      - PYTHONPATH
  timeout: 30
  max_output_bytes: 65536

local_tools:
  - exec_command
```

### Security Controls

Host execution is protected by multiple layers:

1. **Hardcoded blocklist** (always active, cannot be overridden):
    - `rm -rf /`, `sudo`, `su`
    - `curl|bash`, `wget|bash` (piped execution)
    - `mkfs`, `dd of=/dev/` (destructive operations)
    - `curl localhost`, `wget 127.0.0.*` (SSRF prevention)
    - Fork bombs

2. **Directory allowlist**: Commands can only run in directories listed in `working_dirs`

3. **Command allowlist** (optional): If `commands` is non-empty, only listed binaries are allowed. Use `subcommands` to further restrict (e.g., allow `git pull` but not `git push`).

4. **Environment sanitization**: Only env vars listed in `env_passthrough` are visible to commands

### When to Use

- Interacting with host-level services (systemd, Docker CLI, etc.)
- Running commands that need host networking or devices
- When Docker overhead is undesirable
- **Be careful**: Host execution has a larger blast radius than Docker

---

## Host Exec (Legacy)

The original host execution mechanism — still functional but superseded by Host Workspace for new setups. Configured as a standalone block rather than through the workspace system.

### Bot YAML Configuration

```yaml
host_exec:
  enabled: true
  dry_run: false                # true = log commands without executing
  working_dirs:
    - /home/user/projects
  commands:
    - name: git
      subcommands: [pull, commit]
    - name: "*"                 # wildcard: allow all commands
      subcommands: []
  blocked_patterns:
    - "npm publish"             # custom blocklist
  env_passthrough:
    - PATH
    - HOME
  timeout: 30
  max_output_bytes: 65536

local_tools:
  - exec_command
```

Same security controls as Host Workspace (hardcoded blocklist, directory/command allowlists, env sanitization). The difference is configuration location — `host_exec` is a standalone bot config block while Host Workspace integrates with the unified workspace system (indexing, file management, etc.).

---

## Client Tools (`shell_exec`)

Commands run on the **user's local machine**, not the server. The server sends a tool request to the client, which executes it and sends back the result.

### Bot YAML Configuration

```yaml
client_tools:
  - shell_exec
```

### How It Works

1. The bot decides to run a command
2. Server sends a `tool_request` SSE event to the connected client
3. The CLI client executes `subprocess.run(command, shell=True, timeout=30)`
4. Result (stdout + stderr + exit code) is posted back to the server
5. Bot continues with the result

### Limitations

!!! warning "CLI only"
    Client tools **only work from the CLI agent client** (`client/`). They do **not** work from Slack, Discord, the web UI, or any other client. If a bot has `shell_exec` in its `client_tools` and a user talks to it from Slack, the tool simply won't be available.

- **No server-side restrictions**: Commands run with the CLI user's full permissions
- **30-second timeout**: Subprocess killed after 30s on the client side
- **120-second server timeout**: Server gives up waiting for the client after 120s
- **Requires interactive client**: The CLI must be running and connected

### When to Use

- Local development workflows (running tests on the dev machine)
- Inspecting the user's local environment
- When the bot needs to interact with the user's filesystem

---

## Deferred Execution

Both `delegate_to_exec` and pipeline `exec` steps support **deferred mode** — the command runs as a background task and results are posted back to the channel when complete.

### Bot YAML

```yaml
local_tools:
  - delegate_to_exec
```

### Usage

The bot calls `delegate_to_exec` with `mode: "deferred"`:

```json
{
  "command": "python",
  "args": ["train_model.py"],
  "mode": "deferred",
  "notify_parent": true
}
```

The command is enqueued as a Task, executed by the task worker (polls every 5s), and results dispatched to the channel. The bot doesn't block waiting — it can continue the conversation.

### Pipeline Exec Steps

Pipelines can also run commands as steps:

```yaml
steps:
  - id: check_disk
    type: exec
    command: df -h
    description: Check disk usage
```

See the [Pipelines guide](pipelines.md) for details.

---

## Docker Sandbox Profiles

An older mechanism for per-bot isolated containers with configurable scope (session, client, agent, shared). Still supported but Docker Workspace is preferred for new setups.

### Enable

Set `DOCKER_SANDBOX_ENABLED=true` in `.env`.

### Bot YAML

```yaml
docker_sandbox_profiles:
  - python-scratch

bot_sandbox:
  enabled: true
  image: python:3.12-slim
  network: none
  env:
    PYTHONUNBUFFERED: "1"
  mounts:
    - host_path: /home/user/data
      container_path: /data
      mode: ro
  user: nobody
```

Sandbox profiles are managed via the admin API (`sandbox_profiles` table) and can be shared across bots.

---

## Comparison

| Feature | Docker Workspace | Host Workspace | Host Exec | Client `shell_exec` | Docker Sandbox |
|---|---|---|---|---|---|
| **Runs on** | Server (container) | Server (host) | Server (host) | User's machine | Server (container) |
| **Works from Slack/Discord** | Yes | Yes | Yes | **No** | Yes |
| **Works from CLI** | Yes | Yes | Yes | Yes | Yes |
| **Isolation** | Container | Directory allowlist | Directory allowlist | None | Container |
| **Network control** | Yes (`none`/`bridge`) | No | No | No | Yes |
| **File indexing** | Yes | Yes | No | No | No |
| **Async/deferred** | Via `delegate_to_exec` | Via `delegate_to_exec` | No | No | No |
| **Command allowlist** | No (container is the boundary) | Yes | Yes | No | No |
| **Setup complexity** | Medium (needs Docker) | Low | Low | Low | Medium |

---

## Server-Level Configuration

These `.env` settings apply globally:

| Setting | Description | Default |
|---|---|---|
| `HOST_EXEC_BLOCKED_PATTERNS` | Additional regex patterns to block (server-wide) | `""` |
| `HOST_EXEC_WORKING_DIR_ALLOWLIST` | Comma-separated allowed directories (server-wide) | `""` |
| `HOST_EXEC_ENV_PASSTHROUGH` | Default env vars to pass through | `""` |
| `HOST_EXEC_DEFAULT_TIMEOUT` | Default command timeout (seconds) | `30` |
| `HOST_EXEC_MAX_OUTPUT_BYTES` | Default output size cap | `65536` |
| `DOCKER_SANDBOX_ENABLED` | Enable Docker sandbox system | `false` |
| `DOCKER_SANDBOX_MOUNT_ALLOWLIST` | Allowed mount source paths | `""` |
| `DOCKER_SANDBOX_MAX_CONCURRENT` | Max concurrent sandbox containers | `10` |
| `PARALLEL_TOOL_MAX_CONCURRENT` | Max parallel tool calls per request | `5` |
