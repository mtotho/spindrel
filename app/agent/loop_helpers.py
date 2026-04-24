import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from app.agent.bots import BotConfig
from app.agent.hooks import HookContext, fire_hook
from app.agent.llm import FallbackInfo, strip_malformed_tool_calls, strip_silent_tags, strip_think_tags
from app.agent.message_utils import (
    _event_with_compaction_tag,
    _extract_client_actions,
    _extract_transcript,
)
from app.agent.recording import _record_trace_event
from app.agent.tracing import _trace
from app.utils import safe_create_task

if TYPE_CHECKING:
    from app.agent.loop_dispatch import SummarizeSettings

logger = logging.getLogger(__name__)


def _resolve_effective_provider(
    model_override: str | None,
    provider_id_override: str | None,
    bot_model_provider_id: str | None,
) -> str | None:
    """Resolve the effective provider for the current call."""
    from app.services.providers import resolve_effective_provider

    return resolve_effective_provider(
        model_override,
        provider_id_override,
        bot_model_provider_id,
    )


_CORRECTION_RE = re.compile(
    r"^(no[,.]?\s(?!problem|worries|thanks|thank|need|rush|idea)"
    r"|wrong|that'?s not"
    r"|actually[,.]?\s(?!thanks|thank|great|good|perfect|nice|fine)"
    r"|incorrect|not quite|you should)"
    r"|(?:\bthat'?s\s+(?:wrong|incorrect))|(?:\byou\s+misunderstood)|(?:\bi\s+(?:said|meant)\b)",
    re.IGNORECASE,
)


