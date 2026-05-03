"""Host orchestration for general task execution."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import openai

from app.agent.bots import BotConfig
from app.db.models import Channel, Session, Task
from app.domain.errors import NotFoundError
from app.services.agent_harnesses.turn_request import HarnessTurnRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TaskRunHostDeps:
    """Patchable dependencies supplied by app.agent.tasks at run time."""

    async_session: Callable[[], Any]
    settings: Any
    session_locks: Any
    get_bot: Callable[[str], BotConfig]
    resolve_task_session_target: Callable[[Any, Task], Awaitable[tuple[Any, Channel | None]]]
    is_pipeline_child: Callable[[Task], bool]
    resolve_sub_session_bus_channel: Callable[[Task], Awaitable[uuid.UUID | None]]
    dispatch_to_specialized_runner: Callable[[Task], Awaitable[bool]]
    publish_turn_ended: Callable[..., Awaitable[None]]
    fire_task_complete: Callable[[Task, str], Awaitable[None]]
    record_timeout_event: Callable[[Task, uuid.UUID | None, str], Awaitable[None]]
    resolve_task_timeout: Callable[[Task, Channel | None], int]
    mark_task_failed_in_db: Callable[..., Awaitable[None]]
    publish_turn_ended_safe: Callable[..., Awaitable[None]]
    mark_heartbeat_task_started: Callable[[Task, uuid.UUID | None], Awaitable[None]]
    finalize_heartbeat_task_run: Callable[..., Awaitable[None]]
    heartbeat_execution_meta: Callable[[Task], dict]


@dataclass
class _PreparedTaskRun:
    task: Task
    bot: BotConfig
    session_id: uuid.UUID
    messages: list[dict]
    messages_start: int
    task_prompt: str
    correlation_id: uuid.UUID
    context_profile_name: str
    task_timeout: int
    ecfg: dict
    model_override: str | None
    provider_id_override: str | None
    fallback_models: list | None
    skip_tool_policy: bool
    system_preamble: str | None
    injected_tools: list[dict] | None
    is_scheduled: bool
    recurrence: str | None




_ISSUE_REPORTING_PREAMBLE = """\
[Issue reporting]
This run may report durable issues with the report_issue tool. Use it only when
you found a real blocker, missing permission, recurring system/tool failure, or
setup problem that needs a human decision. Do not report ordinary task progress,
temporary noise, or issues you can fix directly. Keep reports concise and
actionable: what happened, why it matters, and the next useful action.
If required tools are missing, make at most one report_issue call with
category="missing_permission", a stable dedupe key, and a concrete
suggested_action. After that, stop using tools and produce a concise final
response.
"""


def _heartbeat_should_post(task: Task, deps: TaskRunHostDeps) -> bool:
    return deps.heartbeat_execution_meta(task).get("dispatch_results", True) is not False


def _task_run_control_policy(ecfg: dict, *, task_type: str | None = None) -> dict | None:
    from app.services.task_run_policy import resolve_task_run_policy

    effective_task_type = task_type or str(ecfg.get("_task_type") or "")
    policy = dict((resolve_task_run_policy(effective_task_type).run_control_policy or {}))
    policy.update(dict(ecfg.get("run_control_policy") or {}))
    configured_tools = [str(name) for name in (ecfg.get("tools") or []) if name]
    if configured_tools:
        existing = [str(name) for name in (policy.get("required_tools") or []) if name]
        policy["required_tools"] = list(dict.fromkeys([*existing, *configured_tools]))
    elif ecfg.get("heartbeat") and bool(ecfg.get("allow_issue_reporting")):
        hard_cap = int(policy.get("hard_max_llm_calls") or 0)
        soft_cap = int(policy.get("soft_max_llm_calls") or 0)
        policy["hard_max_llm_calls"] = min(hard_cap, 2) if hard_cap > 0 else 2
        policy["soft_max_llm_calls"] = min(soft_cap, 1) if soft_cap > 0 else 1
    return policy or None


def _task_context_profile_name(task: Task, channel: Channel | None) -> str:
    from app.agent.context_profiles import resolve_native_chat_profile
    from app.services.task_run_policy import resolve_task_run_policy

    task_policy = resolve_task_run_policy(task.task_type)
    if task_policy.context_profile:
        return task_policy.context_profile
    if task.task_type == "api":
        return resolve_native_chat_profile(channel=channel).name
    return "task_recent"


def _history_turns_for_task(task: Task, profile_name: str, deps: TaskRunHostDeps) -> int:
    from app.agent.context_profiles import get_context_profile

    ecfg_hist = task.execution_config or {}
    hist_mode = ecfg_hist.get("history_mode")
    if hist_mode == "none":
        return 0
    if hist_mode == "recent":
        try:
            return int(ecfg_hist.get("history_recent_count") or 10)
        except (TypeError, ValueError):
            return 10
    if hist_mode == "full":
        return -1
    profile = get_context_profile(profile_name)
    if profile.live_history_turns is not None:
        return profile.live_history_turns
    return deps.settings.HEARTBEAT_MAX_HISTORY_TURNS


def _metadata_context_visibility(task_type: str | None, *, is_scheduled: bool = False) -> str:
    if task_type in {"heartbeat", "memory_hygiene", "skill_review"}:
        return "background"
    if is_scheduled:
        return "background"
    return "chat"


async def _resolve_task_bot(bot_id: str, deps: TaskRunHostDeps) -> BotConfig:
    """Resolve a bot for a task run, refreshing the runtime registry once.

    Runtime-created bots are committed to the database before tasks can target
    them, but long-lived task workers may still hold a stale in-memory bot
    registry. A single reload keeps task execution in sync without hiding a
    genuinely invalid bot id.
    """
    try:
        return deps.get_bot(bot_id)
    except Exception as exc:
        if not isinstance(exc, NotFoundError) and "Unknown bot" not in str(exc):
            raise
        from app.agent.bots import reload_bots

        await reload_bots()
        return deps.get_bot(bot_id)


async def _prepare_task_run(
    task: Task,
    task_channel: Channel | None,
    deps: TaskRunHostDeps,
) -> _PreparedTaskRun:
    """Resolve the task's runtime state before the harness/agent invocation."""
    _ecfg_override = (task.execution_config or {}).get("system_prompt_override")
    if _ecfg_override is not None:
        from app.agent.context import current_system_prompt_override
        current_system_prompt_override.set(_ecfg_override)

    from app.agent.persona import get_persona
    from app.services.sessions import _effective_system_prompt, load_or_create

    bot = await _resolve_task_bot(task.bot_id, deps)
    ecfg = task.execution_config or task.callback_config or {}
    model_override = ecfg.get("model_override") or None
    provider_id_override = ecfg.get("model_provider_id_override") or None

    async with deps.async_session() as db:
        # Detect cross-bot delegation: task.session_id belongs to a different bot.
        # In that case, create a proper child delegation session instead of reusing the parent.
        parent_for_delegation = None
        delegation_depth = 1
        delegation_root_id = None

        if task.session_id is not None:
            orig_session = await db.get(Session, task.session_id)
            if orig_session is not None and orig_session.bot_id != task.bot_id:
                parent_for_delegation = task.session_id
                delegation_depth = (orig_session.depth or 0) + 1
                delegation_root_id = orig_session.root_session_id or orig_session.id

        if parent_for_delegation is not None:
            child_session_id = uuid.uuid4()
            child_session = Session(
                id=child_session_id,
                client_id=task.client_id or "task",
                bot_id=task.bot_id,
                channel_id=task.channel_id,
                parent_session_id=parent_for_delegation,
                root_session_id=delegation_root_id,
                depth=delegation_depth,
                source_task_id=task.id,
            )
            db.add(child_session)
            await db.commit()
            task_channel = await db.get(Channel, task.channel_id) if task.channel_id else None
            messages = [{
                "role": "system",
                "content": _effective_system_prompt(
                    bot,
                    channel=task_channel,
                    model_override=model_override,
                    provider_id_override=provider_id_override,
                ),
            }]
            if bot.persona:
                persona_layer = await get_persona(bot.id, workspace_id=bot.shared_workspace_id)
                if persona_layer:
                    messages.append({"role": "system", "content": f"[PERSONA]\n{persona_layer}"})
            session_id = child_session_id
            logger.info(
                "Task %s: cross-bot delegation -> child session %s (depth=%d, root=%s)",
                task.id, child_session_id, delegation_depth, delegation_root_id,
            )
        else:
            initial_profile = (
                "task_none"
                if (task.execution_config or {}).get("history_mode") == "none"
                else _task_context_profile_name(task, task_channel)
            )
            session_id, messages = await load_or_create(
                db,
                task.session_id,
                task.client_id or "task",
                task.bot_id,
                channel_id=task.channel_id,
                context_profile_name=initial_profile,
                model_override=model_override,
                provider_id_override=provider_id_override,
            )

    from app.services.heartbeat import _trim_history_for_task
    context_profile_name = _task_context_profile_name(task, task_channel)
    hist_turns = _history_turns_for_task(task, context_profile_name, deps)
    messages = _trim_history_for_task(messages, hist_turns)
    from app.services.task_run_policy import resolve_task_run_policy
    if hist_turns == 0 and not resolve_task_run_policy(task.task_type).context_profile:
        context_profile_name = "task_none"

    correlation_id = uuid.uuid4()
    task.correlation_id = correlation_id
    async with deps.async_session() as corr_db:
        t = await corr_db.get(Task, task.id)
        if t:
            t.correlation_id = correlation_id
            await corr_db.commit()
    messages_start = len(messages)

    from app.services.prompt_resolution import resolve_prompt
    async with deps.async_session() as resolve_db:
        task_prompt = await resolve_prompt(
            workspace_id=str(task.workspace_id) if task.workspace_id else None,
            workspace_file_path=task.workspace_file_path,
            template_id=str(task.prompt_template_id) if task.prompt_template_id else None,
            inline_prompt=task.prompt,
            db=resolve_db,
        )

    is_scheduled = False
    recurrence: str | None = None
    if task.parent_task_id:
        async with deps.async_session() as preamble_db:
            parent = await preamble_db.get(Task, task.parent_task_id)
            if parent and parent.recurrence:
                is_scheduled = True
                recurrence = parent.recurrence
    if is_scheduled:
        preamble_lines = [f"[SCHEDULED TASK — recurring {recurrence}]"]
        if task.title:
            preamble_lines.append(f"Title: {task.title}")
        preamble_lines.append(
            "You are executing a scheduled task, not responding to a live user. "
            "Execute the instructions below directly."
        )
        preamble_lines.append("---")
        task_prompt = "\n".join(preamble_lines) + "\n" + task_prompt

    fallback_models = ecfg.get("fallback_models") or None
    skip_tool_policy = bool(ecfg.get("skip_tool_approval", False))

    allowed_secrets = ecfg.get("allowed_secrets")
    if allowed_secrets is not None:
        from app.agent.context import current_allowed_secrets
        current_allowed_secrets.set(allowed_secrets)

    system_preamble = ecfg.get("system_preamble") or None
    ecfg_skills = ecfg.get("skills") or None
    ecfg_tool_names = ecfg.get("tools") or None

    if ecfg_skills:
        from app.agent.context import set_ephemeral_skills
        set_ephemeral_skills(ecfg_skills)

    injected_tools: list[dict] | None = None
    if ecfg_tool_names:
        from app.tools.registry import get_local_tool_schemas
        injected_tools = get_local_tool_schemas(ecfg_tool_names) or None
    if bool(ecfg.get("allow_issue_reporting")):
        from app.tools.registry import get_local_tool_schemas
        report_tools = get_local_tool_schemas(["report_issue"]) or []
        injected_tools = list(injected_tools or [])
        existing_names = {
            (schema.get("function") or {}).get("name")
            for schema in injected_tools
            if isinstance(schema, dict)
        }
        for schema in report_tools:
            name = (schema.get("function") or {}).get("name") if isinstance(schema, dict) else None
            if name and name not in existing_names:
                injected_tools.append(schema)
                existing_names.add(name)
        system_preamble = (
            f"{system_preamble.rstrip()}\n\n{_ISSUE_REPORTING_PREAMBLE}"
            if system_preamble
            else _ISSUE_REPORTING_PREAMBLE
        )
    additional_tool_schemas = ecfg.get("additional_tool_schemas") or None
    if additional_tool_schemas:
        injected_tools = list(injected_tools or [])
        existing_names = {
            (schema.get("function") or {}).get("name")
            for schema in injected_tools
            if isinstance(schema, dict)
        }
        for schema in additional_tool_schemas:
            if not isinstance(schema, dict):
                continue
            name = (schema.get("function") or {}).get("name")
            if name and name in existing_names:
                continue
            injected_tools.append(schema)
            if name:
                existing_names.add(name)

    exclude_tools = ecfg.get("exclude_tools") or None
    if exclude_tools:
        import dataclasses as dc
        exclude_set = set(exclude_tools)
        bot = dc.replace(bot, local_tools=[t for t in bot.local_tools if t not in exclude_set])
        logger.info("Task %s: excluded tools %s", task.id, exclude_tools)

    return _PreparedTaskRun(
        task=task,
        bot=bot,
        session_id=session_id,
        messages=messages,
        messages_start=messages_start,
        task_prompt=task_prompt,
        correlation_id=correlation_id,
        context_profile_name=context_profile_name,
        task_timeout=deps.resolve_task_timeout(task, task_channel),
        ecfg=ecfg,
        model_override=model_override,
        provider_id_override=provider_id_override,
        fallback_models=fallback_models,
        skip_tool_policy=skip_tool_policy,
        system_preamble=system_preamble,
        injected_tools=injected_tools,
        is_scheduled=is_scheduled,
        recurrence=recurrence,
    )


