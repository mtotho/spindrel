import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from app.agent.loop_state import LoopRunContext, LoopRunState
from app.agent.message_utils import _event_with_compaction_tag
from app.agent.prompt_sizing import estimate_chars_to_tokens

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoopRunControl:
    policy: dict[str, Any]
    soft_max_llm_calls: int
    hard_max_llm_calls: int
    soft_current_prompt_tokens: int
    target_seconds: int
    run_started_at: float


@dataclass(frozen=True)
class LoopSetupDone:
    ctx: LoopRunContext
    state: LoopRunState
    effective_max_iterations: int
    max_iterations_source: str
    model: str
    effective_provider_id: str | None
    effective_model_params: dict[str, Any]
    summarize_settings: Any
    in_loop_keep_iterations: int
    tools_param: list[dict[str, Any]] | None
    tool_choice: str | None
    effective_allowed: set[str] | None
    activated_list: list[dict]
    has_manage_bot_skill: bool
    run_control: LoopRunControl


async def stream_loop_setup(
    *,
    messages: list[dict],
    bot: Any,
    session_id: Any,
    client_id: str | None,
    correlation_id: Any,
    channel_id: Any,
    compaction: bool,
    native_audio: bool,
    user_msg_index: int | None,
    turn_start: int,
    max_iterations: int | None,
    model_override: str | None,
    provider_id_override: str | None,
    context_profile_name: str | None,
    run_control_policy: dict[str, Any] | None,
    pre_selected_tools: list[dict[str, Any]] | None,
    authorized_tool_names: set[str] | None,
    settings_obj: Any,
    resolve_loop_config_fn: Any,
    resolve_loop_tools_fn: Any,
    get_local_tool_schemas_fn: Any,
    fetch_mcp_tools_fn: Any,
    get_client_tool_schemas_fn: Any,
    merge_tool_schemas_fn: Any,
    resolve_provider_for_model_fn: Any,
    inject_opening_skill_nudges_fn: Any,
    record_trace_event_fn: Any,
    safe_create_task_fn: Any,
    monotonic_fn: Any,
) -> AsyncGenerator[dict[str, Any] | LoopSetupDone, None]:
    """Resolve loop setup, emit setup-time events, and return typed run state."""
    loop_config = resolve_loop_config_fn(
        bot,
        max_iterations=max_iterations,
        model_override=model_override,
        provider_id_override=provider_id_override,
        context_profile_name=context_profile_name,
        settings_obj=settings_obj,
    )
    effective_max_iterations = loop_config.effective_max_iterations
    max_iterations_source = loop_config.max_iterations_source
    model = loop_config.model
    provider_id = loop_config.provider_id

    tool_state = await resolve_loop_tools_fn(
        bot,
        pre_selected_tools=pre_selected_tools,
        authorized_tool_names=authorized_tool_names,
        tool_surface_policy=(run_control_policy or {}).get("tool_surface"),
        required_tool_names=(run_control_policy or {}).get("required_tools"),
        compaction=compaction,
        get_local_tool_schemas_fn=get_local_tool_schemas_fn,
        fetch_mcp_tools_fn=fetch_mcp_tools_fn,
        get_client_tool_schemas_fn=get_client_tool_schemas_fn,
        merge_tool_schemas_fn=merge_tool_schemas_fn,
    )

    run_control_policy = run_control_policy or {}
    run_control = LoopRunControl(
        policy=run_control_policy,
        soft_max_llm_calls=int(run_control_policy.get("soft_max_llm_calls") or 0),
        hard_max_llm_calls=int(run_control_policy.get("hard_max_llm_calls") or 0),
        soft_current_prompt_tokens=int(run_control_policy.get("soft_current_prompt_tokens") or 0),
        target_seconds=int(run_control_policy.get("target_seconds") or 0),
        run_started_at=monotonic_fn(),
    )
    if run_control.hard_max_llm_calls > 0:
        if context_profile_name == "heartbeat" and max_iterations_source == "global":
            effective_max_iterations = run_control.hard_max_llm_calls
        else:
            effective_max_iterations = min(effective_max_iterations, run_control.hard_max_llm_calls)

    all_tools = tool_state.all_tools
    tools_param = tool_state.tools_param
    logger.debug(
        "Tools available: %s",
        [t["function"]["name"] for t in all_tools] if all_tools else "(none)",
    )

    tool_schema_chars = sum(len(json.dumps(t, default=str)) for t in (tools_param or []))
    tool_surface_event = {
        "type": "tool_surface_summary",
        "context_profile": context_profile_name or "chat",
        "tool_count": len(tools_param or []),
        "tool_schema_tokens_estimate": estimate_chars_to_tokens(tool_schema_chars),
        "tools": [(t.get("function") or {}).get("name") for t in (tools_param or [])],
        "tool_surface": run_control.policy.get("tool_surface") or "focused_escape",
        "required_tools": list(run_control.policy.get("required_tools") or []),
        "continuation_mode": run_control.policy.get("continuation_mode") or "stateless",
        "max_iterations_source": max_iterations_source,
        "effective_max_iterations": effective_max_iterations,
    }
    yield _event_with_compaction_tag(tool_surface_event, compaction)
    if correlation_id is not None:
        safe_create_task_fn(record_trace_event_fn(
            correlation_id=correlation_id,
            session_id=session_id,
            bot_id=bot.id,
            client_id=client_id,
            event_type="tool_surface_summary",
            data={k: v for k, v in tool_surface_event.items() if k != "type"},
        ))

    ctx = LoopRunContext(
        bot=bot,
        session_id=session_id,
        client_id=client_id,
        correlation_id=correlation_id,
        channel_id=channel_id,
        compaction=compaction,
        native_audio=native_audio,
        user_msg_index=user_msg_index,
        turn_start=turn_start,
    )
    state = LoopRunState(messages=messages)

    effective_provider_id = provider_id
    if effective_provider_id is None:
        effective_provider_id = resolve_provider_for_model_fn(model)

    await inject_opening_skill_nudges_fn(
        bot=bot,
        messages=messages,
        has_manage_bot_skill=tool_state.has_manage_bot_skill,
        correlation_id=correlation_id,
    )

    yield LoopSetupDone(
        ctx=ctx,
        state=state,
        effective_max_iterations=effective_max_iterations,
        max_iterations_source=max_iterations_source,
        model=model,
        effective_provider_id=effective_provider_id,
        effective_model_params=loop_config.effective_model_params,
        summarize_settings=loop_config.summarize_settings,
        in_loop_keep_iterations=loop_config.in_loop_keep_iterations,
        tools_param=tools_param,
        tool_choice=tool_state.tool_choice,
        effective_allowed=tool_state.effective_allowed,
        activated_list=tool_state.activated_list,
        has_manage_bot_skill=tool_state.has_manage_bot_skill,
        run_control=run_control,
    )
