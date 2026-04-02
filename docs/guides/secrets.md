# Secret Redaction & Secret Values

Spindrel includes a secret redaction system that prevents known secrets from leaking through tool results, LLM output, or conversation history. It also provides a **Secret Values vault** for storing encrypted environment variables that are injected into workspace containers but never visible to the LLM.

## How It Works

### Redaction Engine

The redaction engine collects known secret values from all configured sources and replaces them with `[REDACTED]` in:

- **Tool results** — before the LLM sees them (and before summarization)
- **LLM response text** — at all output paths (final response, forced retry, intermediate text, max-iterations)
- **Stored tool call records** — raw results in the database are redacted

This means if a bot runs `env` or `cat .env` via a tool, the output reaching the LLM and stored in history will have secret values replaced.

> **Note:** Streaming `text_delta` events are not individually redacted. Since tool results are redacted before the LLM sees them, the LLM should not reproduce secrets in its output. If you need streaming redaction, this is a trade-off to be aware of.

### Secret Sources

The registry automatically collects secrets from:

| Source | What's collected |
|--------|-----------------|
| `.env` / `app/config.py` | `API_KEY`, `ADMIN_API_KEY`, `LITELLM_API_KEY`, `ENCRYPTION_KEY`, `JWT_SECRET`, `GOOGLE_CLIENT_SECRET`, `DATABASE_URL` |
| LLM Providers | `api_key` and `management_key` from each configured provider |
| Integration Settings | Any setting marked as secret (e.g., `SLACK_BOT_TOKEN`) |
| MCP Servers | `api_key` from each configured MCP server |
| API Keys | Active scoped bot API keys from the database |
| Secret Values vault | All user-managed encrypted values (see below) |

Values shorter than 6 characters are skipped to avoid false-positive redactions on common short strings.

### Registry Rebuild

The registry rebuilds automatically:

- **At startup** — after all sources are loaded
- **When providers change** — after `load_providers()` completes
- **When integration settings change** — after `update_settings()` completes
- **When secret values are created/updated/deleted** — immediately after the DB write

## Secret Values Vault

The vault stores user-managed encrypted environment variables. These are:

- **Encrypted at rest** using Fernet symmetric encryption (same system as provider API keys)
- **Injected into workspace containers** as environment variables (available to scripts and tools)
- **Registered with the redaction engine** so their values never appear in tool results or LLM output
- **Never returned in plaintext** via the API — list/get endpoints only return metadata

### Secrets vs. Workspace Environment Variables

Both Secrets and workspace env vars (configured in **Bot > Workspace** or **Workspace > Docker** settings) are injected into containers. The difference is security:

| | **Secret Values** | **Workspace Env Vars** |
|---|---|---|
| Storage | Encrypted at rest (Fernet) | Plaintext in database |
| Redaction | Automatically redacted from tool results and LLM output | Visible to the LLM if a tool exposes them |
| API access | Value never returned in API responses | Value visible in workspace config endpoints |
| Use for | API keys, tokens, passwords, credentials | Feature flags, URLs, runtime configuration |

**Rule of thumb:** If the value would be a problem if it appeared in a conversation log, it should be a Secret.

### Use Cases

- Store API keys that bot tools need (e.g., a GitHub token for a deployment script)
- Store database credentials for workspace automation
- Store any sensitive value that tools should use but the LLM should never see in context

### Managing Secrets

**Via Admin UI:**

Navigate to **Admin > Security > Secrets** to create, edit, and delete secret values. Each secret has:

- **Name** — must be a valid environment variable name (letters, digits, underscores)
- **Value** — encrypted and stored; never displayed after creation
- **Description** — optional note about what the secret is for

**Via Admin API:**

```bash
# List secrets (values are masked)
curl -H "Authorization: Bearer $API_KEY" \
  http://localhost:8000/api/v1/admin/secret-values

# Create a secret
curl -X POST -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "GITHUB_TOKEN", "value": "ghp_abc123...", "description": "Deploy bot GitHub access"}' \
  http://localhost:8000/api/v1/admin/secret-values

# Update a secret
curl -X PUT -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"value": "ghp_new_token..."}' \
  http://localhost:8000/api/v1/admin/secret-values/{id}

# Delete a secret
curl -X DELETE -H "Authorization: Bearer $API_KEY" \
  http://localhost:8000/api/v1/admin/secret-values/{id}
```

### Container Injection

Secret values are injected as environment variables into:

- **Docker sandbox containers** — via `docker exec -e` flags
- **Shared workspace containers** — same mechanism
- **Host exec** — added to the process environment

Inside a workspace container, a bot's tool can use `$GITHUB_TOKEN` in a script without the LLM ever seeing the token value.

## User Input Secret Detection

When a user types a message in the chat UI, a pre-flight check runs before sending:

1. The message is checked against **known secrets** (exact match against the registry)
2. The message is checked against **common secret patterns** (regex heuristics for API keys, tokens, JWTs, private keys, connection strings, etc.)

If either check triggers, a warning dialog appears with three options:

- **Cancel** — discard the send, keep the draft
- **Add to Secrets** — navigate to the Secret Values admin page to store the value properly
- **Send Anyway** — proceed with sending (the user explicitly accepts the risk)

### Detected Patterns

The heuristic detector recognizes:

| Pattern | Example prefix |
|---------|---------------|
| OpenAI API key | `sk-...` |
| Anthropic API key | `sk-ant-...` |
| GitHub token | `ghp_...`, `ghs_...`, `github_pat_...` |
| Slack token | `xoxb-...`, `xoxp-...` |
| AWS access key | `AKIA...` |
| JWT | `eyJ...eyJ...` |
| Private key header | `-----BEGIN PRIVATE KEY-----` |
| Connection string | `postgres://...`, `mongodb://...` |
| Password assignment | `password = "..."`, `api_key: "..."` |

> **Note:** Pattern detection is heuristic — it may miss novel formats or flag false positives. The exact-match check against known secrets is authoritative.

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `SECRET_REDACTION_ENABLED` | `true` | Master toggle. Set to `false` to disable all redaction. |

This can be toggled via the Admin UI under **Settings > Security** or by setting `SECRET_REDACTION_ENABLED=false` in `.env`.

## Security Considerations

- **Redaction is defense-in-depth** — it protects against accidental exposure and basic prompt injection. A determined attacker with tool access could potentially exfiltrate secrets character-by-character. Use tool policies and sandbox restrictions as the primary security boundary.
- **Secrets are encrypted at rest** but decrypted into an in-memory cache for fast redaction and container injection. The server process has access to plaintext values.
- **The pre-flight check is advisory** — users can always choose "Send Anyway". It's a safety net, not a hard block.
- **Streaming text is not redacted** — since tool results are redacted before the LLM processes them, the LLM shouldn't reproduce secrets. But if a secret is injected via a different path (e.g., system prompt), streaming could expose it.
