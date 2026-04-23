"""Tool: spawn_subagents — run ephemeral sub-agents inline with parallel execution."""

import json
import logging

from app.agent.context import (
    current_bot_id,
    current_channel_id,
    current_session_id,
)
from app.agent.subagents import MAX_SUBAGENTS_PER_CALL, SUBAGENT_PRESETS
from app.tools.registry import register

logger = logging.getLogger(__name__)

_PRESET_SUMMARY = ", ".join(
    f"{name} ({cfg.get('default_tier', 'standard')})"
    for name, cfg in sorted(SUBAGENT_PRESETS.items())
)


@register({
    "type": "function",
        "function": {
            "name": "spawn_subagents",
            "description": (
                "Spawn one or more ephemeral sub-agents to perform bounded, parallel, read-only side research. "
                "Each sub-agent runs with minimal context (just your prompt), executes quickly, "
                "and returns its result directly to you — nothing is posted to the channel.\n\n"
                "Use this only for independent side tasks like file scanning, summarizing text, "
                "lightweight research, or extracting data before you synthesize the answer. "
                "Sub-agents are not a general planning-or-reasoning shortcut and should not own "
                "the critical path of the turn.\n\n"
                "**When to use:** 2+ bounded independent read-only tasks.\n"
                "**When NOT to use:** single simple work, anything requiring mutating or exec-capable tools, "
                "or work that depends on the full conversation context.\n\n"
                f"Built-in presets: {_PRESET_SUMMARY}.\n"
                "You can also specify custom readonly tools and system_prompt instead of a preset. "
                "Mutating, exec-capable, control-plane, and recursive delegation tools are dropped.\n\n"
                f"Maximum {MAX_SUBAGENTS_PER_CALL} sub-agents per call."
            ),
        "parameters": {
            "type": "object",
            "properties": {
                "agents": {
                    "type": "array",
                    "description": "List of sub-agent specs to run in parallel.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "preset": {
                                "type": "string",
                                "description": (
                                    "Named preset (file-scanner, summarizer, researcher, "
                                    "code-reviewer, data-extractor). Sets tools, system prompt, "
                                    "and default model tier. Optional if tools + system_prompt given."
                                ),
                            },
                            "prompt": {
                                "type": "string",
                                "description": "The task for the sub-agent. Be specific and focused.",
                            },
                            "tools": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "Additional tools to make available to the sub-agent. "
                                    "These ADD to the preset's tool list — you do NOT need to "
                                    "restate the preset's tools. "
                                    "Example: preset=\"data-extractor\" + tools=[\"github_get_commit\"] "
                                    "gives the sub-agent file + github_get_commit."
                                ),
                            },
                            "system_prompt": {
                                "type": "string",
                                "description": "Custom system prompt (overrides preset).",
                            },
                            "model_tier": {
                                "type": "string",
                                "enum": ["free", "fast", "standard", "capable", "frontier"],
                                "description": "Model tier override. Default comes from preset.",
                            },
                            "model": {
                                "type": "string",
                                "description": (
                                    "Explicit model ID (overrides tier and preset). "
                                    "Use only when you need a specific model."
                                ),
                            },
                            "max_chars": {
                                "type": "integer",
                                "description": "Max characters in the result (default 4000). Truncates if exceeded.",
                            },
                        },
                        "required": ["prompt"],
                    },
                },
            },
            "required": ["agents"],
        },
    },
}, safety_tier="readonly", requires_bot_context=True, requires_channel_context=True, returns={
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "status": {"type": "string"},
                    "result": {"type": ["string", "null"]},
                    "preset": {"type": "string"},
                    "model": {"type": ["string", "null"]},
                    "elapsed_ms": {"type": "number"},
                    "tool_names": {"type": "array", "items": {"type": "string"}},
                    "blocked_tools": {"type": "array", "items": {"type": "string"}},
                    "correlation_id": {"type": ["string", "null"]},
                },
                "required": ["index", "status"],
            },
        },
        "warning": {"type": "string"},
        "error": {"type": "string"},
    },
})
async def spawn_subagents(agents: list[dict]) -> str:
    """Run sub-agents in parallel and return collected results."""
    from app.agent.subagents import run_subagents

    if not agents:
        return json.dumps({"error": "No agents specified."}, ensure_ascii=False)

    if len(agents) > MAX_SUBAGENTS_PER_CALL:
        # Truncate and warn
        agents = agents[:MAX_SUBAGENTS_PER_CALL]
        truncated = True
    else:
        truncated = False

    session_id = current_session_id.get()
    bot_id = current_bot_id.get()
    channel_id = current_channel_id.get()

    results = await run_subagents(
        agents,
        parent_session_id=session_id,
        parent_bot_id=bot_id,
        channel_id=channel_id,
    )

    output = []
    for r in results:
        entry: dict = {
            "index": r.index,
            "status": r.status,
            "result": r.result,
        }
        if r.preset:
            entry["preset"] = r.preset
        if r.model:
            entry["model"] = r.model
        if r.elapsed_ms:
            entry["elapsed_ms"] = r.elapsed_ms
        if r.tool_names:
            entry["tool_names"] = r.tool_names
        if r.blocked_tools:
            entry["blocked_tools"] = r.blocked_tools
        if r.correlation_id:
            entry["correlation_id"] = r.correlation_id
        output.append(entry)

    response: dict = {"results": output}
    if truncated:
        response["warning"] = f"Capped at {MAX_SUBAGENTS_PER_CALL} sub-agents. Remaining were dropped."

    return json.dumps(response, ensure_ascii=False)