async def _run_harness_task_if_needed(
    prepared: _PreparedTaskRun,
    *,
    turn_id: uuid.UUID,
    deps: TaskRunHostDeps,
) -> bool:
    """Run harness-backed bots through the harness path, if configured."""
    if not prepared.bot.harness_runtime:
        return False

    from app.services.turn_worker import _run_harness_turn

    task = prepared.task
    pre_user_msg_id = None
    pre_user_msg_id_str = prepared.ecfg.get("pre_user_msg_id")
    if pre_user_msg_id_str:
        try:
            pre_user_msg_id = uuid.UUID(str(pre_user_msg_id_str))
        except (TypeError, ValueError):
            logger.warning(
                "task %s: invalid pre_user_msg_id %r in execution_config",
                task.id,
                pre_user_msg_id_str,
            )
    base_request = HarnessTurnRequest(
        channel_id=task.channel_id,
        bus_key=task.channel_id or prepared.session_id,
        session_id=prepared.session_id,
        turn_id=turn_id,
        bot=prepared.bot,
        user_message=prepared.task_prompt,
        correlation_id=prepared.correlation_id,
        msg_metadata={
            "source": "heartbeat" if task.task_type == "heartbeat" else "task",
            "task_id": str(task.id),
            "task_type": task.task_type,
            "is_heartbeat": task.task_type == "heartbeat",
            "context_visibility": _metadata_context_visibility(
                task.task_type,
                is_scheduled=prepared.is_scheduled,
            ),
            **({"trigger": "heartbeat", "dispatched": _heartbeat_should_post(task, deps)} if task.task_type == "heartbeat" else {}),
        },
        pre_user_msg_id=pre_user_msg_id,
        suppress_outbox=(
            bool(prepared.ecfg.get("session_scoped"))
            or task.channel_id is None
            or task.task_type == "heartbeat"
        ),
        is_heartbeat=task.task_type == "heartbeat",
        harness_model_override=prepared.ecfg.get("model_override") or None,
        harness_effort_override=prepared.ecfg.get("harness_effort") or None,
    )
    result_text, harness_error = await asyncio.wait_for(
        _run_harness_turn(base_request.with_task_execution_config(prepared.ecfg)),
        timeout=prepared.task_timeout,
    )
    if harness_error:
        async with deps.async_session() as db:
            t = await db.get(Task, task.id)
            if t:
                t.status = "failed"
                t.error = harness_error[:4000]
                t.result = result_text
                t.completed_at = datetime.now(timezone.utc)
                await db.commit()
        await deps.fire_task_complete(task, "failed")
        if task.task_type == "heartbeat":
            await deps.finalize_heartbeat_task_run(
                task,
                status="failed",
                result_text=result_text,
                error_text=harness_error,
                correlation_id=prepared.correlation_id,
            )
        if task.task_type != "heartbeat":
            await deps.publish_turn_ended(
                task,
                turn_id=turn_id,
                result=result_text,
                error=harness_error,
                kind_hint="task",
            )
        return True

    if task.task_type == "heartbeat":
        if _heartbeat_should_post(task, deps) and task.channel_id:
            try:
                from app.services.heartbeat import _enqueue_persisted_heartbeat_result
                await _enqueue_persisted_heartbeat_result(
                    channel_id=task.channel_id,
                    session_id=prepared.session_id,
                    correlation_id=prepared.correlation_id,
                )
            except Exception:
                logger.warning("Heartbeat harness task %s outbox enqueue failed", task.id, exc_info=True)

    async with deps.async_session() as db:
        t = await db.get(Task, task.id)
        if t:
            t.status = "complete"
            t.result = result_text
            t.completed_at = datetime.now(timezone.utc)
            await db.commit()
    await deps.fire_task_complete(task, "complete")
    if task.task_type == "heartbeat":
        await deps.finalize_heartbeat_task_run(
            task,
            status="complete",
            result_text=result_text,
            error_text=None,
            correlation_id=prepared.correlation_id,
        )
    if task.task_type != "heartbeat":
        await deps.publish_turn_ended(
            task,
            turn_id=turn_id,
            result=result_text,
            kind_hint="task",
        )
    return True


