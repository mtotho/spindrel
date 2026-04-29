import asyncio
import logging
import uuid

from app.utils import safe_create_task
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

from app.agent.bots import BotConfig
from app.agent.context import set_agent_context
from app.services import session_locks
from app.agent.context_assembly import AssemblyResult, assemble_context
from app.agent.context_pruning import prune_in_loop_tool_results, should_prune_in_loop
from app.agent.loop_dispatch import (
    SummarizeSettings,
    resolve_approval_verdict,  # noqa: F401 — re-exported
    dispatch_iteration_tool_calls,
)
from app.agent.loop_helpers import (
    _CORRECTION_RE,  # noqa: F401 — re-exported
    _EMPTY_RESPONSE_GENERIC_FALLBACK,  # noqa: F401 — re-exported
    _append_transcript_text_entry,
    _append_transcript_tool_entry,  # noqa: F401 — re-exported
    _check_prompt_budget_guard,
    _collapse_final_assistant_tool_turn,  # noqa: F401 — re-exported
    _extract_last_user_text,  # noqa: F401 — re-exported
    _extract_usage_extras,  # noqa: F401 — re-exported
    _finalize_response,  # noqa: F401 — re-exported
    _handle_loop_exit_forced_response,
    _handle_no_tool_calls_path,
    _inject_opening_skill_nudges,
    _merge_activated_tools_into_param,
    _recover_tool_calls_from_text,
    _record_fallback_event,
    _resolve_effective_provider,  # noqa: F401 — re-exported
    _resolve_loop_config,
    _resolve_loop_tools,
    _sanitize_llm_text,
    _sanitize_messages,
    _synthesize_empty_response_fallback,  # noqa: F401 — re-exported
)
from app.agent.loop_exit import schedule_loop_error_cleanup, stream_loop_exit_finalization
from app.agent.loop_llm import LoopLlmIterationDone, stream_loop_llm_iteration
from app.agent.loop_pre_llm import LoopPreLlmIterationDone, stream_loop_pre_llm_iteration
from app.agent.loop_recovery import LoopRecoveryDone, stream_loop_recovery
from app.agent.loop_setup import LoopSetupDone, stream_loop_setup
from app.agent.loop_state import LoopRunContext, LoopRunState
from app.agent.loop_stream import (
    StreamPostAssemblyDone,
    prepare_stream_setup,
    stream_context_assembly_events,
    stream_post_assembly_events,
    stream_tool_loop_events,
)
from app.agent.loop_tool_iteration import LoopToolIterationDone, stream_loop_tool_iteration
from app.agent.message_utils import (
    _event_with_compaction_tag,
    _extract_client_actions,
    _extract_transcript,
    _merge_tool_schemas,
)
from app.agent.prompt_sizing import message_prompt_chars
from app.agent.recording import _record_trace_event
from app.agent.llm import AccumulatedMessage, EmptyChoicesError, FallbackInfo, _llm_call, _llm_call_stream, _summarize_tool_result, extract_json_tool_calls, extract_xml_tool_calls, last_fallback_info, strip_malformed_tool_calls, strip_silent_tags, strip_think_tags  # noqa: F401 — re-exported
from app.agent.loop_cycle_detection import detect_cycle
from app.agent.tool_dispatch import dispatch_tool_call  # noqa: F401 — re-exported
from app.agent.tracing import _CLASSIFY_SYS_MSG, _SYS_MSG_PREFIXES, _trace  # noqa: F401 — re-exported
from app.config import settings
from app.tools.client_tools import get_client_tool_schemas, is_client_tool  # noqa: F401 — re-exported
from app.tools.mcp import fetch_mcp_tools
from app.tools.registry import get_local_tool_schemas

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    response: str = ""
    transcript: str = ""
    client_actions: list[dict] = field(default_factory=list)


