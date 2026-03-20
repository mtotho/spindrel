# Docker sandbox plan (OpenClaw-style)

Design for **named, long-lived Docker containers** the agent can **inspect, start, and `exec` into**, with **database-backed** mapping to `bot_id` / `session_id` and **flexible sharing** so multiple bots or sessions can use the **same** container definition or runtime.

The removed `run_server_command` experiment is **not** continued here: no host shell, no bubblewrap. This is **Docker-only**, config-driven.

---

## Why this instead of the old tool

OpenClaw keeps **one sandbox runtime per scope** (e.g. per [session](https://docs.openclaw.ai/gateway/sandboxing)) and runs repeated **`exec`** inside it — state (cwd, files, processes) can persist across turns. A fresh `docker run --rm` per message does **not** match that model.

This plan targets that behavior **on purpose**: **ensure container → exec**, with optional **idle prune** and **recreate**.

---

## Goals

1. **List** sandboxes the current bot is allowed to see (by config + DB state).
2. **Status**: running / stopped / missing; map to Docker container ID (or name).
3. **Ensure**: create + start if missing or stopped (idempotent).
4. **Exec**: run a shell command **inside** the container (`docker exec`), stream or return bounded output.
5. **Correlate** Docker container ↔ logical sandbox ↔ optional `session_id` in PostgreSQL.
6. **Flexible assignment**: same **sandbox profile** (image, mounts, network) shared by **many bots**; same **running instance** shared by **many sessions** when desired, or **one instance per session** when desired.

---

## Concepts

| Concept | Meaning |
|--------|---------|
| **Sandbox profile** | Declarative template: image, `docker network`, bind mounts (validated allowlist), env, labels, entrypoint keep-alive (`sleep infinity`), read-only root policy, etc. Stored in DB or YAML + DB row ID. |
| **Sandbox instance** | A concrete container: `container_id` (or name), `profile_id`, optional `session_id`, `state`, `last_used_at`. Multiple instances can share one profile (e.g. per-session). |
| **Binding** | Which **bots** may use which **profiles** (many-to-many). Optional overrides per bot YAML (`docker_sandboxes: [build, scratch]`). |

---

## Data model (PostgreSQL)

### `sandbox_profile`

| Column | Notes |
|--------|--------|
| `id` | UUID PK |
| `name` | Unique human slug: `build`, `homelab-tools` |
| `description` | For tool RAG / operator docs |
| `image` | e.g. `my-sandbox:bookworm` |
| `network_mode` | `none` \| `bridge` \| custom (never `host` / `container:` without explicit break-glass flag) |
| `read_only_root` | bool; pair with tmpfs `/tmp` |
| `create_options` | JSONB: extra `docker run` flags you allow (cpus, memory, user) |
| `mount_specs` | JSONB: list of `{host_path, container_path, mode}` — **server-side validated** against an allowlist prefix (never raw user strings into `-v`) |
| `labels` | JSONB merged into `docker run --label` for `docker ps` filtering |
| `created_at`, `updated_at` | |

### `sandbox_bot_access`

Many-to-many: which bots may reference which profiles.

| Column | Notes |
|--------|--------|
| `bot_id` | text, matches `bots/*.yaml` `id` |
| `profile_id` | FK → `sandbox_profile` |
| PK | `(bot_id, profile_id)` |

### `sandbox_instance`

| Column | Notes |
|--------|--------|
| `id` | UUID PK |
| `profile_id` | FK |
| `session_id` | UUID nullable — **null** = shared pool for that profile; **set** = dedicated per session |
| `container_id` | Docker short/long id after create |
| `container_name` | deterministic: `agent-sbx-{profile}-{session_suffix}` |
| `status` | enum: `creating`, `running`, `stopped`, `dead`, `unknown` |
| `last_inspected_at`, `last_used_at` | for prune + UI |
| `error_message` | last create/start failure |

**Uniqueness:** partial unique index on `(profile_id, session_id)` where `session_id IS NOT NULL`; for shared pool (`session_id` null), **at most one** active row per `profile_id` (enforce in app or unique constraint with sentinel).

---

## Session modes (per profile)

Configurable on **profile** or **bot override**:

| Mode | Behavior |
|------|----------|
| `shared` | One running container per profile for the whole server (or per bot); `session_id` null in instance row. |
| `session` | One container per chat `session_id` (OpenClaw default scope). |
| `agent` | One container per `bot_id` (optional; instance key = profile + bot). |

Implementation detail: **composite key** `(profile_id, scope_type, scope_key)` instead of nullable `session_id` only — cleaner long-term.

---

## Tool surface (for the LLM)

Minimal set:

1. **`list_docker_sandboxes`** — Profiles the **current bot** can access; merge DB + live `docker inspect` status when possible.
2. **`ensure_docker_sandbox`** — `profile_name` → create/start if needed; update `sandbox_instance`.
3. **`exec_docker_sandbox`** — `profile_name` [, `session_id` implicit from context] + `command` → `docker exec`; timeout + max output bytes.
4. (Optional) **`remove_docker_sandbox`** — stop + rm instance row (admin); or hook on **session delete** to tear down `session`-scoped instances.

**Context:** use existing `current_session_id` / `current_bot_id` from `app/agent/context.py` so the model does not pass raw UUIDs unless you want an override.

---

## Config layers

1. **Global** `.env`: Docker socket path, max concurrent sandboxes, default timeouts, **host path allowlist** for bind mounts.
2. **`sandbox_profile` rows** (or seed migration): definitions.
3. **`sandbox_bot_access`** rows: which bot uses which profile.
4. **Bot YAML** (optional): `docker_sandbox_profiles: [build, scratch]` to restrict subset; if omitted, use all rows in `sandbox_bot_access` for that bot.

---

## Safety (non-negotiable)

- **Never** pass LLM-controlled strings directly into `docker run -v` or `--network` without validation.
- **Block** mounting `docker.sock`, `/etc`, `/proc`, `/sys` unless explicit operator config (OpenClaw documents similar rules).
- **Default `network_mode: none`** for untrusted workloads.
- Document: **docker group ≈ root** on typical Linux.

---

## Implementation phases

### Phase A — MVP (~2–4 days focused)

- Tables + Alembic migration; seed one profile + bot access.
- Service module: `ensure` = `docker run -d` with keep-alive, `exec` = `docker exec`.
- Three tools; wire to `current_bot_id` / `current_session_id`.
- Session-scoped **or** shared-only (pick one mode first to cut scope).

### Phase B — Hardening

- Idle TTL prune job; **session delete** → stop/remove session instances.
- `docker inspect` reconciliation if container died externally.
- Per-profile locks to avoid double-create races.

### Phase C — Operator UX

- Admin API or CLI: `list`, `recreate`, explain effective config (OpenClaw’s `sandbox explain` analog).
- Metrics / logging.

---

## Out of scope (initially)

- OpenShell / SSH backends (OpenClaw has these; duplicate only if needed).
- Sandboxed browser / CDP (large separate surface).
- Running the **FastAPI app itself** inside Docker for this feature (orthogonal).

---

## References

- [OpenClaw — Sandboxing](https://docs.openclaw.ai/gateway/sandboxing) (scope: session / agent / shared; Docker default; network defaults)
- [OpenClaw — Sandbox CLI](https://docs.openclaw.ai/sandbox) (lifecycle mental model)

---

## Summary

**Yes, it’s “a few configs + decent tools + DB”** — roughly **Phase A** above. The flexible **bot ↔ profile ↔ instance** layout is the part that takes design care; the Docker calls themselves are straightforward. The old server shell was the wrong abstraction; this doc is the intended replacement direction.
