"""Host-side orchestration for a single agent-harness turn.

Harness runtimes own the external agent loop. This Module owns the Spindrel
host work around that runtime: settings, context hints, cancellation,
persistence, usage, native plan mirroring, and auto-compaction.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.agent.bots import BotConfig
from app.db.engine import async_session
from app.db.models import Session as SessionRow
from app.services import session_locks
from app.services.agent_harnesses import ChannelEventEmitter, get_runtime
from app.services.agent_harnesses.base import HarnessInputAttachment, HarnessInputManifest
from app.services.sessions import persist_turn

logger = logging.getLogger(__name__)

_HARNESS_SKILL_TAG_RE = re.compile(r"(?<![<\w@])@skill:([A-Za-z_][\w\-\./]*)")
_HARNESS_TOOL_TAG_RE = re.compile(r"(?<![<\w@])@tool:([A-Za-z_][\w\-\./]*)")


def format_turn_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return type(exc).__name__
    return f"{type(exc).__name__}: {message[:500]}"


def build_turn_failure_message(error_text: str, partial_text: str = "") -> str:
    marker = f"[Turn failed: {error_text}]"
    if partial_text.strip():
        return f"{partial_text.rstrip()}\n\n{marker}"
    return f"The turn failed before producing a response.\n\n{marker}"


class HarnessTurnCancelled(Exception):
    """Raised when a harness turn sees the session cancellation flag."""


def parse_harness_explicit_tags(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    def _unique(matches: list[str]) -> tuple[str, ...]:
        out: list[str] = []
        seen: set[str] = set()
        for value in matches:
            value = value.rstrip(".,;:!?")
            if value and value not in seen:
                seen.add(value)
                out.append(value)
        return tuple(out)

    return (
        _unique([m.group(1) for m in _HARNESS_TOOL_TAG_RE.finditer(text or "")]),
        _unique([m.group(1) for m in _HARNESS_SKILL_TAG_RE.finditer(text or "")]),
    )


def merge_harness_turn_selections(
    user_message: str,
    *,
    tool_names: tuple[str, ...] | list[str] = (),
    skill_ids: tuple[str, ...] | list[str] = (),
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Merge prompt @tags with host-selected harness bridge selections."""
    prompt_tools, prompt_skills = parse_harness_explicit_tags(user_message)

    def _merge(*groups) -> tuple[str, ...]:
        out: list[str] = []
        seen: set[str] = set()
        for group in groups:
            for raw in group or ():
                value = str(raw).strip().rstrip(".,;:!?")
                if value and value not in seen:
                    seen.add(value)
                    out.append(value)
        return tuple(out)

    return (
        _merge(prompt_tools, tool_names),
        _merge(prompt_skills, skill_ids),
    )


def _build_harness_input_manifest(
    *,
    tagged_skill_ids: tuple[str, ...],
    attachments: tuple[dict[str, Any], ...],
    msg_metadata: dict | None,
    channel_id: uuid.UUID | None,
    bot: BotConfig,
) -> HarnessInputManifest:
    prepared: list[HarnessInputAttachment] = []

    for entry in attachments:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("type") or "file")
        mime_type = str(entry.get("mime_type") or "application/octet-stream")
        content = entry.get("content")
        if kind == "image" and isinstance(content, str) and content:
            prepared.append(
                HarnessInputAttachment(
                    kind="image",
                    source="inline_attachment",
                    name=str(entry.get("name") or ""),
                    mime_type=mime_type,
                    content_base64=content,
                    attachment_id=str(entry.get("attachment_id") or "") or None,
                )
            )

    workspace_uploads = tuple(
        item for item in ((msg_metadata or {}).get("workspace_uploads") or ())
        if isinstance(item, dict)
    )
    if workspace_uploads and channel_id is not None:
        root = _safe_channel_workspace_root(channel_id, bot)
        if root:
            root_real = os.path.realpath(root)
            for item in workspace_uploads:
                mime_type = str(item.get("mime_type") or "application/octet-stream")
                if not mime_type.startswith("image/"):
                    continue
                rel_path = str(item.get("path") or "").strip()
                if not rel_path:
                    continue
                abs_path = os.path.realpath(os.path.join(root_real, rel_path))
                if not (abs_path == root_real or abs_path.startswith(root_real + os.sep)):
                    continue
                prepared.append(
                    HarnessInputAttachment(
                        kind="image",
                        source="channel_workspace",
                        name=str(item.get("filename") or os.path.basename(rel_path)),
                        mime_type=mime_type,
                        path=abs_path,
                        size_bytes=item.get("size_bytes") if isinstance(item.get("size_bytes"), int) else None,
                    )
                )

    return HarnessInputManifest(
        tagged_skill_ids=tuple(tagged_skill_ids),
        attachments=tuple(prepared),
        workspace_uploads=workspace_uploads,
    )


