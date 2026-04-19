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
            "Spawn one or more ephemeral sub-agents to perform focused tasks in parallel. "
            "Each sub-agent runs with minimal context (just your prompt), executes quickly, "
            "and returns its result directly to you — nothing is posted to the channel.\n\n"
            "Use this for grunt work: scanning files, summarizing text, researching topics, "
            "extracting data. Sub-agents run on cheaper models with minimal context, so they "
            "save money when you're on an expensive model or have a large conversation history. "
            "They also save time when you have multiple independent tasks to parallelize.\n\n"
            "**When to use:** 2+ independent tasks, or expensive parent model + grunt work.\n"
            "**When NOT to use:** Single simple task you can handle directly in one step.\n\n"
            f"Built-in presets: {_PRESET_SUMMARY}.\n"
            "You can also specify custom tools and system_prompt instead of a preset.\n\n"
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
                                    "gives the sub-agent file + exec_command + github_get_commit."
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
}, safety_tier="readonly", requires_bot_context=True, requires_channel_context=True)
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
        if r.elapsed_ms:
            entry["elapsed_ms"] = r.elapsed_ms
        output.append(entry)

    response: dict = {"results": output}
    if truncated:
        response["warning"] = f"Capped at {MAX_SUBAGENTS_PER_CALL} sub-agents. Remaining were dropped."

    return json.dumps(response, ensure_ascii=False)
