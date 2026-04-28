# Command Execution

![Chat command execution — Orion runs a Python snippet via `exec_command` and the assistant turn shows the EXEC COMMAND tool badge plus the raw stdout in a fenced code block](../images/chat-command-execution.png)

Spindrel bots can execute shell commands in several ways, each with different trust boundaries. This guide describes the current execution model: server-side subprocess tools are the default, Docker sandboxes are optional isolation, local machine control is lease-based, and the older CLI client tools remain legacy.

## Quick Decision Guide

| I want to... | Use | Works from |
|---|---|---|
| Run normal workspace commands on the server | [Server subprocess execution](#server-subprocess-execution) | All clients |
| Run code in an isolated container | [Docker sandboxes](#docker-sandboxes) | All clients |
| Run commands on a paired local machine | [Local machine control](#local-machine-control) | Web UI sessions with a machine lease |
| Run commands from the legacy CLI client | [Client Tools](#client-tools-shell_exec) | CLI only |
| Run commands asynchronously (fire-and-forget) | [Deferred Execution](#deferred-execution) | All clients |

!!! tip "Recommended default"
    Start with server subprocess execution for trusted personal workspaces. Use Docker sandboxes or local machine leases when you need a different isolation or locality boundary.

---

## Where Commands Run

Understanding **where** a command executes is the most important distinction:

```
┌─────────────────────────────────────────────────────────┐
│  Server Host                                            │
│  ┌──────────────────────┐  ┌─────────────────────────┐  │
│  │  Docker Sandbox      │  │  Server subprocess      │  │
│  │  (optional container)│  │  (native process)       │  │
│  │  Isolated filesystem │  │  Shared workspace path  │  │
│  │  Optional network    │  │  Server permissions     │  │
│  └──────────────────────┘  └─────────────────────────┘  │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  User's Machine                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Local machine control lease                     │   │
│  │  Paired provider transport, session scoped       │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

**Key point:** server subprocess tools and Docker sandboxes run where the Spindrel server runs. Local machine control runs on a paired target machine only after a session is granted a lease. Legacy client tools (`shell_exec`) run only through the old CLI client path.

---

## Server subprocess execution

The normal `exec_tool` path runs a subprocess from the Spindrel server process against the configured workspace path. In Docker deployments, that means the command runs inside the Spindrel container against the mounted workspace directory. In local-dev deployments, it runs on the host process.

Use this for trusted personal project work, repo inspection, tests, and command output you want in the chat transcript. It is available from every client because execution happens server-side.

Security posture:

- Treat it as trusted-operator remote command execution.
- Use scoped tool policies and approvals for risky bots.
- Keep Spindrel on a private/LAN/VPN surface unless you have added your own hardening.
- Use Docker sandboxes or local machine leases when the command should not run in the server process environment.

## Docker sandboxes

Docker sandboxes are optional long-lived containers for more isolated code execution. They are configured from the Admin UI and use the host Docker daemon when Spindrel itself runs in Docker.

Use them when you need a pinned image, a constrained filesystem, network isolation, or resource limits. They are not the default workspace model anymore.

## Local machine control

Local machine control pairs a target machine with Spindrel and grants a specific chat session a lease to that target. After a lease is granted, tools such as `machine_status`, `machine_inspect_command`, and `machine_exec_command` run through the provider transport on that target.

Use this when the command needs your actual laptop or workstation: local credentials, GUI-adjacent files, hardware access, or an existing dev checkout that is not mounted into the server.

See [Local Machine Control](local-machine-control.md) for enrollment, leases, and the provider security model.

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

Docker sandbox profiles provide per-bot isolated containers with configurable scope (session, client, agent, shared). Use them when the server subprocess environment is too broad for the work or when you need a pinned image/resource boundary.

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

| Feature | Server subprocess | Local machine lease | Client `shell_exec` | Docker Sandbox |
|---|---|---|---|---|
| **Runs on** | Spindrel server process/container | Paired target machine | User's CLI machine | Server-side container |
| **Works from Slack/Discord** | Yes | Only if a session lease exists | **No** | Yes |
| **Works from web UI** | Yes | Yes, with session lease | **No** | Yes |
| **Isolation** | Server process permissions | Provider/session lease boundary | None beyond CLI user | Container |
| **Network control** | No dedicated network sandbox | Target machine's network | CLI machine's network | Yes |
| **File indexing** | Yes, via workspace files | Target-specific | No | Depends on mounted paths |
| **Async/deferred** | Via `delegate_to_exec` / pipeline exec | Tool-specific | No | Tool-specific |
| **Setup complexity** | Low | Medium | Low but legacy | Medium |

---

## Server-Level Configuration

These `.env` settings apply globally:

| Setting | Description | Default |
|---|---|---|
| `DOCKER_SANDBOX_ENABLED` | Enable Docker sandbox system | `false` |
| `DOCKER_SANDBOX_MOUNT_ALLOWLIST` | Allowed mount source paths | `""` |
| `DOCKER_SANDBOX_MAX_CONCURRENT` | Max concurrent sandbox containers | `10` |
| `PARALLEL_TOOL_MAX_CONCURRENT` | Max parallel tool calls per request | `10` |
