# Plan: Channel-Level Tool & Skill Overrides

## Problem
A bot configured with many tools becomes a bloated generalist everywhere it's deployed. Different channels need different tool subsets (e.g., a home-automation channel only needs HA tools, a coding channel only needs exec tools), but creating separate bots per channel is a maintenance nightmare.

## Design Philosophy
**Inheritance model**: Bot = capabilities (what's available), Channel = activation (what's active here).

```
bot.local_tools = [A, B, C, D, E]          # what's available
channel.tools_override = [A, C]             # what's active here (null = use bot defaults)
channel.tools_disabled = [B]                # explicitly suppress specific ones
```

Three modes per field:
1. **null** (default) — inherit everything from bot config
2. **override list** — only these tools are active (whitelist)
3. **disabled list** — remove these from bot defaults (blacklist)

Override takes precedence over disabled if both are set.

## Schema Changes

### Migration: `065_channel_tool_overrides.py`

Add columns to `channels` table:

```python
op.add_column("channels", sa.Column("local_tools_override", JSONB, nullable=True))
op.add_column("channels", sa.Column("local_tools_disabled", JSONB, nullable=True))
op.add_column("channels", sa.Column("mcp_servers_override", JSONB, nullable=True))
op.add_column("channels", sa.Column("mcp_servers_disabled", JSONB, nullable=True))
op.add_column("channels", sa.Column("client_tools_override", JSONB, nullable=True))
op.add_column("channels", sa.Column("client_tools_disabled", JSONB, nullable=True))
op.add_column("channels", sa.Column("pinned_tools_override", JSONB, nullable=True))
op.add_column("channels", sa.Column("skills_override", JSONB, nullable=True))
op.add_column("channels", sa.Column("skills_disabled", JSONB, nullable=True))
```

All nullable JSONB arrays. Null = inherit from bot.

### ORM: `Channel` model (`app/db/models.py`)

Add mapped columns:
```python
local_tools_override: Mapped[list | None]     # ["tool_a", "tool_c"] or None
local_tools_disabled: Mapped[list | None]      # ["tool_b"] or None
mcp_servers_override: Mapped[list | None]
mcp_servers_disabled: Mapped[list | None]
client_tools_override: Mapped[list | None]
client_tools_disabled: Mapped[list | None]
pinned_tools_override: Mapped[list | None]
skills_override: Mapped[list | None]           # [{id, mode, similarity_threshold}] or None
skills_disabled: Mapped[list | None]            # ["skill_id"] or None
```

## Resolution Logic

### New function: `resolve_effective_tools(bot: BotConfig, channel: Channel | None) -> EffectiveTools`

Location: `app/services/channels.py` (or new `app/agent/channel_overrides.py`)

```python
@dataclass
class EffectiveTools:
    local_tools: list[str]
    mcp_servers: list[str]
    client_tools: list[str]
    pinned_tools: list[str]
    skills: list[SkillConfig]

def resolve_effective_tools(bot: BotConfig, channel: Channel | None) -> EffectiveTools:
    """Resolve tool/skill lists with channel overrides."""
    if channel is None:
        return EffectiveTools(
            local_tools=bot.local_tools,
            mcp_servers=bot.mcp_servers,
            client_tools=bot.client_tools,
            pinned_tools=bot.pinned_tools,
            skills=bot.skills,
        )

    def _resolve(bot_list, override, disabled):
        if override is not None:
            # Whitelist mode: only items that exist in bot config
            return [t for t in override if t in bot_list]
        if disabled is not None:
            # Blacklist mode: remove disabled items
            return [t for t in bot_list if t not in disabled]
        return bot_list  # inherit

    return EffectiveTools(
        local_tools=_resolve(bot.local_tools, channel.local_tools_override, channel.local_tools_disabled),
        mcp_servers=_resolve(bot.mcp_servers, channel.mcp_servers_override, channel.mcp_servers_disabled),
        client_tools=_resolve(bot.client_tools, channel.client_tools_override, channel.client_tools_disabled),
        pinned_tools=_resolve(bot.pinned_tools, channel.pinned_tools_override, None),
        skills=_resolve_skills(bot.skills, channel.skills_override, channel.skills_disabled),
    )
```

Key constraint: channel can only **restrict** what the bot offers, never add tools the bot doesn't have. The override list is intersected with bot's list.

### Integration point: `context_assembly.py`

In `assemble_context()`, after loading bot config but before tool retrieval:

```python
# Current: uses bot.local_tools, bot.mcp_servers, etc. directly
# New: resolve effective tools from channel overrides
channel = await _load_channel(db, channel_id) if channel_id else None
effective = resolve_effective_tools(bot, channel)
# Use effective.local_tools, effective.mcp_servers, etc. for the rest of assembly
```

This is the **only** place resolution needs to happen — all downstream tool retrieval, schema building, and dispatch already use the lists built during context assembly.