def _safe_channel_workspace_root(channel_id: uuid.UUID, bot: BotConfig) -> str | None:
    try:
        from app.services.channel_workspace import get_channel_workspace_root

        return get_channel_workspace_root(str(channel_id), bot)
    except Exception:
        logger.warning("harness: failed to resolve channel workspace root for %s", channel_id, exc_info=True)
        return None


async def load_harness_channel_prompt_hint(db, channel_id: uuid.UUID | None):
    """Return the channel prompt as a harness host instruction, if configured."""
    if channel_id is None:
        return None
    from app.db.models import Channel
    from app.services.agent_harnesses.base import HarnessContextHint
    from app.services.prompt_resolution import resolve_workspace_file_prompt

    channel = await db.get(Channel, channel_id)
    if channel is None:
        return None

    workspace_path = getattr(channel, "channel_prompt_workspace_file_path", None)
    workspace_id = getattr(channel, "channel_prompt_workspace_id", None)
    inline_prompt = getattr(channel, "channel_prompt", None) or ""
    if workspace_path and workspace_id:
        prompt = resolve_workspace_file_prompt(str(workspace_id), workspace_path, inline_prompt)
    else:
        prompt = inline_prompt
    prompt = (prompt or "").strip()
    if not prompt:
        return None
    return HarnessContextHint(
        kind="channel_prompt",
        source="channel",
        created_at=datetime.now(timezone.utc).isoformat(),
        consume_after_next_turn=False,
        priority="instruction",
        text=prompt,
    )


