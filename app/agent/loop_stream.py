"""High-level run_stream orchestration stages."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from typing import Any

from app.agent.bots import BotConfig
from app.agent.context_assembly import AssemblyResult


@dataclass
class StreamSetup:
    is_outermost_stream: bool
    delegation_posts: list
    native_audio: bool
    turn_start: int
    context_profile_name: str
    budget: Any
    model_override: str | None
    provider_id_override: str | None


@dataclass
class StreamPostAssemblyDone:
    bot: BotConfig
    model_override: str | None
    provider_id_override: str | None
    max_iterations: int | None
    pre_selected_tools: list[dict[str, Any]] | None
    authorized_tool_names: set[str] | None
    user_msg_index: int | None
    fallback_models: list[dict]
    return_stream: bool = False


async def prepare_stream_setup(
    *,
    messages: list[dict],
    bot: BotConfig,
    session_id: uuid.UUID | None,
    client_id: str | None,
    correlation_id: uuid.UUID | None,
    dispatch_type: str | None,
    dispatch_config: dict | None,
    channel_id: uuid.UUID | None,
    injected_tools: list[dict] | None,
    audio_data: str | None,
    model_override: str | None,
    provider_id_override: str | None,
    context_profile_name: str | None,
    settings_obj: Any,
    logger: logging.Logger,
    set_agent_context_fn: Callable[..., None],
    resolve_effective_provider_fn: Callable[[str | None, str | None, str | None], str | None],
) -> StreamSetup:
    from app.agent.embeddings import clear_embed_cache
    from app.agent.context import (
        current_effort_override,
        current_injected_tools,
        current_pending_delegation_posts,
        current_run_origin,
        current_turn_responded_bots,
        task_creation_count,
    )
    from app.agent.context_profiles import resolve_context_profile

    clear_embed_cache()
    task_creation_count.set(0)

    is_outermost_stream = current_pending_delegation_posts.get() is None
    delegation_posts: list = []
    if is_outermost_stream:
        current_pending_delegation_posts.set(delegation_posts)
        current_turn_responded_bots.set({bot.id})
    else:
        delegation_posts = current_pending_delegation_posts.get()  # type: ignore[assignment]

    set_agent_context_fn(
        session_id=session_id,
        client_id=client_id,
        bot_id=bot.id,
        correlation_id=correlation_id,
        channel_id=channel_id,
        memory_cross_channel=None,
        memory_cross_client=None,
        memory_cross_bot=None,
        memory_similarity_threshold=None,
        dispatch_type=dispatch_type,
        dispatch_config=dispatch_config,
    )
    current_injected_tools.set(injected_tools)

    if current_effort_override.get() is None and channel_id is not None:
        try:
            from app.db.engine import async_session as effort_session_factory
            from app.db.models import Channel as EffortChannel

            async with effort_session_factory() as effort_db:
                channel = await effort_db.get(EffortChannel, channel_id)
                if channel is not None:
                    override = (channel.config or {}).get("effort_override")
                    if override in ("off", "low", "medium", "high"):
                        current_effort_override.set(override)
        except Exception:
            logger.debug("effort override lookup failed", exc_info=True)

    if model_override is None and channel_id is not None:
        try:
            from app.db.engine import async_session as model_session_factory
            from app.db.models import Channel as ModelChannel

            async with model_session_factory() as model_db:
                channel = await model_db.get(ModelChannel, channel_id)
                if channel is not None and channel.model_override:
                    model_override = channel.model_override
                    provider_id_override = provider_id_override or getattr(
                        channel,
                        "model_provider_id_override",
                        None,
                    )
        except Exception:
            logger.debug("channel model override lookup failed", exc_info=True)

    resolved_context_profile = context_profile_name
    if resolved_context_profile is None:
        origin = current_run_origin.get(None)
        session = None
        if session_id is not None:
            try:
                from app.db.engine import async_session
                from app.db.models import Session

                async with async_session() as profile_db:
                    session = await profile_db.get(Session, session_id)
            except Exception:
                logger.debug("context profile session lookup failed", exc_info=True)
        resolved_context_profile = resolve_context_profile(
            session=session,
            origin=origin,
        ).name

    budget = None
    if settings_obj.CONTEXT_BUDGET_ENABLED:
        from app.agent.context_budget import ContextBudget, get_model_context_window

        effective_model = model_override or bot.model
        effective_provider = resolve_effective_provider_fn(
            model_override,
            provider_id_override,
            bot.model_provider_id,
        )
        window = get_model_context_window(effective_model, effective_provider)
        budget = ContextBudget(
            total_tokens=window,
            reserve_tokens=int(window * settings_obj.CONTEXT_BUDGET_RESERVE_RATIO),
        )

    return StreamSetup(
        is_outermost_stream=is_outermost_stream,
        delegation_posts=delegation_posts,
        native_audio=audio_data is not None,
        turn_start=len(messages),
        context_profile_name=resolved_context_profile,
        budget=budget,
        model_override=model_override,
        provider_id_override=provider_id_override,
    )


async def stream_context_assembly_events(
    *,
    assemble_context_fn: Callable[..., AsyncGenerator[dict[str, Any], None]],
    messages: list[dict],
    bot: BotConfig,
    user_message: str,
    session_id: uuid.UUID | None,
    client_id: str | None,
    correlation_id: uuid.UUID | None,
    channel_id: uuid.UUID | None,
    audio_data: str | None,
    audio_format: str | None,
    attachments: list[dict] | None,
    native_audio: bool,
    assembly_result: AssemblyResult,
    system_preamble: str | None,
    budget: Any,
    task_mode: bool,
    skip_skill_inject: bool,
    context_profile_name: str,
    model_override: str | None,
    provider_id_override: str | None,
    run_control_policy: dict[str, Any] | None,
) -> AsyncGenerator[dict[str, Any], None]:
    async for event in assemble_context_fn(
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
        native_audio=native_audio,
        result=assembly_result,
        system_preamble=system_preamble,
        budget=budget,
        task_mode=task_mode,
        skip_skill_inject=skip_skill_inject,
        context_profile_name=context_profile_name,
        model_override=model_override,
        provider_id_override=provider_id_override,
        tool_surface_policy=(run_control_policy or {}).get("tool_surface"),
        required_tool_names=(run_control_policy or {}).get("required_tools"),
    ):
        yield event


def stream_budget_events(
    *,
    budget: Any,
    assembly_result: AssemblyResult,
    context_profile_name: str,
    logger: logging.Logger,
) -> list[dict[str, Any]]:
    if budget is None:
        return []
    if assembly_result.pre_selected_tools:
        from app.agent.context_budget import estimate_tokens

        tool_schema_chars = sum(len(json.dumps(tool)) for tool in assembly_result.pre_selected_tools)
        budget.consume("tool_schemas", estimate_tokens("x" * tool_schema_chars))
        logger.debug("Budget after assembly: %s", budget.to_dict())

    budget_dict = budget.to_dict()
    policy = assembly_result.context_policy or {}
    return [{
        "type": "context_budget",
        "utilization": round(budget.utilization, 3),
        "total_tokens": budget.total_tokens,
        "consumed_tokens": budget.consumed_tokens,
        "remaining_tokens": budget.remaining,
        "available_budget": budget_dict["available_budget"],
        "base_tokens": budget_dict["base_tokens"],
        "live_history_tokens": budget_dict["live_history_tokens"],
        "live_history_utilization": budget_dict["live_history_utilization"],
        "static_injection_tokens": budget_dict["static_injection_tokens"],
        "tool_schema_tokens": budget_dict["tool_schema_tokens"],
        "context_profile": context_profile_name,
        "context_origin": assembly_result.context_origin,
        "live_history_turns": policy.get("live_history_turns"),
        "mandatory_static_injections": policy.get("mandatory_static_injections") or [],
        "optional_static_injections": policy.get("optional_static_injections") or [],
    }]


async def stream_rerank_event(
    *,
    messages: list[dict],
    user_message: str,
    bot: BotConfig,
    session_id: uuid.UUID | None,
    client_id: str | None,
    correlation_id: uuid.UUID | None,
    model_override: str | None,
    provider_id_override: str | None,
    settings_obj: Any,
    logger: logging.Logger,
    resolve_effective_provider_fn: Callable[[str | None, str | None, str | None], str | None],
    record_trace_event_fn: Callable[..., Any],
    safe_create_task_fn: Callable[[Any], Any],
) -> dict[str, Any] | None:
    from app.services.reranking import rerank_rag_context

    rerank_result = await rerank_rag_context(
        messages,
        user_message,
        provider_id=settings_obj.RAG_RERANK_MODEL_PROVIDER_ID
        or resolve_effective_provider_fn(model_override, provider_id_override, bot.model_provider_id),
    )
    if rerank_result is None:
        return None
    logger.info(
        "RAG re-rank: %d→%d chunks, %d→%d chars",
        rerank_result.original_chunks,
        rerank_result.kept_chunks,
        rerank_result.original_chars,
        rerank_result.kept_chars,
    )
    if correlation_id is not None:
        safe_create_task_fn(record_trace_event_fn(
            correlation_id=correlation_id,
            session_id=session_id,
            bot_id=bot.id,
            client_id=client_id,
            event_type="rag_rerank",
            data={
                "original_chunks": rerank_result.original_chunks,
                "kept_chunks": rerank_result.kept_chunks,
                "original_chars": rerank_result.original_chars,
                "kept_chars": rerank_result.kept_chars,
            },
        ))
    return {
        "type": "rag_rerank",
        "original_chunks": rerank_result.original_chunks,
        "kept_chunks": rerank_result.kept_chunks,
        "original_chars": rerank_result.original_chars,
        "kept_chars": rerank_result.kept_chars,
    }


def apply_auto_injected_skills(
    *,
    messages: list[dict],
    assembly_result: AssemblyResult,
    logger: logging.Logger,
) -> None:
    if not assembly_result.auto_inject_skills:
        return

    from app.agent.context import current_skills_in_context

    resident_skills = list(current_skills_in_context.get() or [])
    for skill in assembly_result.auto_inject_skills:
        skill_id = skill["skill_id"]
        tool_call_id = f"auto_inject_{hashlib.md5(skill_id.encode()).hexdigest()[:12]}"
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": "get_skill",
                    "arguments": json.dumps({"skill_id": skill_id}),
                },
            }],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": skill["content"],
            "_no_prune": True,
            "_auto_inject": True,
        })
        if not any(
            isinstance(entry, dict) and entry.get("skill_id") == skill_id
            for entry in resident_skills
        ):
            resident_skills.insert(0, {
                "skill_id": skill_id,
                "skill_name": skill["content"].splitlines()[0].removeprefix("# ").strip() or skill_id,
                "source": "auto_injected",
                "messages_ago": 0,
            })
    current_skills_in_context.set(resident_skills)
    logger.info(
        "Auto-injected %d skill(s) as synthetic get_skill() pairs: %s",
        len(assembly_result.auto_inject_skills),
        [skill["skill_id"] for skill in assembly_result.auto_inject_skills],
    )


async def stream_post_assembly_events(
    *,
    messages: list[dict],
    bot: BotConfig,
    user_message: str,
    session_id: uuid.UUID | None,
    client_id: str | None,
    correlation_id: uuid.UUID | None,
    model_override: str | None,
    provider_id_override: str | None,
    fallback_models: list[dict] | None,
    assembly_result: AssemblyResult,
    budget: Any,
    context_profile_name: str,
    settings_obj: Any,
    logger: logging.Logger,
    resolve_effective_provider_fn: Callable[[str | None, str | None, str | None], str | None],
    record_trace_event_fn: Callable[..., Any],
    safe_create_task_fn: Callable[[Any], Any],
) -> AsyncGenerator[dict[str, Any] | StreamPostAssemblyDone, None]:
    budget_events = stream_budget_events(
        budget=budget,
        assembly_result=assembly_result,
        context_profile_name=context_profile_name,
        logger=logger,
    )
    for event in budget_events:
        yield event
        if event.get("type") == "context_budget" and correlation_id is not None:
            safe_create_task_fn(record_trace_event_fn(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot.id,
                client_id=client_id,
                event_type="context_budget",
                data={k: v for k, v in event.items() if k != "type"},
            ))

    if assembly_result.skills_in_context:
        yield {"type": "active_skills", "skills": assembly_result.skills_in_context}

    rerank_event = await stream_rerank_event(
        messages=messages,
        user_message=user_message,
        bot=bot,
        session_id=session_id,
        client_id=client_id,
        correlation_id=correlation_id,
        model_override=model_override,
        provider_id_override=provider_id_override,
        settings_obj=settings_obj,
        logger=logger,
        resolve_effective_provider_fn=resolve_effective_provider_fn,
        record_trace_event_fn=record_trace_event_fn,
        safe_create_task_fn=safe_create_task_fn,
    )
    if rerank_event is not None:
        yield rerank_event

    apply_auto_injected_skills(
        messages=messages,
        assembly_result=assembly_result,
        logger=logger,
    )

    if model_override is None and assembly_result.channel_model_override:
        model_override = assembly_result.channel_model_override
        provider_id_override = provider_id_override or assembly_result.channel_provider_id_override

    from app.agent.context import (
        current_channel_model_tier_overrides,
        current_model_override,
        current_provider_id_override,
    )

    current_model_override.set(model_override)
    current_provider_id_override.set(provider_id_override)
    current_channel_model_tier_overrides.set(assembly_result.channel_model_tier_overrides)

    if assembly_result.effective_local_tools and list(bot.local_tools) != assembly_result.effective_local_tools:
        from dataclasses import replace as dc_replace

        bot = dc_replace(bot, local_tools=assembly_result.effective_local_tools)

    resolved_fallback_models = (
        fallback_models
        if fallback_models is not None
        else (assembly_result.channel_fallback_models or bot.fallback_models or [])
    )

    from app.services.usage_limits import UsageLimitExceeded, check_usage_limits

    try:
        await check_usage_limits(model_override or bot.model, bot.id)
    except UsageLimitExceeded as exc:
        yield {"type": "error", "code": "usage_limit_exceeded", "message": str(exc)}
        yield StreamPostAssemblyDone(
            bot=bot,
            model_override=model_override,
            provider_id_override=provider_id_override,
            max_iterations=assembly_result.channel_max_iterations,
            pre_selected_tools=assembly_result.pre_selected_tools,
            authorized_tool_names=assembly_result.authorized_tool_names,
            user_msg_index=assembly_result.user_msg_index,
            fallback_models=resolved_fallback_models,
            return_stream=True,
        )
        return

    yield StreamPostAssemblyDone(
        bot=bot,
        model_override=model_override,
        provider_id_override=provider_id_override,
        max_iterations=assembly_result.channel_max_iterations,
        pre_selected_tools=assembly_result.pre_selected_tools,
        authorized_tool_names=assembly_result.authorized_tool_names,
        user_msg_index=assembly_result.user_msg_index,
        fallback_models=resolved_fallback_models,
    )


async def stream_tool_loop_events(
    *,
    run_agent_tool_loop_fn: Callable[..., AsyncGenerator[dict[str, Any], None]],
    messages: list[dict],
    bot: BotConfig,
    session_id: uuid.UUID | None,
    client_id: str | None,
    model_override: str | None,
    provider_id_override: str | None,
    turn_start: int,
    native_audio: bool,
    user_msg_index: int | None,
    pre_selected_tools: list[dict[str, Any]] | None,
    authorized_tool_names: set[str] | None,
    correlation_id: uuid.UUID | None,
    channel_id: uuid.UUID | None,
    max_iterations: int | None,
    fallback_models: list[dict],
    skip_tool_policy: bool,
    context_profile_name: str,
    run_control_policy: dict[str, Any] | None,
    is_outermost_stream: bool,
    delegation_posts: list,
) -> AsyncGenerator[dict[str, Any], None]:
    loop_kwargs = {
        "session_id": session_id,
        "client_id": client_id,
        "model_override": model_override,
        "provider_id_override": provider_id_override,
        "turn_start": turn_start,
        "native_audio": native_audio,
        "user_msg_index": user_msg_index,
        "pre_selected_tools": pre_selected_tools,
        "authorized_tool_names": authorized_tool_names,
        "correlation_id": correlation_id,
        "channel_id": channel_id,
        "max_iterations": max_iterations,
        "fallback_models": fallback_models,
        "skip_tool_policy": skip_tool_policy,
        "context_profile_name": context_profile_name,
        "run_control_policy": run_control_policy,
    }
    if not is_outermost_stream:
        async for event in run_agent_tool_loop_fn(messages, bot, **loop_kwargs):
            yield event
        return

    last_response: dict | None = None
    async for event in run_agent_tool_loop_fn(messages, bot, **loop_kwargs):
        if event.get("type") == "response":
            last_response = event
        else:
            yield event

    for post in delegation_posts:
        yield {
            "type": "delegation_post",
            "bot_id": post["bot_id"],
            "text": post["text"],
            "reply_in_thread": post.get("reply_in_thread", False),
            "client_actions": post.get("client_actions", []),
        }

    from app.agent.context import task_creation_count

    pending = task_creation_count.get(0)
    if pending > 0:
        yield {"type": "pending_tasks", "count": pending}
    if last_response is not None:
        yield last_response
