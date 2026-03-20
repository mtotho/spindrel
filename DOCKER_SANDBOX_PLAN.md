# Docker Sandbox Plan (OpenClaw-style)

Long-lived Docker containers the agent can inspect, start, and `exec` into, with **PostgreSQL-backed** lifecycle management tied to the same `bot_id` / `client_id` / `session_id` scoping that Tasks, Memory, and Knowledge use.

No host shell, no bubblewrap. Docker-only, config-driven.

---

## Design Goals

1. **List** sandboxes a bot is allowed to use, with live status.
2. **Ensure**: create + start a container idempotently (never double-create).
3. **Exec**: run a shell command inside a running container, return bounded output.
4. **Stop / remove** an instance (manual or automatic on session end).
5. **Flexible sharing**: the same profile (image + config) can be used in shared, per-client, per-bot, or per-session scope — mirroring the bot_id/client_id/session_id pattern the rest of the system uses.
6. **Multiple bots** may access the same running container when authorized, or a container can be locked to one bot.

---

## Core Concepts

| Concept | Meaning |
|---------|---------|
| **Sandbox profile** | Declarative template: image, network mode, bind mounts (allowlisted), env, labels, resource limits, keep-alive entrypoint. Stored as DB rows + optional seed YAML. |
| **Sandbox instance** | A concrete container: `container_id`, `container_name`, `status`, timestamps. Scoped by `(profile_id, scope_type, scope_key)`. |
| **Bot access** | Many-to-many: which bot IDs may use which profile IDs. Optionally restricted further in bot YAML. |
| **Scope mode** | How the instance key is derived: `shared`, `client`, `agent`, or `session`. |

---

## Scope Modes

Follows the exact same scoping model used by Memory and BotKnowledge.

| Mode | `scope_type` | `scope_key` | Behavior |
|------|-------------|-------------|---------|
| `shared` | `shared` | `<profile_id>` | One container for all bots on this server sharing the profile. |
| `client` | `client` | `<client_id>` | One container per human user (client_id), shared across their sessions. |
| `agent` | `bot` | `<bot_id>` | One container per bot identity. |
| `session` | `session` | `<session_id>` | One container per chat session — most isolated; torn down on session delete. |

The mode is set on the profile and can be overridden in bot YAML. It determines which context var (from `app/agent/context.py`) is used as the scope key.

---

## Data Model (PostgreSQL)

### `sandbox_profile`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `name` | Text unique | Human slug: `build`, `homelab-tools`, `python-scratch` |
| `description` | Text | Shown in tool RAG |
| `image` | Text | e.g. `my-sandbox:bookworm` |
| `scope_mode` | Text | `shared` \| `client` \| `agent` \| `session` |
| `network_mode` | Text | `none` \| `bridge` \| named network. **Default: `none`**. Never `host` without explicit flag. |
| `read_only_root` | bool | Pair with tmpfs `/tmp` |
| `create_options` | JSONB | Allowed extra flags: `{"cpus": "1.0", "memory": "512m", "user": "1000:1000"}` |
| `mount_specs` | JSONB | List of `{host_path, container_path, mode}` — validated server-side against allowlist prefix |
| `env` | JSONB | Static env vars injected at `docker run` |
| `labels` | JSONB | Merged into `docker run --label`; include `agent-server=true` for `docker ps` filtering |
| `idle_ttl_seconds` | int nullable | Stop container after this many seconds idle. NULL = never auto-stop. |
| `created_at`, `updated_at` | TIMESTAMP | |

### `sandbox_bot_access`

Many-to-many: which bots may reference which profiles.

| Column | Type | Notes |
|--------|------|-------|
| `bot_id` | Text | Matches `bots/*.yaml` `id` |
| `profile_id` | UUID FK → `sandbox_profile` | |
| PK | `(bot_id, profile_id)` | |

### `sandbox_instance`