async def run_harness_turn(
    *,
    channel_id: uuid.UUID | None,
    bus_key: uuid.UUID,
    session_id: uuid.UUID,
    turn_id: uuid.UUID,
    bot: BotConfig,
    user_message: str,
    correlation_id: uuid.UUID,
    msg_metadata: dict | None,
    pre_user_msg_id: uuid.UUID | None,
    suppress_outbox: bool,
    is_heartbeat: bool = False,
    harness_model_override: str | None = None,
    harness_effort_override: str | None = None,
    harness_permission_mode_override: str | None = None,
    harness_tool_names: tuple[str, ...] | list[str] = (),
    harness_skill_ids: tuple[str, ...] | list[str] = (),
    harness_attachments: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    async_session_factory=async_session,
    get_runtime_fn: Callable[[str], Any] = get_runtime,
    persist_turn_fn: Callable[..., Awaitable[Any]] = persist_turn,
    load_prior_harness_session_id_fn: Callable[[uuid.UUID], Awaitable[str | None]] | None = None,
    persist_harness_failure_fn: Callable[..., Awaitable[tuple[str, str]]] | None = None,
    start_harness_turn_with_cancel_fn: Callable[..., Awaitable[Any]] | None = None,
    mirror_harness_native_plan_state_fn: Callable[..., Awaitable[None]] | None = None,
    merge_harness_turn_selections_fn: Callable[..., tuple[tuple[str, ...], tuple[str, ...]]] = merge_harness_turn_selections,
    load_harness_channel_prompt_hint_fn: Callable[..., Awaitable[Any]] = load_harness_channel_prompt_hint,
) -> tuple[str, str | None]:
    """Drive a turn against an external agent harness.

    Returns ``(response_text, error_text)``. ``error_text`` is None on success.
    """
    load_prior = load_prior_harness_session_id_fn or load_prior_harness_session_id
    persist_failure = persist_harness_failure_fn or persist_harness_failure
    start_with_cancel = start_harness_turn_with_cancel_fn or start_harness_turn_with_cancel
    mirror_plan = mirror_harness_native_plan_state_fn or mirror_harness_native_plan_state

    try:
        runtime = get_runtime_fn(bot.harness_runtime)  # type: ignore[arg-type]
    except KeyError:
        msg = (
            f"Harness runtime '{bot.harness_runtime}' is not registered. "
            f"The integration may be inactive or its Python deps may be missing - "
            f"open /admin/integrations and click 'Reinstall (upgrade)'."
        )
        return await persist_failure(
            channel_id=channel_id, session_id=session_id, turn_id=turn_id,
            bot=bot, user_message=user_message, correlation_id=correlation_id,
            msg_metadata=msg_metadata, pre_user_msg_id=pre_user_msg_id,
            suppress_outbox=suppress_outbox, is_heartbeat=is_heartbeat, error_text=msg,
            prior_session_id=None,
            async_session_factory=async_session_factory,
            persist_turn_fn=persist_turn_fn,
        )
    prior_session_id = await load_prior(session_id)

    from app.services.agent_harnesses.approvals import (
        load_session_mode,
        revoke_turn_bypass,
    )
    from app.services.agent_harnesses.base import HarnessContextHint
    from app.services.agent_harnesses.context import build_turn_context
    from app.services.agent_harnesses.project import (
        build_workspace_files_memory_hint,
        project_directory_payload,
        resolve_harness_paths,
    )
    from app.services.project_runtime import load_project_runtime_environment_for_id
    from app.services.agent_harnesses.session_state import (
        clear_consumed_context_hints,
        hint_preview,
        load_context_hints,
        load_latest_harness_metadata,
    )
    from app.services.agent_harnesses.settings import load_session_settings
    from app.services.session_plan_mode import get_session_plan_mode

    async with async_session_factory() as db:
        try:
            harness_paths = await resolve_harness_paths(db, channel_id=channel_id, bot=bot)
        except Exception as exc:
            return "", f"could not resolve harness workspace for bot: {exc}"
        workdir = harness_paths.workdir
        runtime_env = None
        work_surface = getattr(harness_paths, "work_surface", None)
        if work_surface is not None and work_surface.kind == "project":
            runtime_env = await load_project_runtime_environment_for_id(
                db,
                work_surface.project_id,
            )
        session_permission_mode = await load_session_mode(db, session_id)
        permission_mode = harness_permission_mode_override or session_permission_mode
        harness_settings = await load_session_settings(db, session_id)
        harness_model = harness_model_override if harness_model_override is not None else harness_settings.model
        harness_effort = harness_effort_override if harness_effort_override is not None else harness_settings.effort
        context_hints = list(await load_context_hints(db, session_id))
        if channel_prompt_hint := await load_harness_channel_prompt_hint_fn(db, channel_id):
            context_hints.insert(0, channel_prompt_hint)
        harness_meta, _last_turn_at = await load_latest_harness_metadata(db, session_id)
        session_row = await db.get(SessionRow, session_id)
        session_plan_mode = get_session_plan_mode(session_row) if session_row is not None else "chat"

    plan_hint = _build_harness_plan_tool_hint(session_plan_mode)
    if plan_hint is not None:
        context_hints.append(plan_hint)

    explicit_tool_names, tagged_skill_ids = merge_harness_turn_selections_fn(
        user_message,
        tool_names=harness_tool_names,
        skill_ids=harness_skill_ids,
    )
    if tagged_skill_ids:
        from sqlalchemy import select
        from app.db.models import Skill

        async with async_session_factory() as db:
            rows = (await db.execute(
                select(Skill.id, Skill.name, Skill.description).where(
                    Skill.id.in_(list(tagged_skill_ids)),
                    Skill.archived_at.is_(None),
                )
            )).all()
        by_id = {row.id: row for row in rows}
        lines = [
            "The user or host selected these Spindrel skills for this harness turn.",
            "Use the bridged get_skill(skill_id=\"...\") tool to fetch full skill bodies progressively; these lines are an index, not the full content.",
        ]
        for skill_id in tagged_skill_ids:
            row = by_id.get(skill_id)
            if row is None:
                lines.append(f"- {skill_id} - not found or archived")
                continue
            desc = f": {row.description}" if row.description else ""
            lines.append(f"- {row.id} - {row.name}{desc}")
        context_hints.append(
            HarnessContextHint(
                kind="tagged_skills",
                source="composer",
                created_at=datetime.now(timezone.utc).isoformat(),
                consume_after_next_turn=True,
                text="\n".join(lines),
            )
        )

    input_manifest = _build_harness_input_manifest(
        tagged_skill_ids=tagged_skill_ids,
        attachments=tuple(harness_attachments or ()),
        msg_metadata=msg_metadata,
        channel_id=channel_id,
        bot=bot,
    )

    memory_hint = build_workspace_files_memory_hint(bot, harness_paths.bot_workspace_dir)
    if memory_hint is not None:
        context_hints.append(memory_hint)

    emitter = ChannelEventEmitter(
        channel_id=bus_key,
        turn_id=turn_id,
        bot_id=bot.id,
        session_id=session_id,
        redact_text=runtime_env.redact_text if runtime_env is not None else None,
    )

    ctx = build_turn_context(
        spindrel_session_id=session_id,
        channel_id=channel_id,
        bot_id=bot.id,
        turn_id=turn_id,
        workdir=workdir,
        env=dict(runtime_env.env) if runtime_env is not None else None,
        harness_session_id=prior_session_id,
        permission_mode=permission_mode,
        db_session_factory=async_session_factory,
        model=harness_model,
        effort=harness_effort,
        runtime_settings=harness_settings.runtime_settings,
        context_hints=tuple(context_hints),
        ephemeral_tool_names=explicit_tool_names,
        tagged_skill_ids=tagged_skill_ids,
        input_manifest=input_manifest,
        session_plan_mode=session_plan_mode,
        harness_metadata=harness_meta or {},
    )

    runtime_accepted_turn = False
    try:
        try:
            result = await start_with_cancel(
                runtime=runtime,
                ctx=ctx,
                prompt=user_message,
                emit=emitter,
                session_id=session_id,
            )
            runtime_accepted_turn = True
        finally:
            revoke_turn_bypass(turn_id)
    except HarnessTurnCancelled:
        persisted_tool_calls = emitter.persisted_tool_calls()
        tool_envelopes = emitter.tool_envelopes()
        assistant_turn_body = emitter.assistant_turn_body(text="")
        cancelled_assistant_msg: dict = {
            "role": "assistant",
            "content": "",
            "_turn_cancelled": True,
            "_harness": {
                "runtime": bot.harness_runtime,
                "session_id": prior_session_id,
                "interrupted": True,
                "effective_cwd": workdir,
                "effective_cwd_source": harness_paths.source,
                "bot_workspace_dir": harness_paths.bot_workspace_dir,
                "project_dir": project_directory_payload(harness_paths.project_dir),
                "last_hints_sent": [hint_preview(hint) for hint in context_hints],
                "input_manifest": input_manifest.metadata(),
            },
        }
        if persisted_tool_calls:
            cancelled_assistant_msg["tool_calls"] = persisted_tool_calls
            if tool_envelopes:
                cancelled_assistant_msg["_tool_envelopes"] = tool_envelopes
            cancelled_assistant_msg["_tools_used"] = [
                call["function"]["name"] for call in persisted_tool_calls
            ]
        if assistant_turn_body:
            cancelled_assistant_msg["_assistant_turn_body"] = assistant_turn_body
        synthetic_messages: list[dict] = [
            {"role": "user", "content": user_message},
            cancelled_assistant_msg,
        ]
        try:
            async with async_session_factory() as db:
                await persist_turn_fn(
                    db, session_id, bot, synthetic_messages, from_index=0,
                    correlation_id=correlation_id,
                    msg_metadata=msg_metadata,
                    channel_id=channel_id,
                    is_heartbeat=is_heartbeat,
                    pre_user_msg_id=pre_user_msg_id,
                    suppress_outbox=suppress_outbox,
                )
        except Exception:
            logger.exception(
                "harness '%s': failed to persist cancelled row for session %s",
                bot.harness_runtime, session_id,
            )
        return "", "cancelled"
    except Exception as exc:
        logger.exception(
            "harness '%s' turn %s failed for bot %s",
            bot.harness_runtime, turn_id, bot.id,
        )
        error_text = format_turn_exception(exc)
        persisted_tool_calls = emitter.persisted_tool_calls()
        tool_envelopes = emitter.tool_envelopes()
        assistant_turn_body = emitter.assistant_turn_body(text="")
        error_assistant_msg: dict = {
            "role": "assistant",
            "content": build_turn_failure_message(error_text, ""),
            "_turn_error": True,
            "_turn_error_message": error_text,
            "_harness": {
                "runtime": bot.harness_runtime,
                "session_id": prior_session_id,
                "error": error_text,
                "effective_cwd": workdir,
                "effective_cwd_source": harness_paths.source,
                "bot_workspace_dir": harness_paths.bot_workspace_dir,
                "project_dir": project_directory_payload(harness_paths.project_dir),
                "last_hints_sent": [hint_preview(hint) for hint in context_hints],
                "input_manifest": input_manifest.metadata(),
            },
        }
        if persisted_tool_calls:
            error_assistant_msg["tool_calls"] = persisted_tool_calls
            if tool_envelopes:
                error_assistant_msg["_tool_envelopes"] = tool_envelopes
            error_assistant_msg["_tools_used"] = [
                call["function"]["name"] for call in persisted_tool_calls
            ]
        if assistant_turn_body:
            error_assistant_msg["_assistant_turn_body"] = assistant_turn_body
        synthetic_messages: list[dict] = [
            {"role": "user", "content": user_message},
            error_assistant_msg,
        ]
        try:
            async with async_session_factory() as db:
                await persist_turn_fn(
                    db, session_id, bot, synthetic_messages, from_index=0,
                    correlation_id=correlation_id,
                    msg_metadata=msg_metadata,
                    channel_id=channel_id,
                    is_heartbeat=is_heartbeat,
                    pre_user_msg_id=pre_user_msg_id,
                    suppress_outbox=suppress_outbox,
                )
        except Exception:
            logger.exception(
                "harness '%s': failed to persist error row for session %s",
                bot.harness_runtime, session_id,
            )
        return "", error_text

    from app.services.secret_registry import redact as _redact_secrets

    final_text = _redact_secrets(result.final_text)
    persisted_tool_calls = emitter.persisted_tool_calls()
    tool_envelopes = emitter.tool_envelopes()
    assistant_turn_body = emitter.assistant_turn_body(text=final_text)
    await mirror_plan(
        session_id=session_id,
        runtime_name=bot.harness_runtime,
        result_metadata=result.metadata or {},
        persisted_tool_calls=persisted_tool_calls,
        async_session_factory=async_session_factory,
    )
    if runtime_accepted_turn and context_hints:
        try:
            async with async_session_factory() as db:
                await clear_consumed_context_hints(db, session_id)
        except Exception:
            logger.exception(
                "harness '%s': failed to clear consumed context hints for session %s",
                bot.harness_runtime,
                session_id,
            )
    assistant_msg: dict = {
        "role": "assistant",
        "content": final_text,
        "_harness": {
            "runtime": bot.harness_runtime,
            "session_id": result.session_id,
            "cost_usd": result.cost_usd,
            "usage": result.usage,
            "effective_cwd": workdir,
            "effective_cwd_source": harness_paths.source,
            "bot_workspace_dir": harness_paths.bot_workspace_dir,
            "project_dir": project_directory_payload(harness_paths.project_dir),
            "last_hints_sent": [hint_preview(hint) for hint in context_hints],
            "input_manifest": input_manifest.metadata(),
            **(result.metadata or {}),
        },
    }
    if persisted_tool_calls:
        assistant_msg["tool_calls"] = persisted_tool_calls
        if tool_envelopes:
            assistant_msg["_tool_envelopes"] = tool_envelopes
        assistant_msg["_tools_used"] = [
            call["function"]["name"] for call in persisted_tool_calls
        ]
    if assistant_turn_body:
        assistant_msg["_assistant_turn_body"] = assistant_turn_body
    synthetic_messages = [{
        "role": "user",
        "content": user_message,
    }, assistant_msg]
    try:
        async with async_session_factory() as db:
            await persist_turn_fn(
                db, session_id, bot, synthetic_messages, from_index=0,
                correlation_id=correlation_id,
                msg_metadata=msg_metadata,
                channel_id=channel_id,
                is_heartbeat=is_heartbeat,
                pre_user_msg_id=pre_user_msg_id,
                suppress_outbox=suppress_outbox,
            )
            from app.services.agent_harnesses.usage import record_harness_token_usage

            await record_harness_token_usage(
                db,
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot.id,
                runtime=bot.harness_runtime,
                model=harness_model,
                channel_id=channel_id,
                usage=result.usage if isinstance(result.usage, dict) else None,
                cost_usd=result.cost_usd,
            )
    except Exception:
        logger.exception(
            "harness '%s': persist_turn failed for session %s",
            bot.harness_runtime,
            session_id,
        )
        return final_text, "persist_turn failed"

    try:
        async with async_session_factory() as db:
            from app.services.agent_harnesses.session_state import (
                maybe_run_harness_auto_compaction,
            )

            await maybe_run_harness_auto_compaction(
                db,
                session_id,
                runtime=bot.harness_runtime,
                usage=result.usage if isinstance(result.usage, dict) else None,
            )
    except Exception:
        logger.exception(
            "harness '%s': auto-compaction check failed for session %s",
            bot.harness_runtime,
            session_id,
        )

    return final_text, None


