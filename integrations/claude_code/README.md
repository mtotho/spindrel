# Claude Code Integration

Native integration with Claude Code via the `claude-agent-sdk` Python package. Replaces the harness-based approach with direct subprocess communication — no shell scripts, no Docker exec wrapping.

## Prerequisites

- Claude Code CLI installed on the host (the SDK bundles it, or install separately)
- Valid Anthropic API key configured for Claude Code (via `ANTHROPIC_API_KEY` env var or Claude Code's own auth)

## Installation

Install dependencies from the admin UI (**Integrations > Claude Code > Install Dependencies**) or manually:

```bash
pip install -r integrations/claude_code/requirements.txt
```

Restart the server after installation for tool discovery.

## Bot Configuration

Add `run_claude_code` to your bot's `local_tools` and optionally the `claude_code` skill:

```yaml
local_tools: [run_claude_code]
skills: [claude_code]  # optional, provides prompt guidance
```

### Migrating from Harness

```yaml
# Before (harness-based)
local_tools: [delegate_to_harness]
harness_access: [claude-code]

# After (native SDK)
local_tools: [run_claude_code]
skills: [claude_code]
```

The harness system is unaffected — keep it for other CLI tools (cursor, custom scripts).

## Configuration

All settings are optional with sensible defaults. Configure via environment variables or the admin UI settings panel.

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_CODE_MAX_TURNS` | `30` | Max agent turns per invocation |
| `CLAUDE_CODE_TIMEOUT` | `1800` | Timeout in seconds (30 min) |
| `CLAUDE_CODE_MAX_RESUME_RETRIES` | `1` | Resume attempts on failure |
| `CLAUDE_CODE_PERMISSION_MODE` | `bypassPermissions` | SDK permission mode |
| `CLAUDE_CODE_ALLOWED_TOOLS` | `Read,Write,Edit,Bash,Glob,Grep` | Pre-approved tools |
| `CLAUDE_CODE_MODEL` | *(empty)* | Model override (empty = SDK default) |

## How It Works

**Sync mode**: The `run_claude_code` tool calls `claude_agent_sdk.query()` directly, streams messages from the subprocess, and returns a structured JSON result with `result`, `session_id`, `cost_usd`, `num_turns`, and `duration_ms`.

**Deferred mode**: Creates a `task_type="claude_code"` task row. The task worker picks it up, runs the SDK query, dispatches the result to the output channel, and optionally creates a callback task for the parent bot.

**Resume**: Pass a `session_id` from a previous run as `resume_session_id` to continue the conversation with full context.

## Troubleshooting

- **"claude-agent-sdk is not installed"**: Use the admin UI install button or run `pip install claude-agent-sdk`
- **"Claude Code not found"**: Ensure the Claude CLI is on `PATH` or set `CLAUDE_CODE_CLI_PATH`
- **Timeout errors**: Increase `CLAUDE_CODE_TIMEOUT` for large tasks, or use deferred mode
- **Permission denied**: Check `CLAUDE_CODE_PERMISSION_MODE` — use `bypassPermissions` for fully autonomous operation