### Integration point: `tool_dispatch.py`

No changes needed. Dispatch receives the tool schemas built during context assembly — it doesn't re-check bot config. If a tool wasn't in the assembled schemas, the LLM won't call it.

## API Changes

### Channel update endpoint (`PUT /channels/{channel_id}`)

Already exists in `api_v1_channels.py`. Extend the update schema to accept:

```python
class ChannelUpdate(BaseModel):
    # ... existing fields ...
    local_tools_override: list[str] | None = UNSET
    local_tools_disabled: list[str] | None = UNSET
    mcp_servers_override: list[str] | None = UNSET
    mcp_servers_disabled: list[str] | None = UNSET
    client_tools_override: list[str] | None = UNSET
    client_tools_disabled: list[str] | None = UNSET
    pinned_tools_override: list[str] | None = UNSET
    skills_override: list[dict] | None = UNSET
    skills_disabled: list[str] | None = UNSET
```

Use `UNSET` sentinel to distinguish "not sent" from "set to null" (null = clear override, revert to inherit).

### New endpoint: `GET /channels/{channel_id}/effective-tools`

Returns the resolved tool/skill lists after applying overrides. Useful for the UI to show what's actually active.

```python
@router.get("/channels/{channel_id}/effective-tools")
async def get_effective_tools(channel_id: UUID, db: AsyncSession = Depends(get_db)):
    channel = await _get_channel(db, channel_id)
    bot = get_bot(channel.bot_id)
    effective = resolve_effective_tools(bot, channel)
    return {
        "local_tools": effective.local_tools,
        "mcp_servers": effective.mcp_servers,
        "client_tools": effective.client_tools,
        "pinned_tools": effective.pinned_tools,
        "skills": [s.to_dict() for s in effective.skills],
        "mode": {
            "local_tools": "override" if channel.local_tools_override else "disabled" if channel.local_tools_disabled else "inherit",
            "mcp_servers": "override" if channel.mcp_servers_override else "disabled" if channel.mcp_servers_disabled else "inherit",
            # ... etc
        }
    }
```

## Admin UI Changes

### Channel admin page (`ui/app/(app)/admin/channels/`)

Currently likely shows basic channel info. Add a **Tools** tab or section:

**Mode selector per category** (local_tools, mcp_servers, client_tools, skills):
```
Local Tools:  ( ) Inherit from bot  ( ) Override (whitelist)  ( ) Disable (blacklist)
```

**When "Override"**: Show the bot's tools with checkboxes (same UI as bot editor). Only checked tools are active in this channel.

**When "Disable"**: Show the bot's tools with checkboxes. Checked tools are **disabled** in this channel.

**When "Inherit"**: Show a read-only preview of what the bot provides. Grayed out, no interaction.

### Channel detail API hook

```typescript
// ui/src/api/hooks/useChannels.ts
export function useChannelEffectiveTools(channelId: string) {
  return useQuery({
    queryKey: ["channel-effective-tools", channelId],
    queryFn: () => api.get(`/channels/${channelId}/effective-tools`),
  });
}
```

## File Changes Summary

| File | Change |
|------|--------|
| `migrations/versions/065_channel_tool_overrides.py` | New migration: 9 JSONB columns on channels |
| `app/db/models.py` | Add 9 Mapped columns to Channel |
| `app/agent/channel_overrides.py` | New file: `EffectiveTools` dataclass + `resolve_effective_tools()` |
| `app/agent/context_assembly.py` | Load channel, resolve effective tools, use throughout assembly |
| `app/routers/api_v1_channels.py` | Extend PUT schema, add `GET .../effective-tools` |
| `app/routers/api_v1_admin/channels.py` | Add admin endpoint for channel tool config (if separate from public API) |
| `ui/app/(app)/admin/channels/` | Channel tool override UI (inherit/override/disable mode selector + tool checkboxes) |
| `ui/src/api/hooks/useChannels.ts` | Add `useChannelEffectiveTools` hook |
| `ui/src/types/api.ts` | Add `ChannelToolOverrides` and `EffectiveTools` types |

## Implementation Order

1. **Migration + ORM** — Add columns, run migration
2. **Resolution logic** — `resolve_effective_tools()` in new module
3. **Wire into context_assembly** — Use resolved tools instead of raw bot config
4. **API** — Extend channel update + add effective-tools endpoint
5. **UI** — Channel tool override editor
6. **Tests** — Resolution logic (override wins, disabled works, null inherits, can't add tools bot doesn't have)

## Edge Cases
- Channel override lists tools the bot doesn't have → silently ignored (intersection)
- Bot adds new tools after channel override is set → new tools not auto-included in override mode (by design — override is a whitelist)
- Bot removes a tool that's in channel override → silently dropped (intersection)
- Both override and disabled set → override wins, disabled ignored
- Skills have richer config (mode, threshold) → override replaces entire skill entry, disabled just removes by id