async def mirror_harness_native_plan_state(
    *,
    session_id: uuid.UUID,
    runtime_name: str | None,
    result_metadata: dict,
    persisted_tool_calls: list[dict],
    async_session_factory=async_session,
) -> None:
    """Reflect runtime-native plan signals into Spindrel session plan state."""
    if not result_metadata and not persisted_tool_calls:
        return
    try:
        async with async_session_factory() as db:
            session = await db.get(SessionRow, session_id)
            if session is None:
                return
            changed = False
            if runtime_name == "codex" and metadata_has_codex_plan_signal(result_metadata):
                from app.services.session_plan_mode import (
                    enter_session_plan_mode,
                    get_session_plan_mode,
                    publish_session_plan_event,
                    update_planning_state,
                )

                if get_session_plan_mode(session) == "chat":
                    enter_session_plan_mode(session)
                    changed = True
                evidence = codex_plan_evidence(result_metadata)
                if evidence:
                    update_planning_state(
                        session,
                        evidence=evidence,
                        reason="codex_native_plan",
                    )
                    changed = True
                if changed:
                    await db.commit()
                    await db.refresh(session)
                    publish_session_plan_event(session, "codex_native_plan")
                return
    except Exception:
        logger.exception("harness native plan mirroring failed for session %s", session_id)