async def run_agent_tool_loop(
    messages: list[dict],
    bot: BotConfig,
    session_id: uuid.UUID | None = None,
    client_id: str | None = None,
    *,
    model_override: str | None = None,
    provider_id_override: str | None = None,
    turn_start: int = 0,
    native_audio: bool = False,
    user_msg_index: int | None = None,
    compaction: bool = False,
    pre_selected_tools: list[dict[str, Any]] | None = None,
    authorized_tool_names: set[str] | None = None,
    correlation_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None,
    max_iterations: int | None = None,
    fallback_models: list[dict] | None = None,
    skip_tool_policy: bool = False,
    context_profile_name: str | None = None,
    run_control_policy: dict[str, Any] | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Single agent tool loop: LLM + tool calls until final response. Caller builds messages and sets context.
    When compaction=True, every yielded event gets "compaction": True.
    """
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
    state = LoopRunState(
        messages=messages,
    )

    try:
        import time as _time
        from app.agent.hooks import fire_hook
        from app.services.providers import resolve_provider_for_model
        from app.services.secret_registry import redact as _redact_secrets

        _setup_done: LoopSetupDone | None = None
        async for _setup_event in stream_loop_setup(
            messages=messages,
            bot=bot,
            session_id=session_id,
            client_id=client_id,
            correlation_id=correlation_id,
            channel_id=channel_id,
            compaction=compaction,
            native_audio=native_audio,
            user_msg_index=user_msg_index,
            turn_start=turn_start,
            max_iterations=max_iterations,
            model_override=model_override,
            provider_id_override=provider_id_override,
            context_profile_name=context_profile_name,
            run_control_policy=run_control_policy,
            pre_selected_tools=pre_selected_tools,
            authorized_tool_names=authorized_tool_names,
            settings_obj=settings,
            resolve_loop_config_fn=_resolve_loop_config,
            resolve_loop_tools_fn=_resolve_loop_tools,
            get_local_tool_schemas_fn=get_local_tool_schemas,
            fetch_mcp_tools_fn=fetch_mcp_tools,
            get_client_tool_schemas_fn=get_client_tool_schemas,
            merge_tool_schemas_fn=_merge_tool_schemas,
            resolve_provider_for_model_fn=resolve_provider_for_model,
            inject_opening_skill_nudges_fn=_inject_opening_skill_nudges,
            record_trace_event_fn=_record_trace_event,
            safe_create_task_fn=safe_create_task,
            monotonic_fn=_time.monotonic,
        ):
            if isinstance(_setup_event, LoopSetupDone):
                _setup_done = _setup_event
                continue
            yield _setup_event
        if _setup_done is None:
            return

        ctx = _setup_done.ctx
        state = _setup_done.state
        effective_max_iterations = _setup_done.effective_max_iterations
        model = _setup_done.model
        effective_provider_id = _setup_done.effective_provider_id
        _effective_model_params = _setup_done.effective_model_params
        summarize_settings = _setup_done.summarize_settings
        _in_loop_keep_iterations = _setup_done.in_loop_keep_iterations
        tools_param = _setup_done.tools_param
        tool_choice = _setup_done.tool_choice
        _effective_allowed = _setup_done.effective_allowed
        _activated_list = _setup_done.activated_list
        _has_manage_bot_skill = _setup_done.has_manage_bot_skill
        _run_control = _setup_done.run_control

        for iteration in range(effective_max_iterations):
            _pre_llm_done: LoopPreLlmIterationDone | None = None
            async for _pre_llm_event in stream_loop_pre_llm_iteration(
                ctx=ctx,
                state=state,
                iteration=iteration,
                model=model,
                effective_provider_id=effective_provider_id,
                tools_param=tools_param,
                tool_choice=tool_choice,
                activated_list=_activated_list,
                effective_allowed=_effective_allowed,
                context_profile_name=context_profile_name,
                run_started_at=_run_control.run_started_at,
                soft_max_llm_calls=_run_control.soft_max_llm_calls,
                soft_current_prompt_tokens=_run_control.soft_current_prompt_tokens,
                target_seconds=_run_control.target_seconds,
                in_loop_keep_iterations=_in_loop_keep_iterations,
                settings_obj=settings,
                session_lock_manager=session_locks,
                merge_activated_tools_fn=_merge_activated_tools_into_param,
                prune_in_loop_tool_results_fn=prune_in_loop_tool_results,
                should_prune_in_loop_fn=should_prune_in_loop,
                check_prompt_budget_guard_fn=_check_prompt_budget_guard,
                record_trace_event_fn=_record_trace_event,
                safe_create_task_fn=safe_create_task,
                sleep_fn=asyncio.sleep,
                monotonic_fn=_time.monotonic,
                message_prompt_chars_fn=message_prompt_chars,
                classify_sys_msg_fn=_CLASSIFY_SYS_MSG,
            ):
                if isinstance(_pre_llm_event, LoopPreLlmIterationDone):
                    _pre_llm_done = _pre_llm_event
                    continue
                yield _pre_llm_event
            if _pre_llm_done is None or _pre_llm_done.return_loop:
                return
            tools_param = _pre_llm_done.tools_param
            tool_choice = _pre_llm_done.tool_choice
            if _pre_llm_done.continue_loop:
                continue

            _llm_done: LoopLlmIterationDone | None = None
            async for _llm_event in stream_loop_llm_iteration(
                ctx=ctx,
                state=state,
                iteration=iteration,
                model=model,
                tools_param=tools_param,
                tool_choice=tool_choice,
                effective_provider_id=effective_provider_id,
                model_params=_effective_model_params,
                fallback_models=fallback_models,
                session_lock_manager=session_locks,
                llm_call_stream_fn=_llm_call_stream,
                last_fallback_info_get_fn=last_fallback_info.get,
                fire_hook_fn=fire_hook,
                record_trace_event_fn=_record_trace_event,
                record_fallback_event_fn=_record_fallback_event,
                safe_create_task_fn=safe_create_task,
                monotonic_fn=_time.monotonic,
            ):
                if isinstance(_llm_event, LoopLlmIterationDone):
                    _llm_done = _llm_event
                    continue
                yield _llm_event
                if _llm_event.get("type") == "cancelled":
                    return
            if _llm_done is None:
                return

            accumulated_msg = _llm_done.accumulated_msg
            _recovery_done: LoopRecoveryDone | None = None
            async for _recovery_event in stream_loop_recovery(
                accumulated_msg=accumulated_msg,
                ctx=ctx,
                state=state,
                iteration=iteration,
                model=model,
                tools_param=tools_param,
                effective_provider_id=effective_provider_id,
                fallback_models=fallback_models,
                effective_allowed=_effective_allowed,
                recover_tool_calls_from_text_fn=_recover_tool_calls_from_text,
                handle_no_tool_calls_path_fn=_handle_no_tool_calls_path,
                llm_call_fn=_llm_call,
            ):
                if isinstance(_recovery_event, LoopRecoveryDone):
                    _recovery_done = _recovery_event
                    continue
                yield _recovery_event
            if _recovery_done is None or _recovery_done.return_loop:
                return

            _tool_iteration_done: LoopToolIterationDone | None = None
            async for _tool_iteration_event in stream_loop_tool_iteration(
                accumulated_msg=accumulated_msg,
                ctx=ctx,
                state=state,
                iteration=iteration,
                provider_id=effective_provider_id,
                model=model,
                summarize_settings=summarize_settings,
                skip_tool_policy=skip_tool_policy,
                effective_allowed=_effective_allowed,
                settings_obj=settings,
                session_lock_manager=session_locks,
                in_loop_keep_iterations=_in_loop_keep_iterations,
                has_manage_bot_skill=_has_manage_bot_skill,
                dispatch_iteration_tool_calls_fn=dispatch_iteration_tool_calls,
                dispatch_tool_call_fn=dispatch_tool_call,
                is_client_tool_fn=is_client_tool,
                redact_fn=_redact_secrets,
                prune_in_loop_tool_results_fn=prune_in_loop_tool_results,
                should_prune_in_loop_fn=should_prune_in_loop,
                detect_cycle_fn=detect_cycle,
            ):
                if isinstance(_tool_iteration_event, LoopToolIterationDone):
                    _tool_iteration_done = _tool_iteration_event
                    continue
                yield _tool_iteration_event
            if _tool_iteration_done is None or _tool_iteration_done.cancelled:
                return
            if _tool_iteration_done.break_loop:
                break

        # --- Post-loop: forced response (max iterations or cycle break) ---
        async for _evt in stream_loop_exit_finalization(
            ctx=ctx,
            state=state,
            iteration=iteration,
            effective_max_iterations=effective_max_iterations,
            tools_param=tools_param,
            model=model,
            effective_provider_id=effective_provider_id,
            fallback_models=fallback_models,
            llm_call_fn=_llm_call,
            handle_loop_exit_forced_response_fn=_handle_loop_exit_forced_response,
        ):
            yield _evt
        if state.terminated:
            return

    except Exception as exc:
        schedule_loop_error_cleanup(
            exc=exc,
            ctx=ctx,
            state=state,
            record_trace_event_fn=_record_trace_event,
            safe_create_task_fn=safe_create_task,
        )
        raise


async def run_stream(
    messages: list[dict],
    bot: BotConfig,
    user_message: str,
    session_id: uuid.UUID | None = None,
    client_id: str | None = None,
    audio_data: str | None = None,
    audio_format: str | None = None,
    attachments: list[dict] | None = None,
    correlation_id: uuid.UUID | None = None,
    dispatch_type: str | None = None,
    dispatch_config: dict | None = None,
    channel_id: uuid.UUID | None = None,
    model_override: str | None = None,
    provider_id_override: str | None = None,
    fallback_models: list[dict] | None = None,
    injected_tools: list[dict] | None = None,
    system_preamble: str | None = None,
    skip_tool_policy: bool = False,
    task_mode: bool = False,
    skip_skill_inject: bool = False,
    context_profile_name: str | None = None,
    run_control_policy: dict[str, Any] | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Core agent loop as an async generator that yields status events.

    Events:
      {"type": "tool_start", "tool": "<name>", "args": "<json>"}
      {"type": "tool_result", "tool": "<name>"}
      {"type": "assistant_text", "text": "..."}   (intermediate text alongside tool calls)
      {"type": "memory_context", "count": <int>}
      {"type": "transcript", "text": "..."}
      {"type": "delegation_post", "bot_id": "...", "text": "...", "reply_in_thread": bool}
      {"type": "response", "text": "...", "client_actions": [...]}

    delegation_post events are emitted just before the response event so that the Slack
    client can post child-bot messages first (giving them an earlier timestamp), then post
    the parent's response as a new message — ensuring correct visual ordering.
    """
    setup = await prepare_stream_setup(
        messages=messages,
        bot=bot,
        session_id=session_id,
        client_id=client_id,
        correlation_id=correlation_id,
        dispatch_type=dispatch_type,
        dispatch_config=dispatch_config,
        channel_id=channel_id,
        injected_tools=injected_tools,
        audio_data=audio_data,
        model_override=model_override,
        provider_id_override=provider_id_override,
        context_profile_name=context_profile_name,
        settings_obj=settings,
        logger=logger,
        set_agent_context_fn=set_agent_context,
        resolve_effective_provider_fn=_resolve_effective_provider,
    )
    assembly_result = AssemblyResult()
    async for event in stream_context_assembly_events(
        assemble_context_fn=assemble_context,
        messages=messages,
        bot=bot,
        user_message=user_message,
        session_id=session_id,
        client_id=client_id,
        correlation_id=correlation_id,
        channel_id=channel_id,
        audio_data=audio_data,
        audio_format=audio_format,
        attachments=attachments,
        native_audio=setup.native_audio,
        assembly_result=assembly_result,
        system_preamble=system_preamble,
        budget=setup.budget,
        task_mode=task_mode,
        skip_skill_inject=skip_skill_inject,
        context_profile_name=setup.context_profile_name,
        model_override=setup.model_override,
        provider_id_override=setup.provider_id_override,
        run_control_policy=run_control_policy,
    ):
        yield event

    post_assembly: StreamPostAssemblyDone | None = None
    async for event in stream_post_assembly_events(
        messages=messages,
        bot=bot,
        user_message=user_message,
        session_id=session_id,
        client_id=client_id,
        correlation_id=correlation_id,
        model_override=setup.model_override,
        provider_id_override=setup.provider_id_override,
        fallback_models=fallback_models,
        assembly_result=assembly_result,
        budget=setup.budget,
        context_profile_name=setup.context_profile_name,
        settings_obj=settings,
        logger=logger,
        resolve_effective_provider_fn=_resolve_effective_provider,
        record_trace_event_fn=_record_trace_event,
        safe_create_task_fn=safe_create_task,
    ):
        if isinstance(event, StreamPostAssemblyDone):
            post_assembly = event
            continue
        yield event
    if post_assembly is None or post_assembly.return_stream:
        return

    async for event in stream_tool_loop_events(
        run_agent_tool_loop_fn=run_agent_tool_loop,
        messages=messages,
        bot=post_assembly.bot,
        session_id=session_id,
        client_id=client_id,
        model_override=post_assembly.model_override,
        provider_id_override=post_assembly.provider_id_override,
        turn_start=setup.turn_start,
        native_audio=setup.native_audio,
        user_msg_index=post_assembly.user_msg_index,
        pre_selected_tools=post_assembly.pre_selected_tools,
        authorized_tool_names=post_assembly.authorized_tool_names,
        correlation_id=correlation_id,
        channel_id=channel_id,
        max_iterations=post_assembly.max_iterations,
        fallback_models=post_assembly.fallback_models,
        skip_tool_policy=skip_tool_policy,
        context_profile_name=setup.context_profile_name,
        run_control_policy=run_control_policy,
        is_outermost_stream=setup.is_outermost_stream,
        delegation_posts=setup.delegation_posts,
    ):
        yield event


async def run(
    messages: list[dict],
    bot: BotConfig,
    user_message: str,
    session_id: uuid.UUID | None = None,
    client_id: str | None = None,
    audio_data: str | None = None,
    audio_format: str | None = None,
    attachments: list[dict] | None = None,
    correlation_id: uuid.UUID | None = None,
    dispatch_type: str | None = None,
    dispatch_config: dict | None = None,
    channel_id: uuid.UUID | None = None,
    model_override: str | None = None,
    provider_id_override: str | None = None,
    fallback_models: list[dict] | None = None,
    injected_tools: list[dict] | None = None,
    system_preamble: str | None = None,
    skip_tool_policy: bool = False,
    task_mode: bool = False,
    skip_skill_inject: bool = False,
    context_profile_name: str | None = None,
    run_control_policy: dict[str, Any] | None = None,
) -> RunResult:
    """Non-streaming wrapper: runs the agent loop and returns the final result."""
    result = RunResult()
    _intermediate_texts: list[str] = []
    async for event in run_stream(
        messages, bot, user_message,
        session_id=session_id, client_id=client_id,
        audio_data=audio_data, audio_format=audio_format,
        attachments=attachments,
        correlation_id=correlation_id,
        dispatch_type=dispatch_type,
        dispatch_config=dispatch_config,
        channel_id=channel_id,
        model_override=model_override,
        provider_id_override=provider_id_override,
        fallback_models=fallback_models,
        injected_tools=injected_tools,
        system_preamble=system_preamble,
        skip_tool_policy=skip_tool_policy,
        task_mode=task_mode,
        skip_skill_inject=skip_skill_inject,
        context_profile_name=context_profile_name,
        run_control_policy=run_control_policy,
    ):
        if event["type"] == "assistant_text":
            _intermediate_texts.append(event["text"])
        elif event["type"] == "response":
            # If the final response is empty but intermediate text was produced,
            # combine the intermediate messages as the result.
            final_text = event["text"]
            if not (final_text or "").strip() and _intermediate_texts:
                result.response = "\n\n".join(_intermediate_texts)
            else:
                result.response = final_text
            result.client_actions = event.get("client_actions", [])
        elif event["type"] == "transcript":
            result.transcript = event["text"]
        elif event["type"] == "delegation_post" and channel_id is not None:
            # Non-streaming context (task worker): publish child bot's
            # message onto the channel-events bus. Renderers consume the
            # NEW_MESSAGE event and post to the integration.
            from app.services.delegation import delegation_service as _ds
            try:
                await _ds.post_child_response(
                    channel_id=channel_id,
                    text=event.get("text", ""),
                    bot_id=event.get("bot_id") or "",
                    reply_in_thread=event.get("reply_in_thread", False),
                )
            except Exception:
                logger.warning("run(): delegation_post failed for bot %s", event.get("bot_id"))
    return result
