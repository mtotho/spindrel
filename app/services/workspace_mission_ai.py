"""AI assistance for Mission Control.

This module owns the assistant layer: grounded operator briefs, persisted draft
missions, and the human-approved path from draft to real mission.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot, list_bots
from app.config import settings
from app.db.models import (
    Channel,
    Task,
    WorkspaceMissionControlBrief,
    WorkspaceMissionDraft,
)
from app.domain.errors import NotFoundError, ValidationError
from app.services.channels import apply_channel_visibility
from app.services.providers import get_llm_client
from app.services.workspace_mission_control import build_mission_control
from app.services.workspace_missions import create_mission, normalize_mission_recurrence, serialize_mission


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _bot_name(bot_id: str | None) -> str | None:
    if not bot_id:
        return None
    try:
        bot = get_bot(bot_id)
        return getattr(bot, "name", None) or getattr(bot, "display_name", None) or bot_id
    except Exception:
        return bot_id


def _resolve_model() -> tuple[str, str | None]:
    model = (
        settings.MISSION_CONTROL_AI_MODEL
        or settings.PROMPT_GENERATION_MODEL
        or settings.COMPACTION_MODEL
        or settings.DEFAULT_MODEL
    )
    if not model:
        raise ValidationError(
            "No model configured for Mission Control AI. Set MISSION_CONTROL_AI_MODEL, "
            "PROMPT_GENERATION_MODEL, COMPACTION_MODEL, or DEFAULT_MODEL."
        )
    provider_id = (
        settings.MISSION_CONTROL_AI_MODEL_PROVIDER_ID
        or settings.PROMPT_GENERATION_MODEL_PROVIDER_ID
        or settings.COMPACTION_MODEL_PROVIDER_ID
        or None
    )
    return model, provider_id


async def _visible_channels(db: AsyncSession, auth: Any) -> list[Channel]:
    return list((await db.execute(apply_channel_visibility(select(Channel), auth))).scalars().all())


async def _visible_channel_ids(db: AsyncSession, auth: Any) -> set[uuid.UUID]:
    return {channel.id for channel in await _visible_channels(db, auth)}


def _truncate(value: str | None, limit: int) -> str | None:
    if not value:
        return None
    text = value.strip()
    return text if len(text) <= limit else f"{text[:limit].rstrip()}..."


async def _recent_task_signals(db: AsyncSession, auth: Any, limit: int = 30) -> list[dict[str, Any]]:
    visible = await _visible_channel_ids(db, auth)
    stmt = (
        select(Task)
        .where(or_(Task.channel_id.is_(None), Task.channel_id.in_(visible)))
        .order_by(desc(Task.created_at))
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    channel_by_id = {channel.id: channel for channel in await _visible_channels(db, auth)}
    signals: list[dict[str, Any]] = []
    for task in rows:
        channel = channel_by_id.get(task.channel_id) if task.channel_id else None
        signals.append({
            "id": str(task.id),
            "title": task.title,
            "task_type": task.task_type,
            "status": task.status,
            "bot_id": task.bot_id,
            "bot_name": _bot_name(task.bot_id),
            "channel_id": str(task.channel_id) if task.channel_id else None,
            "channel_name": channel.name if channel else None,
            "scheduled_at": _iso(task.scheduled_at),
            "completed_at": _iso(task.completed_at),
            "created_at": _iso(task.created_at),
            "error": _truncate(task.error, 900),
            "result": _truncate(task.result, 900),
            "prompt": _truncate(task.prompt, 900),
        })
    return signals


async def _channel_signals(db: AsyncSession, auth: Any) -> list[dict[str, Any]]:
    channels = await _visible_channels(db, auth)
    rows: list[dict[str, Any]] = []
    for channel in sorted(channels, key=lambda row: row.name.lower())[:40]:
        rows.append({
            "id": str(channel.id),
            "name": channel.name,
            "bot_id": channel.bot_id,
            "bot_name": _bot_name(channel.bot_id),
            "integration": channel.integration,
            "history_mode": channel.history_mode,
            "workspace_rag": bool(channel.workspace_rag),
            "prompt_excerpt": _truncate(channel.channel_prompt, 700),
            "workspace_file": channel.channel_prompt_workspace_file_path,
        })
    return rows


def _bot_signals() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bot in sorted(list_bots(), key=lambda row: row.name.lower())[:40]:
        rows.append({
            "id": bot.id,
            "name": bot.name,
            "model": getattr(bot, "model", None),
            "harness_runtime": getattr(bot, "harness_runtime", None),
            "skills": list(getattr(bot, "skill_ids", []) or [])[:12],
            "tools": list(getattr(bot, "local_tools", []) or [])[:16],
        })
    return rows


async def build_ai_grounding_context(
    db: AsyncSession,
    *,
    auth: Any,
    user_instruction: str | None = None,
) -> dict[str, Any]:
    control = await build_mission_control(db, auth=auth, include_completed=False, limit=80)
    recent_tasks = await _recent_task_signals(db, auth)
    channel_rows = await _channel_signals(db, auth)
    draft_rows = await list_mission_drafts(db, auth=auth, include_inactive=True, limit=20)
    return {
        "generated_at": _iso(_now()),
        "user_instruction": (user_instruction or "").strip() or None,
        "rule": "Attention items are noisy. Treat them as weak hints unless supported by tasks, mission history, channel context, or spatial state.",
        "mission_control": {
            "summary": control.get("summary", {}),
            "missions": control.get("missions", [])[:20],
            "lanes": [
                {
                    "bot_id": lane.get("bot_id"),
                    "bot_name": lane.get("bot_name"),
                    "missions": [
                        {
                            "mission": row.get("mission"),
                            "spatial_advisory": row.get("spatial_advisory"),
                            "latest_update": row.get("latest_update"),
                        }
                        for row in lane.get("missions", [])[:6]
                    ],
                    "nearest_objects": lane.get("nearest_objects", [])[:5],
                    "attention_signals": lane.get("attention_signals", [])[:4],
                    "warning_count": lane.get("warning_count", 0),
                }
                for lane in control.get("lanes", [])[:20]
            ],
            "recent_updates": control.get("recent_updates", [])[:20],
            "unassigned_attention": control.get("unassigned_attention", [])[:12],
        },
        "recent_tasks_and_heartbeats": recent_tasks,
        "channels": channel_rows,
        "bots": _bot_signals(),
        "existing_drafts": draft_rows,
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise ValidationError("Mission Control AI did not return JSON.")
        parsed = json.loads(stripped[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValidationError("Mission Control AI returned an invalid response.")
    return parsed


def _coerce_confidence(value: Any) -> str:
    text = str(value or "medium").lower()
    return text if text in {"low", "medium", "high"} else "medium"


def _coerce_scope(value: Any) -> str:
    text = str(value or "workspace").lower()
    return text if text in {"workspace", "channel"} else "workspace"


def _coerce_interval_kind(value: Any, recurrence: str | None) -> str:
    text = str(value or ("manual" if not recurrence else "preset")).lower()
    return text if text in {"manual", "preset", "custom"} else "preset"


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _prompt_messages(context: dict[str, Any]) -> list[dict[str, str]]:
    system_msg = (
        "You are Mission Control for an agent workspace. Produce a grounded operator brief "
        "and 2-5 draft missions that a human can approve. Be concrete, operational, and "
        "skeptical of noisy attention alerts. Prefer evidence from recent task outcomes, "
        "mission progress, channel configuration, bot capabilities, and spatial readiness. "
        "Do not claim a mission has started. Return JSON only."
    )
    user_msg = (
        "Workspace grounding JSON follows. Return this exact JSON shape:\n"
        "{\n"
        '  "brief": {"summary": "...", "next_focus": "...", "confidence": "low|medium|high"},\n'
        '  "drafts": [\n'
        '    {"title": "...", "directive": "...", "rationale": "...", "scope": "workspace|channel", '
        '"bot_id": "existing bot id or null", "target_channel_id": "existing channel id or null", '
        '"interval_kind": "manual|preset|custom", "recurrence": null or "+4h"}\n'
        "  ]\n"
        "}\n\n"
        f"{json.dumps(context, default=str)[:50000]}"
    )
    return [{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}]


async def generate_mission_control_drafts(
    db: AsyncSession,
    *,
    auth: Any,
    actor: str | None,
    user_instruction: str | None = None,
) -> dict[str, Any]:
    model, provider_id = _resolve_model()
    context = await build_ai_grounding_context(db, auth=auth, user_instruction=user_instruction)
    client = get_llm_client(provider_id)
    resp = await client.chat.completions.create(
        model=model,
        messages=_prompt_messages(context),
        temperature=settings.MISSION_CONTROL_AI_TEMPERATURE,
        max_tokens=2400,
    )
    text = (resp.choices[0].message.content or "").strip()
    parsed = _extract_json_object(text)
    brief_data = parsed.get("brief") if isinstance(parsed.get("brief"), dict) else {}
    brief = WorkspaceMissionControlBrief(
        summary=str(brief_data.get("summary") or "Mission Control refreshed.").strip()[:4000],
        next_focus=str(brief_data.get("next_focus") or "").strip()[:2000],
        confidence=_coerce_confidence(brief_data.get("confidence")),
        user_instruction=(user_instruction or "").strip() or None,
        grounding_summary={
            "tasks": len(context.get("recent_tasks_and_heartbeats", [])),
            "channels": len(context.get("channels", [])),
            "bots": len(context.get("bots", [])),
            "active_missions": context.get("mission_control", {}).get("summary", {}).get("active_missions", 0),
            "attention_treated_as": "weak_hint",
        },
        raw_response=parsed,
        ai_model=model,
        ai_provider_id=provider_id,
        created_by=actor,
        created_at=_now(),
    )
    db.add(brief)

    visible_channel_ids = await _visible_channel_ids(db, auth)
    known_bot_ids = {bot.id for bot in list_bots()}
    drafts: list[WorkspaceMissionDraft] = []
    for item in (parsed.get("drafts") if isinstance(parsed.get("drafts"), list) else [])[:5]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        directive = str(item.get("directive") or "").strip()
        if not title or not directive:
            continue
        channel_id = _uuid_or_none(item.get("target_channel_id"))
        if channel_id and channel_id not in visible_channel_ids:
            channel_id = None
        recurrence = str(item.get("recurrence") or "").strip() or None
        interval_kind = _coerce_interval_kind(item.get("interval_kind"), recurrence)
        if interval_kind == "manual":
            recurrence = None
        else:
            try:
                interval_kind, recurrence = normalize_mission_recurrence(recurrence, interval_kind)
            except ValidationError:
                interval_kind, recurrence = "preset", "+4h"
        bot_id = str(item.get("bot_id") or "").strip() or None
        if bot_id and bot_id not in known_bot_ids:
            bot_id = None
        scope = _coerce_scope(item.get("scope"))
        if scope == "channel" and channel_id is None:
            scope = "workspace"
        draft = WorkspaceMissionDraft(
            status="draft",
            source="ai",
            title=title[:500],
            directive=directive[:12000],
            rationale=str(item.get("rationale") or "").strip()[:4000] or None,
            scope=scope,
            bot_id=bot_id,
            target_channel_id=channel_id if scope == "channel" else None,
            interval_kind=interval_kind,
            recurrence=recurrence,
            grounding_summary=brief.grounding_summary,
            ai_model=model,
            ai_provider_id=provider_id,
            ai_response=item,
            user_instruction=(user_instruction or "").strip() or None,
            created_by=actor,
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(draft)
        drafts.append(draft)
    await db.commit()
    await db.refresh(brief)
    for draft in drafts:
        await db.refresh(draft)
    return {
        "assistant_brief": await serialize_brief(brief),
        "drafts": [await serialize_draft(db, draft) for draft in drafts],
    }


async def serialize_brief(brief: WorkspaceMissionControlBrief | None) -> dict[str, Any] | None:
    if brief is None:
        return None
    return {
        "id": str(brief.id),
        "summary": brief.summary,
        "next_focus": brief.next_focus,
        "confidence": brief.confidence,
        "user_instruction": brief.user_instruction,
        "grounding_summary": brief.grounding_summary or {},
        "ai_model": brief.ai_model,
        "ai_provider_id": brief.ai_provider_id,
        "created_by": brief.created_by,
        "created_at": _iso(brief.created_at),
    }


async def serialize_draft(db: AsyncSession, draft: WorkspaceMissionDraft) -> dict[str, Any]:
    channel = await db.get(Channel, draft.target_channel_id) if draft.target_channel_id else None
    return {
        "id": str(draft.id),
        "status": draft.status,
        "source": draft.source,
        "title": draft.title,
        "directive": draft.directive,
        "rationale": draft.rationale,
        "scope": draft.scope,
        "bot_id": draft.bot_id,
        "bot_name": _bot_name(draft.bot_id),
        "target_channel_id": str(draft.target_channel_id) if draft.target_channel_id else None,
        "target_channel_name": channel.name if channel else None,
        "interval_kind": draft.interval_kind,
        "recurrence": draft.recurrence,
        "model_override": draft.model_override,
        "model_provider_id_override": draft.model_provider_id_override,
        "harness_effort": draft.harness_effort,
        "grounding_summary": draft.grounding_summary or {},
        "ai_model": draft.ai_model,
        "ai_provider_id": draft.ai_provider_id,
        "user_instruction": draft.user_instruction,
        "accepted_mission_id": str(draft.accepted_mission_id) if draft.accepted_mission_id else None,
        "created_by": draft.created_by,
        "created_at": _iso(draft.created_at),
        "updated_at": _iso(draft.updated_at),
    }


async def latest_mission_control_brief(db: AsyncSession) -> dict[str, Any] | None:
    row = (await db.execute(
        select(WorkspaceMissionControlBrief)
        .order_by(desc(WorkspaceMissionControlBrief.created_at))
        .limit(1)
    )).scalar_one_or_none()
    return await serialize_brief(row)


async def list_mission_drafts(
    db: AsyncSession,
    *,
    auth: Any,
    include_inactive: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    visible = await _visible_channel_ids(db, auth)
    stmt = select(WorkspaceMissionDraft).where(
        or_(WorkspaceMissionDraft.target_channel_id.is_(None), WorkspaceMissionDraft.target_channel_id.in_(visible))
    )
    if not include_inactive:
        stmt = stmt.where(WorkspaceMissionDraft.status == "draft")
    stmt = stmt.order_by(desc(WorkspaceMissionDraft.updated_at)).limit(max(1, min(limit, 100)))
    rows = list((await db.execute(stmt)).scalars().all())
    return [await serialize_draft(db, row) for row in rows]


async def _get_visible_draft(db: AsyncSession, draft_id: uuid.UUID, *, auth: Any) -> WorkspaceMissionDraft:
    visible = await _visible_channel_ids(db, auth)
    row = await db.get(WorkspaceMissionDraft, draft_id)
    if row is None or (row.target_channel_id and row.target_channel_id not in visible):
        raise NotFoundError("Mission draft not found.")
    return row


async def update_mission_draft(
    db: AsyncSession,
    draft_id: uuid.UUID,
    *,
    auth: Any,
    title: str | None = None,
    directive: str | None = None,
    rationale: str | None = None,
    scope: str | None = None,
    bot_id: str | None = None,
    target_channel_id: uuid.UUID | None = None,
    interval_kind: str | None = None,
    recurrence: str | None = None,
    model_override: str | None = None,
    model_provider_id_override: str | None = None,
    harness_effort: str | None = None,
) -> WorkspaceMissionDraft:
    draft = await _get_visible_draft(db, draft_id, auth=auth)
    if draft.status != "draft":
        raise ValidationError("Only draft suggestions can be edited.")
    if title is not None:
        if not title.strip():
            raise ValidationError("Mission title is required.")
        draft.title = title.strip()[:500]
    if directive is not None:
        if not directive.strip():
            raise ValidationError("Mission directive is required.")
        draft.directive = directive.strip()[:12000]
    if rationale is not None:
        draft.rationale = rationale.strip()[:4000] or None
    if scope is not None:
        draft.scope = _coerce_scope(scope)
    if bot_id is not None:
        bot_id = bot_id.strip() or None
        if bot_id:
            try:
                get_bot(bot_id)
            except Exception as exc:
                raise ValidationError(f"Unknown bot: {bot_id}") from exc
        draft.bot_id = bot_id
    if target_channel_id is not None:
        visible = await _visible_channel_ids(db, auth)
        if target_channel_id not in visible:
            raise NotFoundError("Channel not found.")
        draft.target_channel_id = target_channel_id
        draft.scope = "channel"
    if scope == "workspace":
        draft.target_channel_id = None
    if interval_kind is not None or recurrence is not None:
        kind, normalized = normalize_mission_recurrence(recurrence if recurrence is not None else draft.recurrence, interval_kind or draft.interval_kind)
        draft.interval_kind = kind
        draft.recurrence = normalized
    if model_override is not None:
        draft.model_override = model_override.strip() or None
    if model_provider_id_override is not None:
        draft.model_provider_id_override = model_provider_id_override.strip() or None
    if harness_effort is not None:
        draft.harness_effort = harness_effort.strip() or None
    draft.updated_at = _now()
    await db.commit()
    await db.refresh(draft)
    return draft


async def dismiss_mission_draft(
    db: AsyncSession,
    draft_id: uuid.UUID,
    *,
    auth: Any,
) -> WorkspaceMissionDraft:
    draft = await _get_visible_draft(db, draft_id, auth=auth)
    if draft.status != "draft":
        raise ValidationError("Only draft suggestions can be dismissed.")
    draft.status = "dismissed"
    draft.updated_at = _now()
    await db.commit()
    await db.refresh(draft)
    return draft


async def accept_mission_draft(
    db: AsyncSession,
    draft_id: uuid.UUID,
    *,
    auth: Any,
    actor: str,
) -> dict[str, Any]:
    draft = await _get_visible_draft(db, draft_id, auth=auth)
    if draft.status != "draft":
        raise ValidationError("Only draft suggestions can be accepted.")
    mission = await create_mission(
        db,
        auth=auth,
        actor=actor,
        title=draft.title,
        directive=draft.directive,
        scope=draft.scope,
        channel_id=draft.target_channel_id if draft.scope == "channel" else None,
        bot_id=draft.bot_id,
        interval_kind=draft.interval_kind,
        recurrence=draft.recurrence,
        model_override=draft.model_override,
        model_provider_id_override=draft.model_provider_id_override,
        harness_effort=draft.harness_effort,
        history_mode="recent",
        history_recent_count=8,
    )
    mission_id = mission.id
    draft = await db.get(WorkspaceMissionDraft, draft_id)
    if draft is not None:
        draft.status = "accepted"
        draft.accepted_mission_id = mission_id
        draft.updated_at = _now()
        await db.commit()
        await db.refresh(draft)
    mission = await db.get(type(mission), mission_id) or mission
    return {
        "draft": await serialize_draft(db, draft) if draft else None,
        "mission": await serialize_mission(db, mission, include_updates=20),
    }