def metadata_has_codex_plan_signal(metadata: dict) -> bool:
    return any(
        key in metadata
        for key in ("codex_native_plan", "codex_native_plan_text", "codex_native_plan_delta")
    )


def codex_plan_evidence(metadata: dict) -> list[str]:
    text = metadata.get("codex_native_plan_text")
    if isinstance(text, str) and text.strip():
        return [f"Codex native plan: {text.strip()[:2000]}"]
    delta = metadata.get("codex_native_plan_delta")
    if isinstance(delta, str) and delta.strip():
        return [f"Codex native plan draft: {delta.strip()[:2000]}"]
    plan = metadata.get("codex_native_plan")
    if isinstance(plan, list):
        steps = []
        for item in plan[:8]:
            if isinstance(item, dict):
                step = str(item.get("step") or item.get("text") or "").strip()
                status = str(item.get("status") or "").strip()
                if step:
                    steps.append(f"{status}: {step}" if status else step)
        if steps:
            return ["Codex native plan steps: " + "; ".join(steps)]
    if isinstance(plan, dict):
        return [f"Codex native plan updated: {json.dumps(plan, sort_keys=True)[:2000]}"]
    return []


def tool_calls_include_exit_plan_mode(tool_calls: list[dict]) -> bool:
    for call in tool_calls:
        fn = call.get("function") if isinstance(call, dict) else None
        if isinstance(fn, dict) and fn.get("name") == "ExitPlanMode":
            return True
    return False


