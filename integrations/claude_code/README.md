# Claude Code Integration

Runs the `claude` CLI inside the bot's Docker workspace container. The agent gets a clean `run_claude_code` tool interface while execution happens in the container environment with the project's toolchain.

## Prerequisites

- Bot configured with `workspace.type: docker` and a Docker image that has the `claude` CLI installed
- Valid Anthropic API key available inside the container (via `ANTHROPIC_API_KEY` in workspace docker env, or container-level config)

## Bot Configuration

Add `run_claude_code` to your bot's `local_tools` and optionally the `claude_code` skill:

```yaml
local_tools: [run_claude_code]
skills: [claude_code]  # optional, provides prompt guidance

workspace:
  enabled: true
  type: docker
  docker:
    image: my-workspace-image  # must have `claude` CLI installed
    env:
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
```

### Migrating from Harness

```yaml
# Before (harness-based)
local_tools: [delegate_to_harness]
harness_access: [claude-code]

# After (Docker workspace)
local_tools: [run_claude_code]
skills: [claude_code]
```

### Migrating from SDK

```yaml
# Before (SDK-based, ran on host)
local_tools: [run_claude_code]
# Required: pip install claude-agent-sdk on host

# After (Docker workspace, runs in container)
local_tools: [run_claude_code]
# Required: claude CLI in workspace Docker image
```

No host-side Python dependencies needed — the `claude` CLI runs inside Docker.

## Configuration

All settings are optional with sensible defaults. Configure via environment variables or the admin UI settings panel.

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_CODE_MAX_TURNS` | `30` | Max agent turns per invocation |
| `CLAUDE_CODE_TIMEOUT` | `1800` | Timeout in seconds (30 min) |
| `CLAUDE_CODE_MAX_RESUME_RETRIES` | `1` | Resume attempts on failure |
| `CLAUDE_CODE_PERMISSION_MODE` | `bypassPermissions` | CLI permission mode |
| `CLAUDE_CODE_ALLOWED_TOOLS` | `Read,Write,Edit,Bash,Glob,Grep` | Pre-approved tools |
| `CLAUDE_CODE_MODEL` | *(empty)* | Model override (empty = CLI default) |

## How It Works

**Sync mode**: The `run_claude_code` tool builds CLI arguments, executes the `claude` command inside the bot's Docker workspace container via `exec_bot_local()`, and parses the JSON output into a structured result with `result`, `session_id`, `cost_usd`, `num_turns`, and `duration_ms`.

**Deferred mode**: Creates a `task_type="claude_code"` task row. The task worker picks it up, runs the CLI in Docker, dispatches the result to the output channel, and optionally creates a callback task for the parent bot.

**Resume**: Pass a `session_id` from a previous run as `resume_session_id` to continue the conversation with full context.

## Troubleshooting

- **"No workspace enabled"**: Bot needs `workspace.enabled: true` with `workspace.type: docker`
- **"No Docker workspace configured"**: Set `workspace.docker.image` to an image with `claude` CLI
- **"claude: command not found"**: The workspace Docker image must have the `claude` CLI installed and on PATH
- **Timeout errors**: Increase `CLAUDE_CODE_TIMEOUT` for large tasks, or use deferred mode
- **Permission denied**: Check `CLAUDE_CODE_PERMISSION_MODE` — use `bypassPermissions` for fully autonomous operation
