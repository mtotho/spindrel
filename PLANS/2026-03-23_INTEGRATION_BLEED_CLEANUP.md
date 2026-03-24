# Integration Code Bleed Cleanup

**Created:** 2026-03-23
**Status:** Draft
**Goal:** Remove all Slack-specific code from `/app` (core) so that adding Discord/Telegram/etc requires zero changes to core.

---

## Current State

The dispatcher registry, Channel model, and `integrations/` folder are already well-designed for multi-integration support. However, Slack-specific code has leaked into the core app in several places — hardcoded API calls, config keys, tool descriptions, and template rendering that assumes "integration = Slack".

## Inventory of Slack Bleed

### P0 — Functional Code in Core That Must Move

| # | File | Lines | What | Severity |
|---|------|-------|------|----------|
| 1 | `app/routers/admin_channels.py` | 1100-1134 | `/api/slack/config` endpoint — reads Channel table, returns Slack-specific config | **High** |
| 2 | `app/routers/admin_channels.py` | 68-90 | `_fetch_slack_channel_names()` — direct `https://slack.com/api/conversations.info` calls | **High** |
| 3 | `app/routers/admin_channels.py` | 105-111, 147-151, 250-255 | Slack channel name resolution calls in 3 route handlers | **High** |
| 4 | `app/config.py` | 159-161 | `SLACK_DEFAULT_BOT`, `SLACK_BOT_TOKEN` settings | **High** |
| 5 | `app/main.py` | 156, 164 | `api_router as _slack_api_router` import + `/api` mount | **High** |
| 6 | `app/tools/local/tasks.py` | 140-141 | `if dispatch_type == "slack":` hardcoded check to set `reply_in_thread` | **Medium** |

### P1 — Tool Descriptions Mentioning "Slack"

| # | File | Lines | What |
|---|------|-------|------|
| 7 | `app/tools/local/delegation.py` | 67-68, 250-251 | "Post as Slack thread reply" / "No effect outside Slack" |
| 8 | `app/tools/local/tasks.py` | 87-89, 358-359 | "Slack only. When false..." |
| 9 | `app/tools/local/exec_tool.py` | 110 | "Post result as a Slack thread reply" |
| 10 | `app/tools/local/knowledge.py` | ~234 | "always for this Slack channel/client" |

### P2 — Templates with Hardcoded Slack UI

| # | File | Lines | What |
|---|------|-------|------|
| 11 | `app/templates/admin/bot_edit.html` | 870-884 | Hardcoded "Slack" section with `icon_emoji` field |
| 12 | `app/templates/admin/channel_detail.html` | 2-19 | `slack_name` variable, purple badge for Slack |
| 13 | `app/templates/admin/channel_row.html` | 4-27 | Slack channel name resolution, purple badge |
| 14 | `app/templates/admin/task_detail.html` | 105-137 | "Reply in thread" checkbox only shown for `dispatch_type == "slack"` |
| 15 | `app/templates/admin/tasks.html` | 26-31, 85-86 | Hardcoded "slack" in dispatch type filter and badge |
| 16 | `app/templates/admin/knowledge_*.html` | various | `slack:C123456` placeholder examples |

### P3 — Stale / Cleanup

| # | File | Lines | What |
|---|------|-------|------|
| 17 | `app/db/models.py` | 595-608 | `IntegrationChannelConfig` model — deprecated, not used anywhere |
| 18 | Various | — | Comments mentioning Slack (cosmetic) |

---

## Plan

### Step 1: Integration Hooks — Name Resolution

**Problem:** `_fetch_slack_channel_names()` in `admin_channels.py` makes direct Slack API calls. When Discord is added, we'd need `_fetch_discord_channel_names()` too — all in core.

**Fix:** Add a `resolve_names` hook to the integration framework.

**`integrations/__init__.py`** — add a registry:
```python
# Name resolver registry: {integration_id: async (list[str]) -> dict[str, str]}
_name_resolvers: dict[str, Callable] = {}

def register_name_resolver(integration_id: str, resolver: Callable) -> None:
    _name_resolvers[integration_id] = resolver

async def resolve_integration_names(integration_id: str, ids: list[str]) -> dict[str, str]:
    resolver = _name_resolvers.get(integration_id)
    if not resolver:
        return {}
    return await resolver(ids)
```