One row per running or stopped container, keyed by `(profile_id, scope_type, scope_key)`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `profile_id` | UUID FK → `sandbox_profile` | |
| `scope_type` | Text | `shared` \| `client` \| `bot` \| `session` |
| `scope_key` | Text | Value of the scope identifier (profile_id / client_id / bot_id / session_id as string) |
| `container_id` | Text nullable | Docker full container ID after create |
| `container_name` | Text | Deterministic: `agent-sbx-{profile}-{scope_suffix}` |
| `status` | Text | `creating` \| `running` \| `stopped` \| `dead` \| `unknown` |
| `created_by_bot` | Text | bot_id that created this instance |
| `locked_operations` | JSONB | Array of tool names the agent may NOT call on this instance. Default `[]`. Set by admin only. |
| `last_inspected_at` | TIMESTAMP | Set on status check |
| `last_used_at` | TIMESTAMP | Set on exec |
| `error_message` | Text nullable | Last create/start failure |
| `created_at` | TIMESTAMP | |

**Uniqueness constraint:** `UNIQUE (profile_id, scope_type, scope_key)` — prevents double-create races (combined with app-level optimistic locking or DB `FOR UPDATE SKIP LOCKED`).

---

## Container Naming Convention

```
agent-sbx-{profile_name}-{scope_suffix}
```

| Scope mode | `scope_suffix` |
|-----------|---------------|
| `shared` | `shared` |
| `client` | first 8 chars of `client_id` |
| `bot` | `bot_id` |
| `session` | first 12 chars of `session_id` UUID |

Example: `agent-sbx-build-shared`, `agent-sbx-python-scratch-session-4a9f1c3b2e11`

---

## Tool Surface (for the LLM)

All tools read `current_bot_id`, `current_client_id`, `current_session_id` from `app/agent/context.py` — the model never passes raw IDs.

### `list_sandbox_profiles`

Returns profiles this bot is authorized to use, with current instance status if one exists for the active scope.

```json
{
  "name": "list_sandbox_profiles",
  "description": "List Docker sandbox environments this bot can use. Returns each profile with its status (running/stopped/not_created) for the current scope.",
  "parameters": {}
}
```

Returns: `[{name, description, scope_mode, status, container_name, last_used_at}]`

---

### `ensure_sandbox`

Idempotent create + start. Resolves the scope key from context, looks up or creates the `sandbox_instance` row, runs `docker run -d` if needed (or `docker start` if stopped), updates status.

```json
{
  "name": "ensure_sandbox",
  "description": "Ensure a sandbox container is running. Creates and starts it if needed (idempotent).",
  "parameters": {
    "profile_name": {"type": "string", "description": "Sandbox profile name, e.g. 'build'"}
  }
}
```

Returns: `{container_name, status, created: bool, message}`

---

### `exec_sandbox`

Run a command inside a running container. Calls `ensure_sandbox` first if not running (auto-start). Streams output, truncated at `MAX_OUTPUT_BYTES` (default 64 KB). Timeout configurable per profile or global default.

```json
{
  "name": "exec_sandbox",
  "description": "Run a shell command inside a sandbox container. The container is started automatically if needed. Output is capped at 64 KB.",
  "parameters": {
    "profile_name": {"type": "string"},
    "command": {"type": "string", "description": "Shell command to run, e.g. 'ls -la /workspace'"},
    "timeout_seconds": {"type": "integer", "description": "Max seconds to wait. Default: 30."}
  }
}
```

Returns: `{stdout, stderr, exit_code, truncated: bool, duration_ms}`

---

### `stop_sandbox`

Stop a running container without removing it (preserves filesystem state). Useful before handing off or to save resources.

```json
{
  "name": "stop_sandbox",
  "description": "Stop a running sandbox container. The container is preserved and can be restarted.",
  "parameters": {
    "profile_name": {"type": "string"}
  }
}
```

---

### `remove_sandbox`

Stop + remove the container and delete the `sandbox_instance` row. For `session`-scoped sandboxes this is called automatically on session delete.

```json
{
  "name": "remove_sandbox",
  "description": "Stop and permanently remove a sandbox container. A new one can be created later.",
  "parameters": {
    "profile_name": {"type": "string"}
  }
}
```

---

## Instance Locking (Admin-Only)

Operators can lock specific agent-callable operations on any instance via the admin UI or API. This prevents bots from accidentally (or deliberately) stopping, removing, or re-creating containers that the operator wants to keep running.

### Lockable Operations

| Operation name | Blocks |
|---------------|--------|
| `stop` | `stop_sandbox` tool + idle prune auto-stop |
| `remove` | `remove_sandbox` tool + session-delete auto-remove |
| `ensure` | `ensure_sandbox` — prevents bots from starting/restarting this instance (useful for maintenance mode) |
| `exec` | `exec_sandbox` — prevents any command execution (full read-only quarantine) |