def _task_run_origin(task: Task) -> str:
    from app.services.task_run_policy import resolve_task_run_policy

    if task.task_type == "api":
        return "chat"
    return resolve_task_run_policy(task.task_type).origin


async def _bind_project_instance_if_requested(
    db: Any,
    *,
    task: Task,
    execution_config: dict[str, Any],
) -> Any | None:
    run_cfg = execution_config.get("project_coding_run") if isinstance(execution_config, dict) else None
    if isinstance(run_cfg, dict) and task.channel_id is not None:
        from app.db.models import Project
        from app.services.projects import project_canonical_repo_host_path

        channel = await db.get(Channel, task.channel_id)
        project_id = getattr(channel, "project_id", None) if channel is not None else None
        project = await db.get(Project, project_id) if project_id is not None else None
        repo_path = project_canonical_repo_host_path(project) if project is not None else None
        if repo_path and os.path.exists(os.path.join(repo_path, ".git")):
            return None
    from app.services.project_instances import bind_fresh_project_instance_for_task

    return await bind_fresh_project_instance_for_task(
        db,
        task_id=task.id,
        channel_id=task.channel_id,
        execution_config=execution_config,
    )


def _project_dependency_preflight_prompt(preflight: dict[str, Any] | None) -> str:
    if not preflight or not preflight.get("configured"):
        return ""
    env_keys = ", ".join(preflight.get("env_keys") or []) or "none"
    command_keys = ", ".join(preflight.get("command_keys") or []) or "none"
    if preflight.get("ok") is False:
        return (
            "\n\nProject Dependency Stack preflight:\n"
            f"- Status: {preflight.get('status') or 'failed'}\n"
            f"- Source: {preflight.get('source_path') or 'inline spec'}\n"
            f"- Error: {preflight.get('error') or 'unknown error'}\n"
            "- The stack is not ready. Inspect the Project compose file, fix it if needed, then use manage_project_dependency_stack(action=\"reload\" or \"prepare\").\n"
        )
    return (
        "\n\nProject Dependency Stack preflight:\n"
        f"- Status: {preflight.get('status') or 'running'}\n"
        f"- Scope: {preflight.get('scope') or 'task'}\n"
        f"- Source: {preflight.get('source_path') or 'inline spec'}\n"
        f"- Runtime env keys now available: {env_keys}\n"
        f"- Declared stack commands: {command_keys}\n"
        "- Use these dependency env values with native Project commands; continue to use manage_project_dependency_stack for logs, health, reloads, restarts, and service exec.\n"
    )