**`integrations/slack/dispatcher.py`** (or new `integrations/slack/hooks.py`) — register:
```python
from integrations import register_name_resolver

async def resolve_slack_names(channel_ids: list[str]) -> dict[str, str]:
    """Call Slack conversations.info for each channel."""
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        return {}
    # ... (move _fetch_slack_channel_names logic here)

register_name_resolver("slack", resolve_slack_names)
```

**`app/routers/admin_channels.py`** — replace:
```python
# Before:
slack_names = await _fetch_slack_channel_names(slack_ids)

# After:
from integrations import resolve_integration_names
integration_names = {}
for integration_id, ids in grouped_by_integration.items():
    integration_names[integration_id] = await resolve_integration_names(integration_id, ids)
```

Delete `_fetch_slack_channel_names()` and remove `SLACK_BOT_TOKEN` from `app/config.py`.

### Step 2: Move `/api/slack/config` to Integration Router

**Problem:** `/api/slack/config` lives in core (`admin_channels.py`). It's consumed by `integrations/slack/slack_settings.py`.

**Fix:** Move it to `integrations/slack/router.py` (create this file — Slack currently has no router).

**`integrations/slack/router.py`** (new):
```python
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import Bot as BotRow, Channel

router = APIRouter()

@router.get("/config")
async def integration_config(request: Request):
    """Returns channel->bot mapping for this integration."""
    # API key auth...
    async with async_session() as db:
        channels = (await db.execute(
            select(Channel).where(Channel.integration == "slack")
        )).scalars().all()
        bots = (await db.execute(select(BotRow))).scalars().all()
    # ... same logic, returns JSONResponse
```

This gets auto-discovered and mounted at `/integrations/slack/config`.

**`integrations/slack/slack_settings.py`** — update URL:
```python
# Before: /api/slack/config
# After: /integrations/slack/config
```

**`app/routers/admin_channels.py`** — delete the `api_router` and the `/api/slack/config` endpoint entirely.

**`app/main.py`** — delete:
```python
from app.routers.admin_channels import api_router as _slack_api_router
app.include_router(_slack_api_router, prefix="/api")
```

Also move `SLACK_DEFAULT_BOT` out of `app/config.py`. Options:
- The Slack integration reads it from its own env var or config directly
- Or: add a generic `INTEGRATION_DEFAULT_BOT` setting (probably overkill — just let the integration own it)

### Step 3: Generic Integration Config on Bots

**Problem:** `bot_edit.html` has a hardcoded "Slack" section for `icon_emoji`. This should render dynamically per-integration.

**Fix — Option A (minimal):** The `integration_config` JSONB is already generic (`{"slack": {"icon_emoji": "..."}, "discord": {...}}`). The template just needs to not hardcode "Slack":

```html
<!-- Integration Display Config -->
{% for integration_id, fields in integration_fields.items() %}
<div class="mt-4 pt-3 border-t border-gray-700/60">
  <div class="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">{{ integration_id | title }}</div>
  {% for field in fields %}
    <label>{{ field.label }}</label>
    <input :value="ic.{{ integration_id }}?.{{ field.key }}" ... />
  {% endfor %}
</div>
{% endfor %}
```

**Fix — Option B (integration-driven):** Each integration provides a template partial. The bot_edit template includes them dynamically. This is cleaner but more work.

**Recommendation:** Option A for now. The field definitions can come from a simple dict in `integrations/__init__.py`:
```python
_integration_bot_fields: dict[str, list[dict]] = {}

def register_bot_fields(integration_id: str, fields: list[dict]) -> None:
    _integration_bot_fields[integration_id] = fields

def get_integration_bot_fields() -> dict[str, list[dict]]:
    return dict(_integration_bot_fields)
```

Slack registers: `register_bot_fields("slack", [{"key": "icon_emoji", "label": "Icon Emoji", "placeholder": ":robot_face:", "help": "Overrides avatar. Requires chat:write.customize."}])`

### Step 4: Generalize Tool Descriptions

**Problem:** Tool schemas say "Slack only" and "Post as Slack thread reply".

**Fix:** Replace Slack-specific language with generic integration language:

| Before | After |
|--------|-------|
| "Post the child's result as a Slack thread reply (true) or new channel-level message (false, default). No effect outside Slack." | "Post the result as a thread reply (true) or new channel-level message (false, default). Only applies to integrations that support threading." |
| "Slack only. When false (default), the result is posted as a new top-level message..." | "When false (default), the result is posted as a new top-level message in the channel. When true, posted as a thread reply. Only applies to integrations that support threading." |

Also in `tasks.py` line 140:
```python
# Before:
if dispatch_type == "slack":
    dispatch_config["reply_in_thread"] = reply_in_thread

# After:
if dispatch_type not in ("none", "internal", "webhook"):
    dispatch_config["reply_in_thread"] = reply_in_thread
```

Or better — make it unconditional. Dispatchers that don't support threading can ignore the field.

### Step 5: Generalize Templates

**Channel display (`channel_detail.html`, `channel_row.html`):**
- Replace `slack_names` with generic `integration_names` dict
- Replace `channel.integration == "slack"` purple badge with dynamic color mapping
- Integration colors can come from a dict in the template or from integration registration

**Task templates (`task_detail.html`, `tasks.html`):**
- The dispatch type filter already lists all types — just make the badges generic (no special "slack" case)
- "Reply in thread" checkbox: show for any integration that supports threading (not just `dispatch_type == "slack"`)

**Knowledge templates:**
- Replace `slack:C123456` placeholders with `integration:ID` or just remove Slack-specific examples

### Step 6: Drop `IntegrationChannelConfig`

Migration to drop the `integration_channel_configs` table. It's unused — the `Channel` table replaced it.

### Step 7: Remove `SLACK_*` from `app/config.py`

After Steps 1-2, `SLACK_BOT_TOKEN` and `SLACK_DEFAULT_BOT` are no longer needed in core config. The Slack integration reads them from env directly (like it already does for `SLACK_BOT_TOKEN` in `integrations/slack/slack_settings.py` and `SLACK_APP_TOKEN` in `integrations/slack/slack_bot.py`).

---

## Execution Order

1. **Step 1** (name resolution hooks) — unblocks Step 5
2. **Step 2** (move `/api/slack/config`) — unblocks Step 7
3. **Step 3** (bot integration config) — independent
4. **Step 4** (tool descriptions) — independent, quick
5. **Step 5** (templates) — depends on Step 1
6. **Step 6** (drop legacy table) — independent, migration only
7. **Step 7** (remove SLACK_* config) — depends on Steps 1+2

Steps 1+2 are the critical path. Steps 3, 4, 6 can be done in parallel.

## Files Changed Summary

| File | Action |
|------|--------|
| `integrations/__init__.py` | Add name resolver + bot fields registries |
| `integrations/slack/hooks.py` | **New** — register name resolver + bot fields |
| `integrations/slack/router.py` | **New** — `/config` endpoint moved from core |
| `integrations/slack/slack_settings.py` | Update config URL |
| `app/routers/admin_channels.py` | Delete `_fetch_slack_channel_names`, `api_router`, `/api/slack/config`; use generic name resolution |
| `app/main.py` | Remove `_slack_api_router` import and mount |
| `app/config.py` | Remove `SLACK_DEFAULT_BOT`, `SLACK_BOT_TOKEN` |
| `app/tools/local/delegation.py` | Generalize "Slack" in descriptions |
| `app/tools/local/tasks.py` | Generalize descriptions + `dispatch_type == "slack"` check |
| `app/tools/local/exec_tool.py` | Generalize "Slack" in description |
| `app/tools/local/knowledge.py` | Generalize "Slack" in description |
| `app/templates/admin/bot_edit.html` | Dynamic integration config section |
| `app/templates/admin/channel_detail.html` | Generic integration name display |
| `app/templates/admin/channel_row.html` | Generic integration name display |
| `app/templates/admin/task_detail.html` | Generic threading checkbox |
| `app/templates/admin/tasks.html` | Generic dispatch type badges |
| `app/templates/admin/knowledge_*.html` | Generic placeholder examples |
| `app/db/models.py` | Remove `IntegrationChannelConfig` class |
| `migrations/versions/XXX_drop_integration_channel_configs.py` | **New** — drop legacy table |

## Non-Goals

- Refactoring the dispatcher protocol itself (it's already generic)
- Moving `dispatch_type`/`dispatch_config` out of Task/Channel models (already generic JSONB)
- Changing the `client_id` prefix convention (`slack:C...`) — this is fine, it's a convention not a coupling