def _extract_last_user_text(messages: list[dict]) -> str | None:
    """Extract text content of the last user message in the list."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        return part["text"]
                    if isinstance(part, str):
                        return part
            return None
    return None


def _sanitize_llm_text(raw: str) -> str:
    """Apply all sanitization passes to raw LLM text output."""
    return strip_malformed_tool_calls(strip_silent_tags(strip_think_tags(raw)))


async def _record_fallback_event(
    fb_info: FallbackInfo,
    *,
    session_id: uuid.UUID | None,
    channel_id: uuid.UUID | None,
    bot_id: str | None,
) -> None:
    """Write a ModelFallbackEvent row to the DB."""
    try:
        from app.agent.llm import get_cooldown_expiry
        from app.db.engine import async_session
        from app.db.models import ModelFallbackEvent

        cooldown_until = get_cooldown_expiry(fb_info.original_model)

        async with async_session() as db:
            db.add(ModelFallbackEvent(
                model=fb_info.original_model,
                fallback_model=fb_info.fallback_model,
                reason=fb_info.reason,
                error_message=(fb_info.original_error or "")[:2000] or None,
                session_id=session_id,
                channel_id=channel_id,
                bot_id=bot_id,
                cooldown_until=cooldown_until,
            ))
            await db.commit()
    except Exception:
        logger.warning("Failed to record fallback event", exc_info=True)


def _extract_usage_extras(response: Any) -> dict[str, Any]:
    """Extract cached_tokens and response_cost from a raw OpenAI/LiteLLM response."""
    extras: dict[str, Any] = {}
    usage = response.usage
    if not usage:
        return extras

    details = getattr(usage, "prompt_tokens_details", None)
    if details:
        cached = getattr(details, "cached_tokens", None)
        if cached is not None:
            extras["cached_tokens"] = cached

    cost = None
    if hasattr(response, "_hidden_params"):
        cost = getattr(response, "_hidden_params", {}).get("response_cost")
    if cost is None and hasattr(response, "model_extra"):
        hidden = (response.model_extra or {}).get("_hidden_params", {})
        if isinstance(hidden, dict):
            cost = hidden.get("response_cost")
    if cost is not None:
        extras["response_cost"] = cost

    return extras


_EMPTY_RESPONSE_GENERIC_FALLBACK = (
    "I had trouble generating a response. Could you try again?"
)


def _synthesize_empty_response_fallback(
    tool_calls_made: list[str],
    messages: list[dict],
) -> str:
    """Build the user-facing text when both LLM iterations return 0 tokens."""
    if not tool_calls_made:
        return _EMPTY_RESPONSE_GENERIC_FALLBACK

    seen = list(dict.fromkeys(tool_calls_made))
    tool_list = ", ".join(seen)

    last_tool_text: str | None = None
    for message in reversed(messages):
        if message.get("role") != "tool":
            continue
        content = message.get("content")
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        if isinstance(content, str) and content.strip():
            last_tool_text = content.strip()[:500]
        break

    if last_tool_text:
        return f"I completed {tool_list}. Result: {last_tool_text}"
    return f"I completed {tool_list} but couldn't generate a summary."


def _append_transcript_text_entry(entries: list[dict], text: str) -> None:
    if not text:
        return
    if entries and entries[-1].get("kind") == "text":
        entries[-1]["text"] = f'{entries[-1].get("text", "")}{text}'
        return
    entries.append({
        "id": f"text:{len(entries) + 1}",
        "kind": "text",
        "text": text,
    })


def _append_transcript_tool_entry(entries: list[dict], tool_call_id: str) -> None:
    entries.append({
        "id": f"tool:{tool_call_id}",
        "kind": "tool_call",
        "toolCallId": tool_call_id,
    })


def _collapse_final_assistant_tool_turn(messages: list[dict], *, turn_start: int) -> None:
    """Move current-turn assistant tool_calls onto the final assistant row."""
    assistant_indices = [
        index for index, msg in enumerate(messages)
        if index >= turn_start and msg.get("role") == "assistant"
    ]
    if not assistant_indices:
        return

    final_idx = assistant_indices[-1]
    final_msg = messages[final_idx]
    tool_call_by_id: dict[str, dict] = {}
    ordered_tool_call_ids: list[str] = []
    anonymous_tool_calls: list[dict] = []

    for index in assistant_indices:
        msg = messages[index]
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            continue
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            tool_call_id = tool_call.get("id")
            if isinstance(tool_call_id, str) and tool_call_id:
                if tool_call_id not in tool_call_by_id:
                    ordered_tool_call_ids.append(tool_call_id)
                tool_call_by_id[tool_call_id] = tool_call
            else:
                anonymous_tool_calls.append(tool_call)
        if index != final_idx:
            msg["_hidden"] = True

    if not tool_call_by_id and not anonymous_tool_calls:
        return

    ordered_tool_calls: list[dict] = []
    seen_tool_call_ids: set[str] = set()
    assistant_turn_body = final_msg.get("_assistant_turn_body")
    items = assistant_turn_body.get("items") if isinstance(assistant_turn_body, dict) else None
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict) or item.get("kind") != "tool_call":
                continue
            tool_call_id = item.get("toolCallId")
            if not isinstance(tool_call_id, str) or not tool_call_id or tool_call_id in seen_tool_call_ids:
                continue
            tool_call = tool_call_by_id.get(tool_call_id)
            if tool_call is None:
                continue
            ordered_tool_calls.append(tool_call)
            seen_tool_call_ids.add(tool_call_id)

    for tool_call_id in ordered_tool_call_ids:
        if tool_call_id in seen_tool_call_ids:
            continue
        ordered_tool_calls.append(tool_call_by_id[tool_call_id])
        seen_tool_call_ids.add(tool_call_id)

    ordered_tool_calls.extend(anonymous_tool_calls)
    final_msg["tool_calls"] = ordered_tool_calls


def _finalize_response(
    text: str,
    *,
    messages: list[dict],
    bot: BotConfig,
    session_id: uuid.UUID | None,
    client_id: str | None,
    correlation_id: uuid.UUID | None,
    channel_id: uuid.UUID | None,
    compaction: bool,
    native_audio: bool,
    user_msg_index: int | None,
    transcript_emitted: bool,
    tool_calls_made: list[str],
    tool_envelopes_made: list[dict],
    transcript_entries: list[dict],
    thinking_content_buf: str,
    turn_start: int,
    embedded_client_actions: list[dict],
) -> tuple[list[dict], bool]:
    """Shared response finalization: transcript, tracing, hooks, tools_used, response event."""
    events: list[dict] = []

    if native_audio and user_msg_index is not None and not transcript_emitted:
        transcript, text = _extract_transcript(text)
        messages[-1]["content"] = text
        events.append(_event_with_compaction_tag({"type": "transcript", "text": transcript}, compaction))
        if transcript:
            messages[user_msg_index] = {"role": "user", "content": transcript}
        else:
            messages[user_msg_index] = {"role": "user", "content": "[inaudible]"}
        transcript_emitted = True

    if not text.strip() and not tool_calls_made:
        logger.warning("_finalize_response received empty text with no tool calls — applying fallback.")
        text = _EMPTY_RESPONSE_GENERIC_FALLBACK
        if messages and messages[-1].get("role") == "assistant":
            messages[-1]["content"] = text

    _trace("✓ response (%d chars)", len(text))
    logger.info("Final response (%d chars): %r", len(text), text[:120])

    if correlation_id is not None and not compaction:
        safe_create_task(_record_trace_event(
            correlation_id=correlation_id,
            session_id=session_id,
            bot_id=bot.id,
            client_id=client_id,
            event_type="response",
            data={"text": text[:500], "full_length": len(text)},
        ))

    safe_create_task(fire_hook("after_response", HookContext(
        bot_id=bot.id, session_id=session_id, channel_id=channel_id,
        client_id=client_id, correlation_id=correlation_id,
        extra={"response_length": len(text), "tool_calls_made": list(tool_calls_made)},
    )))

    if tool_calls_made and messages and messages[-1].get("role") == "assistant":
        messages[-1]["_tools_used"] = list(tool_calls_made)
        if tool_envelopes_made:
            messages[-1]["_tool_envelopes"] = list(tool_envelopes_made)

    if thinking_content_buf and messages and messages[-1].get("role") == "assistant":
        messages[-1]["_thinking_content"] = thinking_content_buf

    if transcript_entries and messages and messages[-1].get("role") == "assistant":
        messages[-1]["_assistant_turn_body"] = {
            "version": 1,
            "items": list(transcript_entries),
        }

    if messages and messages[-1].get("role") == "assistant":
        _collapse_final_assistant_tool_turn(messages, turn_start=turn_start)

    events.append(_event_with_compaction_tag({
        "type": "response",
        "text": text,
        "tools_used": list(tool_calls_made) if tool_calls_made else None,
        "client_actions": (
            _extract_client_actions(messages, turn_start) + embedded_client_actions
        ),
        **({"correlation_id": str(correlation_id)} if correlation_id else {}),
    }, compaction))

    return events, transcript_emitted


def _sanitize_messages(messages: list[dict]) -> list[dict]:
    """Ensure no message has null/missing content and remove orphaned tool rows."""
    valid_tc_ids: set[str] = set()
    for message in messages:
        if message.get("role") == "assistant" and message.get("tool_calls"):
            for tool_call in message["tool_calls"]:
                tool_call_id = tool_call.get("id") if isinstance(tool_call, dict) else getattr(tool_call, "id", None)
                if tool_call_id:
                    valid_tc_ids.add(tool_call_id)

    index = 0
    while index < len(messages):
        message = messages[index]
        if "content" not in message or message["content"] is None:
            messages[index] = {**message, "content": ""}
        if message.get("role") == "tool" and message.get("tool_call_id"):
            if message["tool_call_id"] not in valid_tc_ids:
                messages.pop(index)
                continue
        index += 1
    return messages


# ---------------------------------------------------------------------------
# run_agent_tool_loop setup helpers (Cluster 6a extraction)
# ---------------------------------------------------------------------------


@dataclass
class LoopRunConfig:
    effective_max_iterations: int
    model: str
    provider_id: str | None
    effective_model_params: dict[str, Any]
    summarize_settings: "SummarizeSettings"
    in_loop_keep_iterations: int


def _resolve_loop_config(
    bot: BotConfig,
    *,
    max_iterations: int | None,
    model_override: str | None,
    provider_id_override: str | None,
    context_profile_name: str | None,
) -> LoopRunConfig:
    """Resolve per-run config: iterations, model, provider, effort overlay, summarize settings."""
    from app.agent.context import current_effort_override
    from app.agent.context_profiles import get_context_profile
    from app.agent.loop_dispatch import SummarizeSettings
    from app.config import settings

    in_loop_keep_iterations = settings.IN_LOOP_PRUNING_KEEP_ITERATIONS
    if context_profile_name:
        profile_override = get_context_profile(context_profile_name).keep_iterations_override
        if profile_override is not None:
            in_loop_keep_iterations = profile_override

    effective_max_iterations = (
        max_iterations
        or getattr(bot, "max_iterations", None)
        or settings.AGENT_MAX_ITERATIONS
    )
    model = model_override or bot.model
    provider_id = _resolve_effective_provider(
        model_override, provider_id_override, bot.model_provider_id,
    )

    effective_model_params = dict(bot.model_params or {})
    effort_now = current_effort_override.get()
    if effort_now:
        effective_model_params["effort"] = effort_now

    trc = bot.tool_result_config or {}
    summarize_settings = SummarizeSettings(
        enabled=trc["enabled"] if "enabled" in trc else settings.TOOL_RESULT_SUMMARIZE_ENABLED,
        threshold=trc.get("threshold") or settings.TOOL_RESULT_SUMMARIZE_THRESHOLD,
        model=trc.get("model") or settings.TOOL_RESULT_SUMMARIZE_MODEL or model,
        max_tokens=trc.get("max_tokens") or settings.TOOL_RESULT_SUMMARIZE_MAX_TOKENS,
        exclude=frozenset(settings.TOOL_RESULT_SUMMARIZE_EXCLUDE_TOOLS)
              | frozenset(trc.get("exclude_tools") or []),
    )
    return LoopRunConfig(
        effective_max_iterations=effective_max_iterations,
        model=model,
        provider_id=provider_id,
        effective_model_params=effective_model_params,
        summarize_settings=summarize_settings,
        in_loop_keep_iterations=in_loop_keep_iterations,
    )


@dataclass
class LoopToolState:
    all_tools: list[dict[str, Any]]
    tools_param: list[dict[str, Any]] | None
    tool_choice: str | None
    effective_allowed: set[str] | None
    has_manage_bot_skill: bool
    activated_list: list[dict]


async def _resolve_loop_tools(
    bot: BotConfig,
    *,
    pre_selected_tools: list[dict[str, Any]] | None,
    authorized_tool_names: set[str] | None,
    compaction: bool,
    get_local_tool_schemas_fn: Any,
    fetch_mcp_tools_fn: Any,
    get_client_tool_schemas_fn: Any,
    merge_tool_schemas_fn: Any,
) -> LoopToolState:
    """Assemble tool schemas + authorization set + mid-loop activation slot.

    Schema-fetch callables are injected rather than imported directly so tests
    that patch them on ``app.agent.loop`` continue to intercept (same pattern
    as Cluster 5's ``dispatch_tool_call_fn`` injection).

    Handles: pre-selected-tools passthrough, bot-tool fetch + auto-inject of
    ``get_skill``/``get_skill_list``, ContextVar-injected dynamic tools (e.g.
    ``heartbeat_post_to_thread``), and ``current_activated_tools`` seeding for
    downstream ``get_tool_info`` mid-loop activations.
    """
    from app.agent.context import current_activated_tools, current_injected_tools

    if pre_selected_tools is not None:
        all_tools = merge_tool_schemas_fn(pre_selected_tools)
    else:
        local_schemas = get_local_tool_schemas_fn(list(bot.local_tools))
        mcp_schemas = await fetch_mcp_tools_fn(bot.mcp_servers)
        client_schemas = get_client_tool_schemas_fn(bot.client_tools)
        all_tools = local_schemas + mcp_schemas + client_schemas
        existing_names = {t.get("function", {}).get("name") for t in all_tools}
        skill_tools_to_add = [
            n for n in ("get_skill", "get_skill_list")
            if n not in existing_names
        ]
        if skill_tools_to_add:
            all_tools = all_tools + get_local_tool_schemas_fn(skill_tools_to_add)
        injected = current_injected_tools.get()
        if injected:
            existing = {t["function"]["name"] for t in all_tools}
            for t in injected:
                if t["function"]["name"] not in existing:
                    all_tools.append(t)

    tools_param = all_tools if all_tools else None
    tool_choice = "auto" if tools_param else None

    if authorized_tool_names:
        effective_allowed: set[str] | None = set(authorized_tool_names)
    elif all_tools:
        effective_allowed = {t["function"]["name"] for t in all_tools}
    else:
        effective_allowed = None

    activated_list: list[dict] = []
    current_activated_tools.set(activated_list)

    has_manage_bot_skill = (
        not compaction
        and bot.memory_scheme == "workspace-files"
        and any(t["function"]["name"] == "manage_bot_skill" for t in all_tools or [])
    )

    return LoopToolState(
        all_tools=all_tools,
        tools_param=tools_param,
        tool_choice=tool_choice,
        effective_allowed=effective_allowed,
        has_manage_bot_skill=has_manage_bot_skill,
        activated_list=activated_list,
    )


async def _inject_opening_skill_nudges(
    *,
    bot: BotConfig,
    messages: list[dict],
    has_manage_bot_skill: bool,
    correlation_id: uuid.UUID | None,
) -> None:
    """Append opening-turn skill nudges (one-shot) to the message stream.

    Two independent nudges, both gated on ``has_manage_bot_skill``:
    - Correction-driven: fires when the last user message matches
      ``_CORRECTION_RE`` (the user pushed back on a prior turn).
    - Repeated-lookup: fires when ``find_repeated_lookups`` detects the bot
      has resolved the same topic N+ times within the window.
    """
    from app.config import settings

    if not has_manage_bot_skill:
        return

    if settings.SKILL_CORRECTION_NUDGE_ENABLED:
        user_text = _extract_last_user_text(messages)
        if user_text and _CORRECTION_RE.search(user_text):
            from app.config import DEFAULT_SKILL_CORRECTION_NUDGE_PROMPT
            messages.append({
                "role": "system",
                "content": DEFAULT_SKILL_CORRECTION_NUDGE_PROMPT,
            })

    if settings.SKILL_REPEATED_LOOKUP_NUDGE_ENABLED and bot.id:
        from app.agent.repeated_lookup_detection import find_repeated_lookups
        from app.config import (
            DEFAULT_SKILL_REPEATED_LOOKUP_NUDGE_PROMPT,
            SKILL_REPEATED_LOOKUP_MIN_RUNS,
            SKILL_REPEATED_LOOKUP_WINDOW_DAYS,
        )
        repeated = await find_repeated_lookups(
            bot_id=bot.id,
            correlation_id=str(correlation_id) if correlation_id else None,
            min_runs=SKILL_REPEATED_LOOKUP_MIN_RUNS,
            window_days=SKILL_REPEATED_LOOKUP_WINDOW_DAYS,
        )
        if repeated:
            topics_list = "\n".join(f"- \"{q}\"" for q in repeated)
            messages.append({
                "role": "system",
                "content": DEFAULT_SKILL_REPEATED_LOOKUP_NUDGE_PROMPT.format(
                    topics=topics_list,
                ),
            })


def _merge_activated_tools_into_param(
    activated_list: list[dict],
    tools_param: list[dict[str, Any]] | None,
    tool_choice: str | None,
    effective_allowed: set[str] | None,
    *,
    iteration: int,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Merge mid-loop ``get_tool_info`` activations into ``tools_param``.

    Also widens the ``effective_allowed`` set in place so dispatch accepts
    newly-activated names that weren't in the caller-provided authorization
    set. Returns the updated ``(tools_param, tool_choice)`` pair.
    """
    if not activated_list:
        return tools_param, tool_choice
    existing_names = (
        {(t.get("function") or {}).get("name") for t in tools_param}
        if tools_param
        else set()
    )
    new_activated = [
        t for t in activated_list
        if (t.get("function") or {}).get("name") not in existing_names
    ]
    if not new_activated:
        return tools_param, tool_choice
    tools_param = (tools_param or []) + new_activated
    tool_choice = "auto"
    if effective_allowed is not None:
        for at in new_activated:
            an = (at.get("function") or {}).get("name")
            if an:
                effective_allowed.add(an)
    logger.info(
        "Iteration %d: merged %d tools activated via get_tool_info: %s",
        iteration + 1,
        len(new_activated),
        [(t.get("function") or {}).get("name") for t in new_activated],
    )
    return tools_param, tool_choice


def _recover_tool_calls_from_text(
    accumulated_msg: Any,
    messages: list[dict],
    effective_allowed: set[str] | None,
) -> None:
    """Recover tool calls from JSON-in-text or suppressed XML blocks.

    Local models sometimes emit tool calls as serialized text alongside or
    instead of the native tool-calls channel. This helper looks for two shapes:
    1. JSON objects in ``accumulated_msg.content`` matching an allowed tool
       (replaces the whole content with the remaining non-JSON text).
    2. XML ``<invoke>`` blocks captured in ``accumulated_msg.suppressed_xml_blocks``
       during streaming (MiniMax and siblings).

    Mutates ``accumulated_msg.tool_calls`` / ``content`` and updates the
    eagerly-appended ``messages[-1]`` in place. No return value.
    """
    from app.agent.llm import extract_json_tool_calls, extract_xml_tool_calls

    if accumulated_msg.tool_calls:
        return
    json_tcs, remaining = extract_json_tool_calls(
        accumulated_msg.content or "", effective_allowed or set()
    )
    if json_tcs:
        logger.info("Recovered %d JSON tool call(s) from text content", len(json_tcs))
        accumulated_msg.tool_calls = json_tcs
        accumulated_msg.content = remaining or None
        messages[-1] = accumulated_msg.to_msg_dict()
        return

    if accumulated_msg.suppressed_xml_blocks:
        xml_tcs = extract_xml_tool_calls(
            accumulated_msg.suppressed_xml_blocks, effective_allowed or set()
        )
        if xml_tcs:
            logger.info(
                "Recovered %d XML tool call(s) from suppressed streaming content",
                len(xml_tcs),
            )
            accumulated_msg.tool_calls = xml_tcs
            messages[-1] = accumulated_msg.to_msg_dict()
