"""Sub-agent system — ephemeral, inline, parallel agent execution.

Sub-agents are lightweight workers that run synchronously within a parent's
tool call.  They get minimal context (system prompt + task prompt), no
conversation history, and return text directly to the parent — never posted
to the channel.

Presets define reusable sub-agent profiles (tool sets, default model tier,
system prompt).  Custom sub-agents can also be created ad-hoc by specifying
tools and system_prompt explicitly.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

SUBAGENT_PRESETS: dict[str, dict[str, Any]] = {
    "file-scanner": {
        "tools": ["file"],
        "system_prompt": (
            "You scan files and extract information. Be concise and precise. "
            "Return only what was asked for — no commentary."
        ),
        "default_tier": "fast",
    },
    "summarizer": {
        "tools": [],
        "system_prompt": (
            "You summarize input concisely. No preamble, no filler. "
            "Get straight to the point."
        ),
        "default_tier": "fast",
    },
    "researcher": {
        "tools": ["web_search"],
        "system_prompt": (
            "You research topics and return findings. Include sources when "
            "available. Be thorough but concise."
        ),
        "default_tier": "standard",
    },
    "code-reviewer": {
        "tools": ["file"],
        "system_prompt": (
            "You review code for bugs, security issues, and quality problems. "
            "Be specific — cite file paths and line numbers. Rate issues by severity."
        ),
        "default_tier": "standard",
    },
    "data-extractor": {
        "tools": ["file"],
        "system_prompt": (
            "You extract structured data from files and command output. "
            "Return data in a clean, parseable format (JSON when appropriate)."
        ),
        "default_tier": "fast",
    },
}

MAX_SUBAGENTS_PER_CALL = 10
MAX_RESULT_CHARS = 4000


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class SubagentResult:
    """Result from a single sub-agent execution."""
    index: int
    preset: str | None
    status: str  # "ok" or "error"
    result: str
    model: str | None = None
    elapsed_ms: int = 0
    tool_names: list[str] = field(default_factory=list)
    blocked_tools: list[str] = field(default_factory=list)
    correlation_id: str | None = None


_FORBIDDEN_TOOLS = {"spawn_subagents", "delegate_to_agent", "delegate_to_exec"}


def _filter_subagent_tools(requested_tools: list[str]) -> tuple[list[str], list[str]]:
    """Allow only readonly tools inside sub-agents.

    Sub-agents are intentionally bounded sidecars, not a second execution loop.
    Unknown, recursive, mutating, exec-capable, and control-plane tools are
    stripped even if the parent explicitly requested them.
    """
    from app.tools.registry import get_tool_safety_tier

    allowed: list[str] = []
    blocked: list[str] = []
    for tool_name in requested_tools:
        if tool_name in _FORBIDDEN_TOOLS:
            blocked.append(tool_name)
            continue
        if get_tool_safety_tier(tool_name) != "readonly":
            blocked.append(tool_name)
            continue
        allowed.append(tool_name)
    return allowed, blocked


# ---------------------------------------------------------------------------
# Core execution
# ---------------------------------------------------------------------------

async def run_subagent(
    prompt: str,
    *,
    preset: str | None = None,
    tools: list[str] | None = None,
    system_prompt: str | None = None,
    model_tier: str | None = None,
    model: str | None = None,
    max_chars: int = MAX_RESULT_CHARS,
    # Parent context (passed through from the tool)
    parent_session_id: uuid.UUID | None = None,
    parent_bot_id: str | None = None,
    channel_id: uuid.UUID | None = None,
) -> SubagentResult:
    """Run a single sub-agent and return its result.

    Resolution order for tools/system_prompt/model:
    1. Explicit params (tools=, system_prompt=, model=)
    2. Preset defaults
    3. Fallbacks (empty tools, generic prompt, parent's model)
    """
    from app.agent.bots import BotConfig, get_bot
    from app.agent.context import (
        current_run_origin,
        current_channel_model_tier_overrides,
        restore_agent_context,
        set_agent_context,
        snapshot_agent_context,
    )
    from app.agent.loop import run_agent_tool_loop
    from app.agent.recording import _record_trace_event
    from app.services.server_config import resolve_model_tier
    from app.tools.registry import get_local_tool_schemas

    t0 = time.monotonic()

    # Resolve preset
    preset_config = SUBAGENT_PRESETS.get(preset) if preset else None
    if preset and not preset_config:
        return SubagentResult(
            index=0,
            preset=preset,
            status="error",
            result=f"Unknown preset: {preset!r}. Available: {sorted(SUBAGENT_PRESETS.keys())}",
        )

    # Resolve effective values.
    # Tools merge: preset tools + explicit additions (deduped, preset order
    # preserved). Previously explicit `tools` replaced the preset entirely,
    # which trapped LLMs into restating the preset tool list whenever they
    # wanted to add one tool. Concrete failure: a parent picked
    # `data-extractor` (preset = ["file"]) and tried to add
    # `github_get_commit` — explicit tools fully replaced, the sub-agent
    # got only `[github_get_commit]` and couldn't read files.
    preset_tools: list[str] = preset_config.get("tools", []) if preset_config else []
    extra_tools: list[str] = list(tools) if tools else []
    seen: set[str] = set()
    effective_tools: list[str] = []
    for t in preset_tools + extra_tools:
        if t and t not in seen:
            seen.add(t)
            effective_tools.append(t)
    effective_system = system_prompt or (preset_config.get("system_prompt", "") if preset_config else "You are a helpful assistant. Be concise.")
    effective_tier = model_tier or (preset_config.get("default_tier") if preset_config else None)

    # Resolve model: explicit > tier > parent bot's model
    effective_model: str | None = model
    effective_provider: str | None = None
    if not effective_model and effective_tier:
        channel_overrides = current_channel_model_tier_overrides.get()
        resolved = resolve_model_tier(effective_tier, channel_overrides)
        if resolved:
            effective_model, effective_provider = resolved

    if not effective_model:
        # Fall back to parent bot's model
        try:
            parent_bot = get_bot(parent_bot_id or "default")
            effective_model = parent_bot.model
            effective_provider = parent_bot.model_provider_id
        except Exception:
            effective_model = settings.DEFAULT_MODEL

    # Sub-agents are deliberately capped at readonly sidecar work.
    effective_tools, blocked_tools = _filter_subagent_tools(effective_tools)
    subagent_correlation_id = uuid.uuid4()

    # Build minimal messages (system prompt + user prompt only)
    messages: list[dict] = [
        {"role": "system", "content": effective_system},
        {"role": "user", "content": prompt},
    ]

    # Build tool schemas for the sub-agent
    tool_schemas = get_local_tool_schemas(effective_tools) if effective_tools else []

    # Create a minimal BotConfig for the sub-agent
    subagent_bot = BotConfig(
        id=f"_subagent_{uuid.uuid4().hex[:8]}",
        name="Sub-Agent",
        model=effective_model,
        model_provider_id=effective_provider,
        system_prompt=effective_system,
        local_tools=effective_tools,
        tool_retrieval=False,
        persona=False,
        context_compaction=False,
    )

    # Snapshot parent context, run sub-agent, restore
    parent_ctx = snapshot_agent_context()
    final_response = ""
    try:
        # Use parent bot ID in context so tools that call get_bot() find a real bot.
        # The sub-agent's BotConfig is only used for the tool loop config.
        set_agent_context(
            session_id=parent_session_id,
            bot_id=parent_bot_id or "default",
            correlation_id=subagent_correlation_id,
            channel_id=channel_id,
            dispatch_type=None,  # No dispatch — results stay inline
            dispatch_config=None,
        )
        current_run_origin.set("subagent")

        if parent_session_id is not None:
            await _record_trace_event(
                correlation_id=subagent_correlation_id,
                session_id=parent_session_id,
                bot_id=parent_bot_id,
                client_id=None,
                event_type="subagent_started",
                data={
                    "preset": preset,
                    "model": effective_model,
                    "model_tier": effective_tier,
                    "requested_tools": preset_tools + extra_tools,
                    "tool_names": effective_tools,
                    "blocked_tools": blocked_tools,
                    "prompt_preview": prompt[:300],
                },
            )

        tools_used: list[str] = []

        async for event in run_agent_tool_loop(
            messages,
            subagent_bot,
            session_id=parent_session_id,
            correlation_id=subagent_correlation_id,
            model_override=effective_model,
            provider_id_override=effective_provider,
            pre_selected_tools=tool_schemas,
            max_iterations=5,  # Sub-agents should be quick
            skip_tool_policy=False,
        ):
            if event.get("type") == "response":
                final_response = event.get("text", "")
            elif event.get("type") == "assistant_text":
                # Accumulate intermediate text as the response
                final_response = event.get("text", "")
            elif event.get("type") == "tool_start":
                tool_name = event.get("tool")
                if isinstance(tool_name, str) and tool_name not in tools_used:
                    tools_used.append(tool_name)
    except Exception as exc:
        logger.exception("Sub-agent execution failed")
        elapsed = int((time.monotonic() - t0) * 1000)
        if parent_session_id is not None:
            await _record_trace_event(
                correlation_id=subagent_correlation_id,
                session_id=parent_session_id,
                bot_id=parent_bot_id,
                client_id=None,
                event_type="subagent_finished",
                event_name="error",
                data={
                    "preset": preset,
                    "model": effective_model,
                    "tool_names": effective_tools,
                    "blocked_tools": blocked_tools,
                    "error": str(exc),
                },
                duration_ms=elapsed,
            )
        return SubagentResult(
            index=0,
            preset=preset,
            status="error",
            result=f"Execution failed: {exc}",
            model=effective_model,
            elapsed_ms=elapsed,
            tool_names=list(effective_tools),
            blocked_tools=list(blocked_tools),
            correlation_id=str(subagent_correlation_id),
        )
    finally:
        await asyncio.sleep(0)  # Let pending tasks settle
        restore_agent_context(parent_ctx)

    # Truncate result if needed
    if len(final_response) > max_chars:
        final_response = final_response[:max_chars] + f"\n... (truncated at {max_chars} chars)"

    elapsed = int((time.monotonic() - t0) * 1000)
    if parent_session_id is not None:
        await _record_trace_event(
            correlation_id=subagent_correlation_id,
            session_id=parent_session_id,
            bot_id=parent_bot_id,
            client_id=None,
            event_type="subagent_finished",
            event_name="ok",
            data={
                "preset": preset,
                "model": effective_model,
                "tool_names": tools_used,
                "blocked_tools": blocked_tools,
                "result_chars": len(final_response or ""),
            },
            duration_ms=elapsed,
        )
    return SubagentResult(
        index=0,
        preset=preset,
        status="ok",
        result=final_response or "(empty response)",
        model=effective_model,
        elapsed_ms=elapsed,
        tool_names=tools_used,
        blocked_tools=list(blocked_tools),
        correlation_id=str(subagent_correlation_id),
    )


async def run_subagents(
    specs: list[dict[str, Any]],
    *,
    parent_session_id: uuid.UUID | None = None,
    parent_bot_id: str | None = None,
    channel_id: uuid.UUID | None = None,
) -> list[SubagentResult]:
    """Run multiple sub-agents in parallel and collect results.

    Each spec dict can contain: preset, prompt, tools, system_prompt,
    model_tier, model, max_chars.
    """
    if len(specs) > MAX_SUBAGENTS_PER_CALL:
        # Run up to the limit, report truncation
        specs = specs[:MAX_SUBAGENTS_PER_CALL]

    tasks = []
    for i, spec in enumerate(specs):
        prompt = spec.get("prompt", "")
        if not prompt:
            # Return an error result for missing prompts
            async def _error_result(idx=i):
                return SubagentResult(index=idx, preset=None, status="error", result="Missing 'prompt' field")
            tasks.append(_error_result())
            continue

        coro = run_subagent(
            prompt,
            preset=spec.get("preset"),
            tools=spec.get("tools"),
            system_prompt=spec.get("system_prompt"),
            model_tier=spec.get("model_tier"),
            model=spec.get("model"),
            max_chars=spec.get("max_chars", MAX_RESULT_CHARS),
            parent_session_id=parent_session_id,
            parent_bot_id=parent_bot_id,
            channel_id=channel_id,
        )
        tasks.append(coro)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    final: list[SubagentResult] = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            final.append(SubagentResult(
                index=i, preset=specs[i].get("preset"), status="error",
                result=f"Exception: {r}",
            ))
        elif isinstance(r, SubagentResult):
            r.index = i
            final.append(r)
        else:
            final.append(SubagentResult(
                index=i, preset=specs[i].get("preset"), status="error",
                result=f"Unexpected result type: {type(r)}",
            ))

    return final