async def _preflight_project_dependency_stack_if_requested(
    db: Any,
    *,
    task: Task,
    project_instance: Any | None,
    prepared: _PreparedTaskRun,
) -> dict[str, Any] | None:
    cfg = prepared.ecfg.get("project_coding_run")
    if not isinstance(cfg, dict):
        return None
    dep_cfg = cfg.get("dependency_stack")
    if not isinstance(dep_cfg, dict) or not dep_cfg.get("configured"):
        return None
    project_id = cfg.get("project_id")
    if not project_id:
        return None
    from app.db.models import Project
    from app.services.project_dependency_stacks import preflight_task_dependency_stack

    try:
        project_uuid = uuid.UUID(str(project_id))
    except (TypeError, ValueError):
        return None
    project = await db.get(Project, project_uuid)
    if project is None:
        return None
    preflight = await preflight_task_dependency_stack(
        db,
        task=task,
        project=project,
        project_instance=project_instance,
    )
    cfg["dependency_stack_preflight"] = preflight
    dep_cfg["preflight_status"] = preflight.get("status")
    dep_cfg["preflight_env_keys"] = list(preflight.get("env_keys") or [])
    dep_cfg["preflight_ok"] = preflight.get("ok") if preflight.get("configured") else None
    task.execution_config = prepared.ecfg
    db_task = await db.get(Task, task.id)
    if db_task is not None:
        db_task.execution_config = prepared.ecfg
    prompt_addendum = _project_dependency_preflight_prompt(preflight)
    if prompt_addendum:
        prepared.task_prompt = f"{prepared.task_prompt.rstrip()}{prompt_addendum}"
    await db.commit()
    return preflight


