# Shared: live Spindrel API access

Repo-dev skills under `.agents/skills/` reach the live Spindrel instance two
ways. Prefer the first when available.

## Mode 1 — In-spindrel (MCP-bridged tools)

When the agent runs inside a Project coding-run on the Spindrel server, runtime
tools are pre-injected through MCP. Use them directly; they are scoped to the
agent's authorization and won't leak past the channel binding. See
[`mcp-bridge-tools.md`](mcp-bridge-tools.md) for the catalog.

If a needed tool is unavailable, report the access gap and fall back to mode 2
with the env vars below — they are also injected into the Project run env.

## Mode 2 — Local CLI or HTTP fallback

Both modes read the same env-var pair:

| Var | Meaning |
|---|---|
| `SPINDREL_API_URL` | Base URL of the Spindrel API (e.g. `http://localhost:8000`, the leased `SPINDREL_E2E_URL`, or the operator's reachable Spindrel URL). |
| `SPINDREL_API_KEY` | Scoped API key. Never print it, write it to files, or commit it. |

For local-CLI repo-dev work against a leased ephemeral e2e stack,
`SPINDREL_API_URL` defaults to `$SPINDREL_E2E_URL` (set by
`scripts/agent_e2e_dev.py write-env`). Skills that touch e2e specifically may
keep referencing `SPINDREL_E2E_URL` directly — `SPINDREL_API_URL` is the
cross-skill default for "live API I should hit."

Read-only or read-write scope is per-skill; default to read-only and document
which scopes a write-touching skill needs.

## Examples

```bash
curl -s -H "X-API-Key: $SPINDREL_API_KEY" \
  "$SPINDREL_API_URL/api/v1/projects"
```

## Anti-patterns

- Do not invent a new env-var per skill (`SPINDREL_API`, `SPINDREL_HOST`,
  `SPINDREL_READONLY_API_KEY`, etc.). Use the canonical pair above.
- Do not assume the API is reachable from outside the operator's network.
- Do not depend on the operator's laptop, vault, or `~/.claude/` for any value.
- Do not print or persist `SPINDREL_API_KEY` in logs, files, or commits.