Any combination can be locked independently. Default: `[]` (nothing locked).

### Data Storage

`sandbox_instance.locked_operations` is a JSONB array of strings:

```json
[]                          // default — fully agent-controllable
["stop", "remove"]          // bot can exec but cannot stop or remove
["stop", "remove", "exec"]  // read-only quarantine; bot can list/status only
["ensure", "stop", "remove", "exec"]  // full operator lock; bot has zero control
```

### Enforcement in the Service Layer

Before any operation in `SandboxService`, check the instance's `locked_operations`:

```python
def _assert_not_locked(self, instance: SandboxInstance, operation: str) -> None:
    locked = instance.locked_operations or []
    if operation in locked:
        raise SandboxLockedError(
            f"Sandbox '{instance.container_name}' has '{operation}' locked by the operator."
        )
```

`SandboxLockedError` surfaces to the tool as a clear, non-retryable error string so the bot can explain the situation to the user instead of looping.

Idle prune also checks: an instance with `"stop"` in `locked_operations` is **skipped** by the prune sweep, regardless of `idle_ttl_seconds`.

Session-delete auto-remove checks: an instance with `"remove"` in `locked_operations` is **skipped** on session teardown (the container lives on).

### Admin Lock/Unlock Endpoints

```
PATCH /admin/sandbox/instances/{id}/lock
Body: {"operations": ["stop", "remove"]}   // set locked_operations (replaces)

DELETE /admin/sandbox/instances/{id}/lock  // clear all locks (set to [])
```

Admin dashboard shows a lock icon badge on each instance row when `locked_operations` is non-empty, with a tooltip listing which ops are locked. Clicking opens a modal with checkboxes for each lockable operation.

### Bot-Visible Error

When a tool hits a lock, the response is:

```json
{
  "error": "locked",
  "message": "Sandbox 'agent-sbx-build-shared' has 'stop' locked by the operator. Contact your administrator.",
  "locked_operations": ["stop", "remove"]
}
```

The bot should relay this to the user rather than retrying.

---

## Multi-Bot Access to a Shared Container

When `scope_mode = shared` or `scope_mode = client`, multiple bots can use the same running container if they each have a `sandbox_bot_access` row for the profile.

Scenario example:
- Profile `homelab-tools` with `scope_mode = client`
- Both `assistant` bot and `coder` bot have access
- The first bot to call `ensure_sandbox` creates and starts the container
- The second bot's `ensure_sandbox` finds the existing running instance and returns it
- Both bots can `exec_sandbox` concurrently — Docker handles concurrent exec fine

For exclusive access, use `scope_mode = agent` (one container per bot) or `scope_mode = session`.

---

## Bot YAML Integration

Follows the same pattern as `local_tools`, `mcp_servers`, and `pinned_tools`.

```yaml
id: coder
name: "Coder Bot"
model: claude-sonnet-4-6
docker_sandbox_profiles:
  - build
  - python-scratch
# If omitted, all profiles in sandbox_bot_access for this bot are available.
# If present, only listed profiles are accessible (subset restriction).
```

At startup, `docker_sandbox_profiles` is validated against `sandbox_bot_access` rows. Any profile listed in YAML but not in DB access table is ignored with a warning.

---

## Service Layer (`app/services/sandbox.py`)

```python
class SandboxService:
    async def list_profiles(self, bot_id: str) -> list[ProfileStatus]
    async def resolve_scope(self, profile: SandboxProfile, ctx: AgentContext) -> ScopeKey
    async def get_or_create_instance(self, profile_id, scope_type, scope_key) -> SandboxInstance
    async def ensure(self, profile_name: str, ctx: AgentContext) -> SandboxInstance
    async def exec(self, instance: SandboxInstance, command: str, timeout: int) -> ExecResult
    async def stop(self, instance: SandboxInstance) -> None
    async def remove(self, instance: SandboxInstance) -> None
    async def reconcile_status(self, instance: SandboxInstance) -> str  # docker inspect
    async def prune_idle(self) -> int  # stop instances past idle_ttl
```

Docker calls use `asyncio.create_subprocess_exec` with the Docker CLI (or `aiodocker` if preferred). Avoid shelling out user strings — all args built as Python lists.

---

## Config (`app/config.py`)