async def _ensure_session_environment_if_requested(
    db: Any,
    *,
    task: Task,
    project_instance: Any | None,
) -> Any | None:
    if task.session_id is None:
        return None
    ecfg = task.execution_config if isinstance(task.execution_config, dict) else {}
    run_cfg = ecfg.get("project_coding_run")
    if not isinstance(run_cfg, dict):
        return None
    from app.db.models import Project
    from app.services.session_execution_environments import ensure_isolated_session_environment

    project = await db.get(Project, project_instance.project_id) if project_instance is not None else None
    if project is None and task.channel_id is not None:
        channel = await db.get(Channel, task.channel_id)
        project_id = getattr(channel, "project_id", None) if channel is not None else None
        project = await db.get(Project, project_id) if project_id is not None else None
    return await ensure_isolated_session_environment(
        db,
        session_id=task.session_id,
        project=project,
        project_instance=project_instance,
        branch=str(run_cfg.get("branch") or "") or None,
        base_branch=str(run_cfg.get("base_branch") or "") or None,
    )


async def _run_normal_agent_task(
    prepared: _PreparedTaskRun,
    *,
    turn_id: uuid.UUID,
    suppress_channel: bool,
    session_scoped_task: bool,
    deps: TaskRunHostDeps,
) -> None:
    """Run the normal agent path and own its persistence/dispatch side effects."""
    from app.agent.context import current_run_origin
    from app.agent.loop import run
    from app.services.sessions import persist_turn

    task = prepared.task
    bot = prepared.bot
    from app.services.task_run_policy import resolve_task_run_policy
    skip_skill_inject = resolve_task_run_policy(task.task_type).skip_skill_inject
    current_run_origin.set(_task_run_origin(task))

    run_result = await asyncio.wait_for(
        run(
            prepared.messages, bot, prepared.task_prompt,
            session_id=prepared.session_id,
            client_id=task.client_id or "task",
            correlation_id=prepared.correlation_id,
            dispatch_type=task.dispatch_type,
            dispatch_config=task.dispatch_config,
            channel_id=task.channel_id,
            model_override=prepared.model_override,
            provider_id_override=prepared.provider_id_override,
            fallback_models=prepared.fallback_models,
            system_preamble=prepared.system_preamble,
            injected_tools=prepared.injected_tools,
            skip_tool_policy=prepared.skip_tool_policy,
            task_mode=True,
            skip_skill_inject=skip_skill_inject,
            context_profile_name=prepared.context_profile_name,
            run_control_policy=_task_run_control_policy(
                prepared.ecfg,
                task_type=task.task_type,
            ),
        ),
        timeout=prepared.task_timeout,
    )
    result_text = run_result.response

    task_meta: dict | None = None
    if task.task_type == "heartbeat":
        hb_meta = deps.heartbeat_execution_meta(task)
        dispatched = _heartbeat_should_post(task, deps)
        task_meta = {
            "trigger": "heartbeat",
            "task_id": str(task.id),
            "task_type": task.task_type,
            "heartbeat_id": hb_meta.get("heartbeat_id"),
            "heartbeat_run_id": hb_meta.get("heartbeat_run_id"),
            "is_heartbeat": True,
            "dispatched": dispatched,
            "context_visibility": "background",
        }
    elif prepared.is_scheduled:
        task_meta = {
            "trigger": "scheduled_task",
            "task_id": str(task.id),
            "task_type": task.task_type,
            "context_visibility": "background",
        }
        if task.title:
            task_meta["task_title"] = task.title
        if prepared.recurrence:
            task_meta["recurrence"] = prepared.recurrence
        if task.parent_task_id:
            task_meta["schedule_id"] = str(task.parent_task_id)
    elif task.task_type == "callback":
        task_meta = {
            "trigger": "callback",
            "task_id": str(task.id),
            "task_type": task.task_type,
            "context_visibility": _metadata_context_visibility(task.task_type),
            "sender_type": "bot",
            "sender_display_name": bot.name,
        }
        if task.parent_task_id:
            async with deps.async_session() as cb_db:
                cb_parent = await cb_db.get(Task, task.parent_task_id)
                if cb_parent and cb_parent.task_type == "delegation":
                    task_meta["trigger"] = "delegation_callback"
                    task_meta["delegation_child_bot_id"] = cb_parent.bot_id
                    try:
                        child_bot = deps.get_bot(cb_parent.bot_id)
                        task_meta["delegation_child_display"] = child_bot.display_name or child_bot.name
                    except Exception:
                        pass
    elif (task.callback_config or {}).get("pipeline_task_id"):
        pipeline_task_id = (task.callback_config or {}).get("pipeline_task_id")
        pipeline_title = "Pipeline step"
        try:
            async with deps.async_session() as pp_db:
                pp_parent = await pp_db.get(Task, uuid.UUID(pipeline_task_id))
                if pp_parent and pp_parent.title:
                    pipeline_title = pp_parent.title
        except Exception:
            pass
        task_meta = {
            "trigger": "pipeline_step",
            "sender_type": "pipeline",
            "sender_display_name": pipeline_title,
            "pipeline_task_id": pipeline_task_id,
            "pipeline_step_index": (task.callback_config or {}).get("pipeline_step_index"),
            "task_type": task.task_type,
            "context_visibility": "background",
        }

    pre_user_msg_id_str = (task.execution_config or {}).get("pre_user_msg_id")
    pre_user_msg_id = None
    if pre_user_msg_id_str:
        try:
            pre_user_msg_id = uuid.UUID(pre_user_msg_id_str)
        except (ValueError, TypeError):
            logger.warning(
                "task %s: invalid pre_user_msg_id %r in execution_config",
                task.id, pre_user_msg_id_str,
            )

    persist_channel_id = None if suppress_channel else task.channel_id
    async with deps.async_session() as db:
        await persist_turn(
            db, prepared.session_id, bot, prepared.messages, prepared.messages_start,
            correlation_id=prepared.correlation_id,
            channel_id=persist_channel_id,
            msg_metadata=task_meta,
            is_heartbeat=task.task_type == "heartbeat",
            pre_user_msg_id=pre_user_msg_id,
            hide_messages=suppress_channel,
            suppress_outbox=session_scoped_task or task.task_type == "heartbeat",
        )

    dispatch_text = result_text
    if prepared.is_scheduled:
        label = f"🔁 _{task.title or 'Scheduled task'}_\n"
        dispatch_text = label + result_text

    delegation_meta = None
    if task.task_type == "delegation":
        parent_bot_id = (task.callback_config or {}).get("parent_bot_id")
        parent_display = parent_bot_id
        if parent_bot_id:
            try:
                parent_bot = deps.get_bot(parent_bot_id)
                parent_display = parent_bot.display_name or parent_bot.name
            except Exception:
                pass
        delegation_meta = {
            "delegated_by": parent_bot_id,
            "delegated_by_display": parent_display,
            "delegation_task_id": str(task.id),
        }

    dispatch_actions = None if task.task_type == "callback" else run_result.client_actions
    if task.task_type == "heartbeat":
        if _heartbeat_should_post(task, deps) and task.channel_id:
            try:
                from app.services.heartbeat import _enqueue_persisted_heartbeat_result
                await _enqueue_persisted_heartbeat_result(
                    channel_id=task.channel_id,
                    session_id=prepared.session_id,
                    correlation_id=prepared.correlation_id,
                )
            except Exception:
                logger.warning("Heartbeat task %s outbox enqueue failed", task.id, exc_info=True)

    if task.task_type != "heartbeat":
        await deps.publish_turn_ended(
            task,
            turn_id=turn_id,
            result=dispatch_text,
            client_actions=dispatch_actions,
            extra_metadata=delegation_meta,
            kind_hint=None,
        )

    cb = task.callback_config or {}
    followup_tasks: list[Task] = []
    if (
        task.task_type == "heartbeat"
        and _heartbeat_should_post(task, deps)
        and deps.heartbeat_execution_meta(task).get("trigger_rag_loop")
        and result_text
    ):
        followup_tasks.append(Task(
            bot_id=task.bot_id,
            client_id=task.client_id,
            session_id=prepared.session_id,
            channel_id=task.channel_id,
            prompt=f"[Your scheduled heartbeat just ran. The output was:]\n\n{result_text}",
            status="pending",
            task_type="callback",
            dispatch_type=task.dispatch_type,
            dispatch_config=dict(task.dispatch_config or {}),
            callback_config={"trigger_rag_loop": False},
            parent_task_id=task.id,
            created_at=datetime.now(timezone.utc),
        ))
    elif cb.get("trigger_rag_loop") and result_text:
        followup_tasks.append(Task(
            bot_id=task.bot_id,
            client_id=task.client_id,
            session_id=prepared.session_id,
            channel_id=task.channel_id,
            prompt=f"[Your scheduled task just ran and posted to the channel. The output was:]\n\n{result_text}",
            status="pending",
            task_type="callback",
            dispatch_type=task.dispatch_type,
            dispatch_config=dict(task.dispatch_config or {}),
            callback_config={"trigger_rag_loop": False},
            parent_task_id=task.id,
            created_at=datetime.now(timezone.utc),
        ))

    has_result = bool(result_text) or bool(run_result.client_actions)
    if cb.get("notify_parent") and has_result:
        parent_bot_id = cb.get("parent_bot_id")
        parent_session_str = cb.get("parent_session_id")
        parent_client_id = cb.get("parent_client_id")
        if parent_bot_id and parent_session_str:
            try:
                parent_session_id = uuid.UUID(parent_session_str)
                child_display = task.bot_id
                try:
                    child_bot = deps.get_bot(task.bot_id)
                    child_display = child_bot.display_name or child_bot.name
                except Exception:
                    pass
                cb_result_desc = result_text or "[The sub-agent completed its work via tool calls with no text response.]"
                cb_prompt = (
                    f"[DELEGATION RESULT — from {child_display}]\n"
                    f"The sub-agent has already posted its response to the channel. "
                    f"Here is what it returned:\n\n"
                    f"{cb_result_desc}\n\n"
                    f"Provide a brief follow-up or summary if appropriate. "
                    f"Do NOT re-post any files or images the sub-agent already provided. "
                    f"Do NOT delegate again — the work is complete."
                )
                followup_tasks.append(Task(
                    bot_id=parent_bot_id,
                    client_id=parent_client_id,
                    session_id=parent_session_id,
                    channel_id=task.channel_id,
                    prompt=cb_prompt,
                    status="pending",
                    task_type="callback",
                    dispatch_type=task.dispatch_type,
                    dispatch_config=dict(task.dispatch_config or {}),
                    execution_config={"exclude_tools": ["delegate_to_agent"]},
                    parent_task_id=task.id,
                    created_at=datetime.now(timezone.utc),
                ))
            except Exception:
                logger.exception("Failed to build parent callback task for task %s", task.id)

    async with deps.async_session() as db:
        t = await db.get(Task, task.id)
        if t:
            t.status = "complete"
            t.result = result_text
            t.completed_at = datetime.now(timezone.utc)
        for followup_task in followup_tasks:
            db.add(followup_task)
        await db.commit()
        for followup_task in followup_tasks:
            await db.refresh(followup_task)

    await deps.fire_task_complete(task, "complete")
    if task.task_type == "heartbeat":
        await deps.finalize_heartbeat_task_run(
            task,
            status="complete",
            result_text=result_text,
            error_text=None,
            correlation_id=prepared.correlation_id,
        )

    for followup_task in followup_tasks:
        logger.info(
            "Task %s: created follow-up task %s (type=%s, bot=%s)",
            task.id, followup_task.id, followup_task.task_type, followup_task.bot_id,
        )


