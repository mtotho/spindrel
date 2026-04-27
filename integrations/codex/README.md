# Codex harness integration

Drives the OpenAI Codex CLI's `app-server` JSON-RPC protocol over stdio. No
third-party Python SDK is used — the `codex` binary is the deployment
prerequisite, and this integration spawns it as a subprocess.

## Prerequisites

1. **Enable the integration** on `/admin/integrations`. Spindrel
   auto-installs `@openai/codex` from npm (declared in
   `integration.yaml`'s `dependencies.npm`) into
   `~/.local/bin/codex`. Set `CODEX_BIN=/path/to/codex` only if the
   binary lives somewhere else.
2. **Authenticate** by running `codex login` once inside the Spindrel
   container. From the Spindrel host:

   ```sh
   docker exec -it spindrel codex login
   ```

   The binary persists credentials at the standard path it controls
   (typically under `$HOME` for the spindrel user).

`auth_status()` distinguishes the two failure modes — "binary not
installed" vs "not logged in" — so the admin UI surfaces a useful error
even before login is attempted.

## Approval mapping

| Spindrel mode       | Codex `approvalPolicy`           | Sandbox profile           | Notes |
|---------------------|----------------------------------|---------------------------|-------|
| `bypassPermissions` | most-permissive                  | most-permissive write     | Server should not issue approval requests; if it does, allow. |
| `acceptEdits`       | on-request                       | workspace-write           | Edits proceed natively; risky commands surface server approval requests through Spindrel cards. |
| `default`           | on-request                       | workspace-write           | All server-initiated approvals routed through Spindrel. |
| `plan`              | most-restrictive                 | read-only                 | Plus a leading host instruction. Plan state from `turn/plan/updated`. |

Exact `approvalPolicy` and sandbox profile values are pulled from the
installed binary's schema via `schema.py` constants.

## Spindrel tool bridge

When the codex binary's app-server reports `dynamicTools` capability,
Spindrel's effective tool set for the current bot+channel is exposed as
Codex `dynamicTools`. Calls flow back through Spindrel's
`execute_harness_spindrel_tool` (which runs Spindrel policy + approval +
audit). When the binary does not support `dynamicTools`, the bridge
status records `"unsupported"` and the harness still runs with native
Codex tools.