```python
DOCKER_SANDBOX_ENABLED: bool = False          # Feature flag
DOCKER_SOCKET_PATH: str = "/var/run/docker.sock"
DOCKER_SANDBOX_MAX_CONCURRENT: int = 10       # max running instances server-wide
DOCKER_SANDBOX_DEFAULT_TIMEOUT: int = 30      # exec timeout seconds
DOCKER_SANDBOX_MAX_OUTPUT_BYTES: int = 65536  # 64 KB
DOCKER_SANDBOX_MOUNT_ALLOWLIST: list[str] = []  # e.g. ["/home/user/workspace", "/data/shared"]
DOCKER_SANDBOX_IDLE_PRUNE_INTERVAL: int = 300   # seconds between prune sweeps
```

`DOCKER_SANDBOX_MOUNT_ALLOWLIST` is **mandatory** for any profile that uses bind mounts. Server validates every `host_path` in `mount_specs` against this list at profile load time and at `ensure` time.

---

## Safety (Non-Negotiable)

- **Never** interpolate LLM-controlled strings into `docker run -v`, `--network`, or any shell argument. All Docker calls use argument lists, never string interpolation.
- **Allowlist bind mounts**: every `host_path` in `mount_specs` must be a prefix of a path in `DOCKER_SANDBOX_MOUNT_ALLOWLIST`. Reject at profile creation.
- **Block dangerous mounts**: `/var/run/docker.sock`, `/etc`, `/proc`, `/sys`, `/dev` are hard-blocked regardless of allowlist.
- **Network default is `none`**: operator must explicitly set `network_mode: bridge` or a named network. `host` mode requires a break-glass env var `DOCKER_SANDBOX_ALLOW_HOST_NETWORK=true`.
- **Docker group = root on Linux**: document this prominently. Operator runs the server with awareness.
- **Resource limits**: `create_options` supports `cpus` and `memory`; recommended defaults in seed migration.
- **Max concurrent**: global cap enforced in `ensure()`; returns error if at limit.

---

## Lifecycle Events

| Event | Action |
|-------|--------|
| Session deleted | Stop + remove all `session`-scoped instances for that session_id **unless `"remove"` is in `locked_operations`** |
| Task worker prune sweep | Stop instances where `last_used_at < now() - idle_ttl_seconds` **and `"stop"` not in `locked_operations`** |
| `docker inspect` reconcile | On `ensure`, if container_id exists but `docker inspect` says it's gone, reset instance to `unknown` and recreate |
| Server startup | Optionally reconcile all instances in DB against live Docker state |

Session cleanup hooks into the session delete endpoint in `app/routers/sessions.py` (or wherever sessions are deleted).

---

## Alembic Migration Plan

**`011_sandbox_profiles`**:
```sql
CREATE TABLE sandbox_profile (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT UNIQUE NOT NULL,
  description TEXT,
  image TEXT NOT NULL,
  scope_mode TEXT NOT NULL DEFAULT 'session',
  network_mode TEXT NOT NULL DEFAULT 'none',
  read_only_root BOOLEAN NOT NULL DEFAULT FALSE,
  create_options JSONB NOT NULL DEFAULT '{}',
  mount_specs JSONB NOT NULL DEFAULT '[]',
  env JSONB NOT NULL DEFAULT '{}',
  labels JSONB NOT NULL DEFAULT '{}',
  idle_ttl_seconds INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sandbox_bot_access (
  bot_id TEXT NOT NULL,
  profile_id UUID NOT NULL REFERENCES sandbox_profile(id) ON DELETE CASCADE,
  PRIMARY KEY (bot_id, profile_id)
);

CREATE TABLE sandbox_instance (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id UUID NOT NULL REFERENCES sandbox_profile(id) ON DELETE CASCADE,
  scope_type TEXT NOT NULL,
  scope_key TEXT NOT NULL,
  container_id TEXT,
  container_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'unknown',
  created_by_bot TEXT NOT NULL,
  locked_operations JSONB NOT NULL DEFAULT '[]',
  last_inspected_at TIMESTAMPTZ,
  last_used_at TIMESTAMPTZ,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (profile_id, scope_type, scope_key)
);

CREATE INDEX idx_sandbox_instance_status ON sandbox_instance(status);
CREATE INDEX idx_sandbox_instance_last_used ON sandbox_instance(last_used_at);
```