async def run_task(task: Task, *, deps: TaskRunHostDeps) -> None:
    """Execute a single task: run the agent, store result, dispatch."""
    _task_channel: Channel | None = None
    try:
        async with deps.async_session() as db:
            _, _task_channel = await deps.resolve_task_session_target(db, task)
            await db.commit()
    except ValueError as exc:
        logger.warning("Task %s failed session-target resolution: %s", task.id, exc)
        await deps.mark_task_failed_in_db(task.id, error=str(exc)[:4000])
        await deps.fire_task_complete(task, "failed")
        if task.task_type == "heartbeat":
            await deps.finalize_heartbeat_task_run(
                task,
                status="failed",
                result_text=None,
                error_text=str(exc)[:4000],
                correlation_id=None,
            )
        return

    if await deps.dispatch_to_specialized_runner(task):
        return

    # Respect the per-session active lock. If a streaming HTTP request is still
    # running for this session, defer this task by 10 seconds rather than running
    # a parallel agent loop.
    # Skip lock for delegation tasks: they create their own child session (cross-bot)
    # or explicitly need to run alongside the parent who is waiting for their result.
    _skip_lock = task.task_type == "delegation"
    _lock_acquired = False
    if task.session_id and not _skip_lock:
        if deps.session_locks.acquire(task.session_id):
            _lock_acquired = True
        else:
            async with deps.async_session() as db:
                t = await db.get(Task, task.id)
                if t:
                    t.status = "pending"
                    t.run_at = None
                    t.scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=10)
                    await db.commit()
            logger.info("Task %s deferred 10s: session %s is busy", task.id, task.session_id)
            return

    logger.info("Running task %s (bot=%s)", task.id, task.bot_id)

    # Task is already marked running by fetch_due_tasks (atomic fetch-and-mark).
    # Verify it still exists before proceeding.
    async with deps.async_session() as db:
        t = await db.get(Task, task.id)
        if t is None:
            if _lock_acquired:
                deps.session_locks.release(task.session_id)
            return

    # Per-task turn correlation. Threaded through TURN_STARTED and every
    # TURN_ENDED publish (success, timeout, rate-limit, exception) so
    # subscribers can demultiplex parallel turns by turn_id.
    _turn_id = uuid.uuid4()

    # Tell the bus a queued task is starting; renderers (Slack/Discord)
    # post a "thinking..." placeholder when this fires. Suppressed for
    # pipeline agent-step children -- the parent pipeline's envelope
    # shows the step's progress instead.
    _suppress_channel = deps.is_pipeline_child(task)
    _session_scoped_task = bool((task.execution_config or {}).get("session_scoped"))
    # For sub-session pipeline children, route TURN_STARTED to the parent
    # channel's bus so the run-view modal sees the event. Inline pipeline
    # children stay suppressed (the parent envelope renders step status
    # from step_states).
    _publish_channel_id: uuid.UUID | None = task.channel_id
    # When a sub-session pipeline child publishes on the parent channel's
    # bus, tag the payload with the child's session_id so parent-channel
    # UI subscribers can filter the event out (otherwise the child's bot
    # would show up as a phantom streaming indicator in the parent channel).
    _publish_session_id: uuid.UUID | None = None
    if _session_scoped_task:
        _publish_session_id = getattr(task, "session_id", None)
    if _suppress_channel and task.channel_id is None:
        _publish_channel_id = await deps.resolve_sub_session_bus_channel(task)
        _suppress_channel = _publish_channel_id is None
        if not _suppress_channel:
            _publish_session_id = getattr(task, "session_id", None)
    if _publish_channel_id is not None and not _suppress_channel and task.task_type != "heartbeat":
        try:
            from app.domain.channel_events import ChannelEvent, ChannelEventKind
            from app.domain.payloads import TurnStartedPayload
            from app.services.channel_events import publish_typed

            publish_typed(
                _publish_channel_id,
                ChannelEvent(
                    channel_id=_publish_channel_id,
                    kind=ChannelEventKind.TURN_STARTED,
                    payload=TurnStartedPayload(
                        bot_id=task.bot_id,
                        turn_id=_turn_id,
                        task_id=str(task.id),
                        reason="queued_task_starting",
                        session_id=_publish_session_id,
                    ),
                ),
            )
            from app.agent.recording import _record_trace_event
            from app.utils import safe_create_task

            safe_create_task(_record_trace_event(
                correlation_id=_turn_id,
                session_id=_publish_session_id or task.session_id,
                bot_id=task.bot_id,
                client_id=task.client_id,
                event_type="turn_started",
                data={
                    "bot_id": task.bot_id,
                    "task_id": str(task.id),
                    "reason": "queued_task_starting",
                },
            ))
        except Exception:
            logger.debug("publish TURN_STARTED failed for task %s", task.id, exc_info=True)

    _task_timeout = deps.settings.TASK_MAX_RUN_SECONDS
    correlation_id: uuid.UUID | None = None

    try:
        prepared = await _prepare_task_run(task, _task_channel, deps)
        _task_timeout = prepared.task_timeout
        correlation_id = prepared.correlation_id
        from app.agent.context import current_issue_reporting_enabled, current_project_instance_id, current_task_id
        async with deps.async_session() as instance_db:
            project_instance = await _bind_project_instance_if_requested(
                instance_db,
                task=task,
                execution_config=prepared.ecfg,
            )
            await _ensure_session_environment_if_requested(
                instance_db,
                task=task,
                project_instance=project_instance,
            )
            await _preflight_project_dependency_stack_if_requested(
                instance_db,
                task=task,
                project_instance=project_instance,
                prepared=prepared,
            )
            current_project_instance_id.set(project_instance.id if project_instance is not None else None)
        current_task_id.set(task.id)
        current_issue_reporting_enabled.set(bool(prepared.ecfg.get("allow_issue_reporting")))
        if task.task_type == "heartbeat":
            await deps.mark_heartbeat_task_started(task, correlation_id)
        from app.services.machine_task_grants import task_machine_lease_context
        async with task_machine_lease_context(
            prepared.task,
            session_id=prepared.session_id,
            purpose="agent_run",
        ):
            if await _run_harness_task_if_needed(prepared, turn_id=_turn_id, deps=deps):
                return
            await _run_normal_agent_task(
                prepared,
                turn_id=_turn_id,
                suppress_channel=_suppress_channel,
                session_scoped_task=_session_scoped_task,
                deps=deps,
            )

    except asyncio.TimeoutError:
        logger.error("Task %s timed out after %ds", task.id, _task_timeout)
        _timeout_err = f"Timed out after {_task_timeout}s"
        await deps.mark_task_failed_in_db(task.id, error=_timeout_err)
        if task.task_type == "heartbeat":
            await deps.finalize_heartbeat_task_run(
                task,
                status="failed",
                result_text=None,
                error_text=_timeout_err,
                correlation_id=correlation_id,
            )
        await deps.record_timeout_event(task, correlation_id, _timeout_err)
        await deps.fire_task_complete(task, "failed")
        await deps.publish_turn_ended_safe(
            task, turn_id=_turn_id, error=_timeout_err, log_label="timeout error",
        )

    except openai.RateLimitError as exc:
        async with deps.async_session() as db:
            t = await db.get(Task, task.id)
            if t is None:
                return
            if t.retry_count < deps.settings.TASK_RATE_LIMIT_RETRIES:
                t.retry_count += 1
                # Exponential backoff: 65s, 130s, 260s -- slightly longer than a 60s TPM window
                delay = deps.settings.LLM_RATE_LIMIT_INITIAL_WAIT * (2 ** (t.retry_count - 1))
                t.status = "pending"
                t.scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                t.error = (
                    f"rate_limited (attempt {t.retry_count}/{deps.settings.TASK_RATE_LIMIT_RETRIES}): "
                    f"{str(exc)[:200]}"
                )
                await db.commit()
                logger.warning(
                    "Task %s rate limited, rescheduled in %ds (attempt %d/%d)",
                    task.id, delay, t.retry_count, deps.settings.TASK_RATE_LIMIT_RETRIES,
                )
            else:
                t.status = "failed"
                t.error = f"rate_limited (max retries exhausted): {str(exc)[:3800]}"
                t.completed_at = datetime.now(timezone.utc)
                await db.commit()
                logger.error("Task %s failed after %d rate limit retries", task.id, t.retry_count)
                if task.task_type == "heartbeat":
                    await deps.finalize_heartbeat_task_run(
                        task,
                        status="failed",
                        result_text=None,
                        error_text="rate_limited",
                        correlation_id=correlation_id,
                    )
                await deps.fire_task_complete(task, "failed")
                await deps.publish_turn_ended_safe(
                    task, turn_id=_turn_id, error="rate_limited",
                    log_label="rate limit error",
                )

    except Exception as exc:
        logger.exception("Task %s failed", task.id)
        await deps.mark_task_failed_in_db(task.id, error=str(exc)[:4000])
        if task.task_type == "heartbeat":
            await deps.finalize_heartbeat_task_run(
                task,
                status="failed",
                result_text=None,
                error_text=str(exc)[:4000],
                correlation_id=correlation_id,
            )
        await deps.fire_task_complete(task, "failed")
        await deps.publish_turn_ended_safe(
            task, turn_id=_turn_id, error=str(exc)[:500], log_label="error",
        )
    finally:
        from app.agent.context import current_issue_reporting_enabled, current_project_instance_id, current_task_id
        current_task_id.set(None)
        current_project_instance_id.set(None)
        current_issue_reporting_enabled.set(False)
        if _lock_acquired:
            deps.session_locks.release(task.session_id)
