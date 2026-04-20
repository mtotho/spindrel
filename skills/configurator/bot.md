---
name: Configurator — Bot Scope
description: >
  Sub-skill of `configurator`. When fixing a bot's configuration, this is
  the investigate-and-propose playbook: which traces to read, which fields
  are in the allowlist, and which rationale patterns hold up under review.
use_when: >
  Parent `configurator` skill has delegated to bot-scope work — user's
  symptom maps to a bot-level setting (tool discovery, prompt, memory,
  model).
triggers: bot config, bot isn't using, tool_similarity_threshold, pinned_tools, system_prompt, memory_scheme, bot model
category: core
---

# Configurator — Bot scope

## Investigate

Pick the narrowest investigation that produces ≥2 citeable correlation_ids.

| User symptom | Investigate with |
|---|---|
| Tool-discovery issue ("not using X") | `get_trace(bot_id=X, event_type="tool_ranking", limit=10, include_user_message=true)` + `list_tool_signatures()` to confirm the tool exists + its description. |
| Persona / verbosity / wrong-tone | `get_trace(bot_id=X, limit=10, include_user_message=true)` — read the user/assistant pairs; quote the drift. |
| Memory / compaction issue | `get_bot(X)` (current knobs) + `get_trace(bot_id=X, event_type="memory_compaction", limit=5)` + `get_trace(bot_id=X, event_type="token_usage", limit=10)` if the concern is context overflow. |
| "Wrong model for this task" | `get_trace(bot_id=X, event_type="llm_status", limit=10)` to see retries/fallbacks + `get_bot(X)` for current `model`/`provider_id`. |

Don't fetch 100 events. 5–10 is plenty. If the signal isn't clear from
those, ask the user for more specifics before proposing.

## Propose — field allowlist

You may emit `propose_config_change(scope="bot", ...)` only with these
fields:

| Field | Type | Notes |
|---|---|---|
| `pinned_tools` | `list[str]` | Full replacement list. Quote the tool names from `list_tool_signatures()`. Include all existing pins unless you're explicitly removing one. |
| `tool_similarity_threshold` | `float` 0.0–1.0 | Lower widens recall. Typical range 0.25–0.45. |
| `system_prompt` | `str` | Full replacement. Preserve any stable preamble the user originally wrote — only rewrite the section you're targeting. Include a diff_preview showing `before: ...` / `after: ...`. |
| `memory_scheme` | `"workspace-files"` | Only active option today. If the bot isn't on it, proposing the switch is fair game. |
| `model` | `str` | Must match an enrolled `provider_models.model_id`. Pair with `provider_id` if switching providers. |
| `provider_id` | `str` | UUID of an enrolled provider. |
| `tool_discovery` | `"on"` / `"off"` | Turns on semantic tool RAG. |

## Refuse

If the user asks you to change anything outside this list (API keys, scope
settings, workspace paths, DB state), say so:

> "That's not in my allowlist. You can change it in Admin → Bots → {bot}."

## Rationale patterns that hold up

- **Quantitative**: "Current threshold 0.5; 4 of 5 recent queries had the
  right tool scored 0.31–0.42 and got dropped. Proposing 0.30."
- **Qualitative-with-evidence**: "In the last 3 turns, bot explained the
  weather in flowery metaphors where user asked for one-line answers. See
  correlation_ids X, Y, Z. Proposing prompt tweak with diff_preview."

## Rationale patterns that get rejected

- "Might work better" (no numbers, no citations)
- "Other bots have X=Y so this should too" (hearsay)
- "User complained" without quoted traces or settings drift