def _build_harness_plan_tool_hint(session_plan_mode: str):
    from app.services.agent_harnesses.base import HarnessContextHint

    if session_plan_mode == "planning":
        text = (
            "Spindrel plan mode is active. Use bridged Spindrel plan tools for "
            "canonical planning state: ask_plan_questions when more input is "
            "needed, and publish_plan for the structured plan artifact. Do not "
            "edit project files while drafting the plan."
        )
    elif session_plan_mode in {"executing", "blocked"}:
        text = (
            "Spindrel plan execution is active. Follow the accepted plan, use "
            "record_plan_progress before ending an execution turn, and use "
            "request_plan_replan if the accepted plan is stale."
        )
    else:
        return None
    return HarnessContextHint(
        kind="session_plan_mode",
        source="spindrel",
        created_at=datetime.now(timezone.utc).isoformat(),
        consume_after_next_turn=False,
        text=text,
    )


async def start_harness_turn_with_cancel(
    *,
    runtime,
    ctx,
    prompt: str,
    emit: ChannelEventEmitter,
    session_id: uuid.UUID,
):
    """Run a harness turn while honoring the shared session cancel flag."""
    task = asyncio.create_task(
        runtime.start_turn(ctx=ctx, prompt=prompt, emit=emit),
        name=f"harness-turn:{session_id}",
    )
    try:
        while True:
            done, _pending = await asyncio.wait({task}, timeout=0.2)
            if task in done:
                return task.result()
            if session_locks.is_cancel_requested(session_id):
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                raise HarnessTurnCancelled()
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