Seed migration inserts one example profile (`python-scratch`, `scope_mode=session`, `network_mode=none`, image=`python:3.12-slim`) for testing.

---

## Admin API (`app/routers/admin_sandbox.py`)

Follows the pattern of `app/routers/admin_tasks.py`.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/sandbox/profiles` | GET | List all profiles |
| `/admin/sandbox/profiles` | POST | Create profile |
| `/admin/sandbox/profiles/{id}` | PUT | Update profile |
| `/admin/sandbox/profiles/{id}` | DELETE | Delete profile (fails if active instances) |
| `/admin/sandbox/access` | POST | Grant bot access to profile |
| `/admin/sandbox/access/{bot_id}/{profile_id}` | DELETE | Revoke access |
| `/admin/sandbox/instances` | GET | List all instances with live status |
| `/admin/sandbox/instances/{id}/stop` | POST | Stop instance (bypasses lock — admin override) |
| `/admin/sandbox/instances/{id}/remove` | POST | Stop + remove instance (bypasses lock — admin override) |
| `/admin/sandbox/instances/{id}/lock` | PATCH | Set locked_operations on an instance |
| `/admin/sandbox/instances/{id}/lock` | DELETE | Clear all locks on an instance |
| `/admin/sandbox/prune` | POST | Manually trigger idle prune |

---

## Implementation Phases

### Phase A — MVP

1. Alembic migration `011_sandbox_profiles` with seed data.
2. `app/services/sandbox.py`: `ensure()` and `exec()` using subprocess Docker CLI.
3. Bot YAML field `docker_sandbox_profiles`.
4. Three tools: `list_sandbox_profiles`, `ensure_sandbox`, `exec_sandbox`.
5. `session` scope only (simplest; no sharing complexity yet).
6. Mount allowlist validation (safety, non-negotiable from day 1).

### Phase B — Full Scope Modes + Sharing

7. Add `shared`, `client`, `agent` scope modes.
8. Multi-bot shared container (resolve existing instance in `get_or_create_instance`).
9. `stop_sandbox` and `remove_sandbox` tools.
10. Concurrency: DB `SELECT ... FOR UPDATE SKIP LOCKED` to prevent double-create races.
11. `reconcile_status()`: `docker inspect` cross-check on every `ensure`.

### Phase C — Lifecycle + Admin

12. Idle prune job wired into task worker loop (like the 5-second task poll).
13. Session delete hook → remove session-scoped instances (respects `locked_operations`).
14. Admin API (`app/routers/admin_sandbox.py`), including `PATCH/DELETE /lock` endpoints.
15. Admin dashboard panel (Jinja2 + HTMX, following existing admin pages) with per-instance lock checkboxes.
16. `SandboxLockedError` surfaced to tools as non-retryable error; admin stop/remove bypasses locks.

### Phase D — Hardening

16. Resource limits enforced in `create_options` by default in seed migration.
17. Audit log: `sandbox_exec_log` table (profile, instance, bot_id, client_id, session_id, command_hash, exit_code, duration_ms) — no raw commands stored.
18. Optional: `docker stats` feed into instance metadata for resource visibility.

---

## Out of Scope (Initially)

- SSH / OpenShell backends.
- Sandboxed browser / CDP.
- Running the FastAPI app itself inside Docker (orthogonal).
- Per-command `seccomp` or AppArmor profiles (operator's responsibility at image build time).

---

## File Layout

```
app/
  services/
    sandbox.py          # SandboxService (ensure, exec, stop, remove, reconcile, prune)
  routers/
    admin_sandbox.py    # Admin CRUD endpoints
  tools/
    local/
      sandbox.py        # list_sandbox_profiles, ensure_sandbox, exec_sandbox, stop_sandbox, remove_sandbox
migrations/
  versions/
    011_sandbox_profiles.py
bots/
  *.yaml                # docker_sandbox_profiles: [...]
```

---

## References

- [OpenClaw — Sandboxing](https://docs.openclaw.ai/gateway/sandboxing) (scope: session / agent / shared; Docker default; network defaults)
- [OpenClaw — Sandbox CLI](https://docs.openclaw.ai/sandbox) (lifecycle mental model)
- Existing patterns: `app/agent/tasks.py` (bot_id/client_id/session_id scoping), `app/agent/context.py` (ContextVars), `app/db/models.py` (ORM conventions)