async def load_prior_harness_session_id(session_id: uuid.UUID) -> str | None:
    """Return the most recent harness-native session id for this Spindrel session."""
    from sqlalchemy import select
    from app.db.models import Message as MessageRow
    from app.services.agent_harnesses.session_state import load_resume_reset_at

    async with async_session() as db:
        reset_at = await load_resume_reset_at(db, session_id)
        rows = (
            await db.execute(
                select(MessageRow.metadata_, MessageRow.created_at)
                .where(MessageRow.session_id == session_id)
                .where(MessageRow.role == "assistant")
                .order_by(MessageRow.created_at.desc())
                .limit(50)
            )
        ).all()
    for meta, created_at in rows:
        if reset_at is not None and created_at is not None:
            try:
                if created_at <= reset_at:
                    continue
            except TypeError:
                if created_at.replace(tzinfo=timezone.utc) <= reset_at:
                    continue
        if not isinstance(meta, dict):
            continue
        harness = meta.get("harness")
        if not isinstance(harness, dict):
            continue
        sid = harness.get("session_id")
        if sid:
            return str(sid)
    return None


async def persist_harness_failure(
    *,
    channel_id: uuid.UUID | None,
    session_id: uuid.UUID,
    turn_id: uuid.UUID,
    bot: BotConfig,
    user_message: str,
    correlation_id: uuid.UUID,
    msg_metadata: dict | None,
    pre_user_msg_id: uuid.UUID | None,
    suppress_outbox: bool,
    error_text: str,
    prior_session_id: str | None,
    is_heartbeat: bool = False,
    async_session_factory=async_session,
    persist_turn_fn: Callable[..., Awaitable[Any]] = persist_turn,
) -> tuple[str, str]:
    """Persist a turn-error assistant row when the harness cannot run at all."""
    synthetic_messages: list[dict] = [
        {"role": "user", "content": user_message},
        {
            "role": "assistant",
            "content": build_turn_failure_message(error_text, ""),
            "_turn_error": True,
            "_turn_error_message": error_text,
            "_harness": {
                "runtime": bot.harness_runtime,
                "session_id": prior_session_id,
                "error": error_text,
            },
        },
    ]
    try:
        async with async_session_factory() as db:
            await persist_turn_fn(
                db, session_id, bot, synthetic_messages, from_index=0,
                correlation_id=correlation_id,
                msg_metadata=msg_metadata,
                channel_id=channel_id,
                is_heartbeat=is_heartbeat,
                pre_user_msg_id=pre_user_msg_id,
                suppress_outbox=suppress_outbox,
            )
    except Exception:
        logger.exception(
            "harness '%s': failed to persist pre-flight error row for session %s",
            bot.harness_runtime, session_id,
        )
    logger.error("harness pre-flight failure for bot %s: %s", bot.id, error_text)
    return "", error_text
