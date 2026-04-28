"""Per-session harness state that is not owned by a runtime SDK.

The external harness owns its native transcript and resume id. Spindrel owns
session-scoped host state around it: one-shot context hints, manual compact
reset markers, and lightweight status summaries for the chat UI.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import Message, Session, TraceEvent
from app.services.agent_harnesses.base import HarnessContextHint

HARNESS_CONTEXT_HINTS_KEY = "harness_context_hints"
HARNESS_RESUME_RESET_AT_KEY = "harness_resume_reset_at"
HARNESS_LAST_COMPACT_SUMMARY_KEY = "harness_last_compact_summary"
HARNESS_BRIDGE_STATUS_KEY = "harness_bridge_status"
HARNESS_NATIVE_COMPACTION_KEY = "harness_native_compaction"

MAX_HINTS = 8
MAX_HINT_CHARS = 12_000
MAX_COMPACT_MESSAGES = 40


@dataclass(frozen=True)
class HarnessStatus:
    session_id: uuid.UUID
    runtime: str | None = None
    harness_session_id: str | None = None
    model: str | None = None
    effort: str | None = None
    permission_mode: str | None = None
    pending_hint_count: int = 0
    last_compacted_at: str | None = None
    last_turn_at: str | None = None
    usage: dict[str, Any] | None = None
    cost_usd: float | None = None
    context_window_tokens: int | None = None
    context_remaining_pct: float | None = None
    native_compaction: dict[str, Any] | None = None
    context_note: str = "Native harness context is provider-managed; Spindrel tracks resume id, compact resets, and pending host hints."


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hint_from_dict(raw: dict[str, Any]) -> HarnessContextHint | None:
    kind = raw.get("kind")
    text = raw.get("text")
    created_at = raw.get("created_at")
    if not isinstance(kind, str) or not isinstance(text, str):
        return None
    return HarnessContextHint(
        kind=kind,
        text=text,
        created_at=created_at if isinstance(created_at, str) else _now_iso(),
        source=raw.get("source") if isinstance(raw.get("source"), str) else None,
        consume_after_next_turn=bool(raw.get("consume_after_next_turn", True)),
    )


def _hint_to_dict(hint: HarnessContextHint) -> dict[str, Any]:
    return {
        "kind": hint.kind,
        "text": hint.text[:MAX_HINT_CHARS],
        "created_at": hint.created_at,
        "source": hint.source,
        "consume_after_next_turn": hint.consume_after_next_turn,
    }


def hint_preview(hint: HarnessContextHint, *, limit: int = 260) -> dict[str, Any]:
    text = " ".join((hint.text or "").split())
    if len(text) > limit:
        text = text[:limit].rstrip() + "..."
    return {
        "kind": hint.kind,
        "source": hint.source,
        "created_at": hint.created_at,
        "consume_after_next_turn": hint.consume_after_next_turn,
        "preview": text,
    }


async def set_bridge_status(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    status: str,
    exported_tools: list[str] | tuple[str, ...] = (),
    ignored_client_tools: list[str] | tuple[str, ...] = (),
    explicit_tool_names: list[str] | tuple[str, ...] = (),
    tagged_skill_ids: list[str] | tuple[str, ...] = (),
    inventory_errors: list[str] | tuple[str, ...] = (),
    error: str | None = None,
) -> dict[str, Any]:
    session = await db.get(Session, session_id)
    if session is None:
        return {}
    payload = {
        "status": status,
        "exported_tools": list(exported_tools),
        "exported_tool_count": len(exported_tools),
        "ignored_client_tools": list(ignored_client_tools),
        "ignored_client_tool_count": len(ignored_client_tools),
        "explicit_tool_names": list(explicit_tool_names),
        "tagged_skill_ids": list(tagged_skill_ids),
        "inventory_errors": list(inventory_errors),
        "error": error,
        "updated_at": _now_iso(),
    }
    meta = dict(session.metadata_ or {})
    meta[HARNESS_BRIDGE_STATUS_KEY] = payload
    session.metadata_ = meta
    flag_modified(session, "metadata_")
    await db.commit()
    return payload


async def load_bridge_status(
    db: AsyncSession,
    session_id: uuid.UUID,
) -> dict[str, Any]:
    session = await db.get(Session, session_id)
    if session is None:
        return {}
    raw = (session.metadata_ or {}).get(HARNESS_BRIDGE_STATUS_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


async def add_context_hint(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    kind: str,
    text: str,
    source: str | None = None,
    consume_after_next_turn: bool = True,
) -> HarnessContextHint:
    session = await db.get(Session, session_id)
    if session is None:
        raise ValueError(f"session not found: {session_id}")

    hint = HarnessContextHint(
        kind=kind.strip() or "hint",
        text=(text or "").strip()[:MAX_HINT_CHARS],
        created_at=_now_iso(),
        source=source,
        consume_after_next_turn=consume_after_next_turn,
    )
    meta = dict(session.metadata_ or {})
    raw_hints = list(meta.get(HARNESS_CONTEXT_HINTS_KEY) or [])
    raw_hints.append(_hint_to_dict(hint))
    meta[HARNESS_CONTEXT_HINTS_KEY] = raw_hints[-MAX_HINTS:]
    session.metadata_ = meta
    flag_modified(session, "metadata_")
    await db.commit()
    return hint


async def load_context_hints(
    db: AsyncSession, session_id: uuid.UUID
) -> tuple[HarnessContextHint, ...]:
    session = await db.get(Session, session_id)
    if session is None:
        return ()
    raw = (session.metadata_ or {}).get(HARNESS_CONTEXT_HINTS_KEY) or []
    hints: list[HarnessContextHint] = []
    for item in raw:
        if isinstance(item, dict) and (hint := _hint_from_dict(item)):
            hints.append(hint)
    return tuple(hints)


async def clear_consumed_context_hints(
    db: AsyncSession, session_id: uuid.UUID
) -> int:
    session = await db.get(Session, session_id)
    if session is None:
        return 0
    meta = dict(session.metadata_ or {})
    raw = list(meta.get(HARNESS_CONTEXT_HINTS_KEY) or [])
    kept: list[dict[str, Any]] = []
    removed = 0
    for item in raw:
        if not isinstance(item, dict):
            continue
        hint = _hint_from_dict(item)
        if hint is None:
            continue
        if hint.consume_after_next_turn:
            removed += 1
        else:
            kept.append(_hint_to_dict(hint))
    if kept:
        meta[HARNESS_CONTEXT_HINTS_KEY] = kept
    else:
        meta.pop(HARNESS_CONTEXT_HINTS_KEY, None)
    session.metadata_ = meta
    flag_modified(session, "metadata_")
    await db.commit()
    return removed


async def set_resume_reset(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    summary: str,
) -> str:
    session = await db.get(Session, session_id)
    if session is None:
        raise ValueError(f"session not found: {session_id}")
    reset_at = _now_iso()
    meta = dict(session.metadata_ or {})
    meta[HARNESS_RESUME_RESET_AT_KEY] = reset_at
    meta[HARNESS_LAST_COMPACT_SUMMARY_KEY] = summary[:MAX_HINT_CHARS]
    session.metadata_ = meta
    flag_modified(session, "metadata_")
    await db.commit()
    return reset_at


async def load_resume_reset_at(
    db: AsyncSession, session_id: uuid.UUID
) -> datetime | None:
    session = await db.get(Session, session_id)
    if session is None:
        return None
    raw = (session.metadata_ or {}).get(HARNESS_RESUME_RESET_AT_KEY)
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


async def build_compact_summary(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    limit: int = MAX_COMPACT_MESSAGES,
) -> str:
    rows = (
        await db.execute(
            select(Message.role, Message.content, Message.created_at)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
    ).all()
    parts: list[str] = [
        "Spindrel compacted this harness session. Continue from this summary; do not assume the native harness resume thread still contains earlier details.",
        "",
    ]
    for role, content, created_at in reversed(rows):
        text = (content or "").strip()
        if not text:
            continue
        if len(text) > 1200:
            text = text[:1200].rstrip() + "..."
        ts = created_at.isoformat() if hasattr(created_at, "isoformat") else ""
        parts.append(f"[{role} {ts}] {text}")
    return "\n".join(parts).strip()[:MAX_HINT_CHARS]


async def compact_harness_session(
    db: AsyncSession,
    session_id: uuid.UUID,
) -> str:
    summary = await build_compact_summary(db, session_id)
    await set_resume_reset(db, session_id, summary=summary)
    await add_context_hint(
        db,
        session_id,
        kind="compact_summary",
        text=summary,
        source="/compact",
        consume_after_next_turn=True,
    )
    return summary


async def load_latest_harness_metadata(
    db: AsyncSession,
    session_id: uuid.UUID,
) -> tuple[dict[str, Any] | None, datetime | None]:
    reset_at = await load_resume_reset_at(db, session_id)
    stmt = (
        select(Message.metadata_, Message.created_at)
        .where(Message.session_id == session_id)
        .where(Message.role == "assistant")
        .order_by(Message.created_at.desc())
        .limit(50)
    )
    for meta, created_at in (await db.execute(stmt)).all():
        if reset_at is not None and created_at is not None:
            try:
                if created_at <= reset_at:
                    continue
            except TypeError:
                if created_at.replace(tzinfo=timezone.utc) <= reset_at:
                    continue
        if isinstance(meta, dict) and isinstance(meta.get("harness"), dict):
            return dict(meta["harness"]), created_at
    return None, None


def _usage_total_tokens(usage: dict[str, Any] | None) -> int | None:
    if not isinstance(usage, dict):
        return None
    for key in (
        "context_tokens",
        "context_total_tokens",
        "last_total_tokens",
    ):
        value = usage.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
    total = 0
    found = False
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "cached_tokens",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    ):
        value = usage.get(key)
        if isinstance(value, (int, float)) and value > 0:
            if key == "total_tokens":
                return int(value)
            total += int(value)
            found = True
    return total if found else None


def normalize_context_usage(
    usage: dict[str, Any] | None,
    *,
    runtime: str | None = None,
    context_window_tokens: int | None = None,
    source: str = "last_turn",
) -> dict[str, Any]:
    """Normalize provider usage into a context-footprint estimate.

    Harness runtimes expose different usage shapes. Some fields are current
    prompt/context footprint, while others are billing or cumulative thread
    totals. The UI should only treat high/medium confidence estimates as
    actionable pressure; low confidence data is still useful for traces.
    """
    snapshot: dict[str, Any] = {
        "runtime": runtime,
        "source": source,
        "confidence": "none",
        "context_window_tokens": context_window_tokens,
        "context_tokens": None,
        "remaining_pct": None,
        "source_fields": [],
        "reason": "no usage reported",
        "raw_usage": usage if isinstance(usage, dict) else None,
    }
    if not isinstance(usage, dict) or not usage:
        return snapshot

    for key in ("context_remaining_pct", "context_remaining_percent", "remaining_pct"):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            remaining = round(max(0.0, min(100.0, float(value))), 1)
            snapshot.update(
                {
                    "confidence": "high",
                    "remaining_pct": remaining,
                    "source_fields": [key],
                    "reason": "provider reported remaining context directly",
                }
            )
            if context_window_tokens and context_window_tokens > 0:
                snapshot["context_tokens"] = int(
                    round(context_window_tokens * (1.0 - remaining / 100.0))
                )
            return snapshot

    for key in ("context_tokens", "context_total_tokens", "last_total_tokens"):
        value = usage.get(key)
        if isinstance(value, (int, float)) and value > 0:
            tokens = int(value)
            snapshot.update(
                {
                    "confidence": "high",
                    "context_tokens": tokens,
                    "source_fields": [key],
                    "reason": f"using normalized {key}",
                }
            )
            break

    if snapshot["context_tokens"] is None:
        # Provider turn input is the closest cross-runtime proxy for active
        # prompt footprint. Include generated output when present because it
        # becomes part of the resumable transcript, but do not add cache-read
        # or historical total fields here; those are commonly billing/cumulative
        # and caused false 0-40% context readings after compaction.
        input_key = "input_tokens" if isinstance(usage.get("input_tokens"), (int, float)) else "prompt_tokens"
        input_value = usage.get(input_key)
        output_key = "output_tokens" if isinstance(usage.get("output_tokens"), (int, float)) else "completion_tokens"
        output_value = usage.get(output_key)
        if isinstance(input_value, (int, float)) and input_value > 0:
            tokens = int(input_value)
            fields = [input_key]
            if isinstance(output_value, (int, float)) and output_value > 0:
                tokens += int(output_value)
                fields.append(output_key)
            snapshot.update(
                {
                    "confidence": "medium",
                    "context_tokens": tokens,
                    "source_fields": fields,
                    "reason": "estimated from provider turn input/output tokens",
                }
            )

    if snapshot["context_tokens"] is None:
        total = usage.get("total_tokens")
        if isinstance(total, (int, float)) and total > 0:
            snapshot.update(
                {
                    "confidence": "low",
                    "context_tokens": int(total),
                    "source_fields": ["total_tokens"],
                    "reason": "total_tokens may be billing or cumulative, not active context",
                }
            )

    tokens = snapshot.get("context_tokens")
    if isinstance(tokens, int) and tokens > 0 and context_window_tokens and context_window_tokens > 0:
        remaining = max(0.0, 1.0 - (float(tokens) / float(context_window_tokens)))
        snapshot["remaining_pct"] = round(remaining * 100.0, 1)
    return snapshot


def estimate_context_remaining_pct(
    usage: dict[str, Any] | None,
    *,
    context_window_tokens: int | None,
) -> float | None:
    snapshot = normalize_context_usage(
        usage,
        context_window_tokens=context_window_tokens,
    )
    if snapshot.get("confidence") == "low":
        return None
    value = snapshot.get("remaining_pct")
    return float(value) if isinstance(value, (int, float)) else None


def estimate_native_compaction_remaining_pct(
    usage: dict[str, Any] | None,
    *,
    context_window_tokens: int | None,
) -> float | None:
    """Estimate remaining context immediately after a successful native compact.

    Some runtimes report compact telemetry as cumulative thread totals rather
    than the post-compact prompt footprint. Treat oversized totals as historical
    and fall back to "freshly compacted" instead of showing 0% remaining.
    """
    if not context_window_tokens or context_window_tokens <= 0:
        return None
    if not isinstance(usage, dict) or not usage:
        return 100.0

    for key in ("context_remaining_pct", "context_remaining_percent", "remaining_pct"):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            return round(max(0.0, min(100.0, float(value))), 1)

    last_total = usage.get("last_total_tokens")
    if isinstance(last_total, (int, float)) and last_total > 0:
        remaining = max(0.0, 1.0 - (float(last_total) / float(context_window_tokens)))
        return round(remaining * 100.0, 1)

    total = _usage_total_tokens(usage)
    if not total:
        return 100.0
    if total >= context_window_tokens:
        return 100.0
    remaining = max(0.0, 1.0 - (float(total) / float(context_window_tokens)))
    return round(remaining * 100.0, 1)


def context_window_from_usage(usage: dict[str, Any] | None) -> int | None:
    """Return provider-reported context window from normalized harness usage."""
    if not isinstance(usage, dict):
        return None
    for key in ("context_window_tokens", "model_context_window"):
        value = usage.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
    return None


def _context_snapshot(
    usage: dict[str, Any] | None,
    *,
    context_window_tokens: int | None,
    source: str,
    runtime: str | None = None,
) -> dict[str, Any]:
    snapshot = normalize_context_usage(
        usage,
        runtime=runtime,
        context_window_tokens=context_window_tokens,
        source=source,
    )
    return {
        **snapshot,
        "usage": usage if isinstance(usage, dict) else None,
    }


def _native_compaction_snapshot(
    usage: dict[str, Any] | None,
    *,
    context_window_tokens: int | None,
    source: str,
) -> dict[str, Any]:
    return {
        "source": source,
        "remaining_pct": estimate_native_compaction_remaining_pct(
            usage,
            context_window_tokens=context_window_tokens,
        ),
        "context_window_tokens": context_window_tokens,
        "usage": usage if isinstance(usage, dict) else None,
    }


def harness_compaction_settings(config: dict[str, Any] | None) -> dict[str, Any]:
    raw = (config or {}).get("harness_auto_compaction")
    if not isinstance(raw, dict):
        raw = {}
    return {
        "enabled": bool(raw.get("enabled", True)),
        "soft_remaining_pct": int(raw.get("soft_remaining_pct", 60) or 60),
        "hard_remaining_pct": int(raw.get("hard_remaining_pct", 10) or 10),
        "last_prompted_at": raw.get("last_prompted_at") if isinstance(raw.get("last_prompted_at"), str) else None,
        "last_hard_compact_at": raw.get("last_hard_compact_at") if isinstance(raw.get("last_hard_compact_at"), str) else None,
    }


async def record_native_compaction(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    runtime: str | None,
    result: Any,
    source: str,
) -> dict[str, Any]:
    session = await db.get(Session, session_id)
    if session is None:
        raise ValueError(f"session not found: {session_id}")
    status = "completed" if getattr(result, "ok", False) else "failed"
    result_metadata = getattr(result, "metadata", None) or {}
    after_context = result_metadata.get("context_after")
    if not isinstance(after_context, dict):
        after_context = _native_compaction_snapshot(
            getattr(result, "usage", None),
            context_window_tokens=context_window_from_usage(getattr(result, "usage", None)),
            source="native_compaction",
        )
    payload = {
        "status": status,
        "runtime": runtime,
        "source": source,
        "session_id": getattr(result, "session_id", None),
        "detail": getattr(result, "detail", "") or "",
        "usage": getattr(result, "usage", None),
        "error": getattr(result, "error", None),
        "metadata": result_metadata,
        "context_before": result_metadata.get("context_before") if isinstance(result_metadata.get("context_before"), dict) else None,
        "context_after": after_context,
        "trace_correlation_id": result_metadata.get("trace_correlation_id") if isinstance(result_metadata.get("trace_correlation_id"), str) else None,
        "created_at": _now_iso(),
    }
    meta = dict(session.metadata_ or {})
    meta[HARNESS_NATIVE_COMPACTION_KEY] = payload
    session.metadata_ = meta
    flag_modified(session, "metadata_")

    row = Message(
        session_id=session_id,
        role="assistant",
        content="Native compaction completed" if status == "completed" else "Native compaction failed",
        metadata_={
            "kind": "slash_command_result",
            "suppress_outbox": True,
            "slash_command": "compact",
            "result_type": "harness_native_compaction",
            "payload": {
                "session_id": str(session_id),
                "title": "Native compaction completed" if status == "completed" else "Native compaction failed",
                "detail": payload["detail"],
                "status": payload["status"],
                "usage": payload["usage"],
                "native_session_id": payload["session_id"],
                "error": payload["error"],
                "metadata": payload["metadata"],
                "context_before": payload["context_before"],
                "context_after": payload["context_after"],
                "trace_correlation_id": payload["trace_correlation_id"],
            },
            "harness_compaction": payload,
            "sender_type": "bot",
            "sender_id": f"bot:{session.bot_id}",
            "sender_display_name": runtime or "Harness",
        },
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.add(TraceEvent(
        correlation_id=uuid.UUID(payload["trace_correlation_id"]) if payload.get("trace_correlation_id") else None,
        session_id=session_id,
        bot_id=session.bot_id,
        client_id=session.client_id,
        event_type="harness_native_compaction",
        event_name=status,
        data={
            "runtime": runtime,
            "source": source,
            "native_session_id": payload["session_id"],
            "context_before": payload["context_before"],
            "context_after": payload["context_after"],
            "usage": payload["usage"],
            "error": payload["error"],
        },
        created_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    return payload


async def load_native_compaction(
    db: AsyncSession,
    session_id: uuid.UUID,
) -> dict[str, Any] | None:
    session = await db.get(Session, session_id)
    if session is None:
        return None
    raw = (session.metadata_ or {}).get(HARNESS_NATIVE_COMPACTION_KEY)
    return dict(raw) if isinstance(raw, dict) else None


async def run_native_harness_compact(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    source: str = "/compact",
) -> dict[str, Any]:
    from app.agent.bots import get_bot
    from app.db.engine import async_session
    from app.services.agent_harnesses import get_runtime
    from app.services.agent_harnesses.approvals import load_session_mode
    from app.services.agent_harnesses.context import build_turn_context
    from app.services.agent_harnesses.project import resolve_harness_paths
    from app.services.agent_harnesses.settings import load_session_settings

    session = await db.get(Session, session_id)
    if session is None:
        raise ValueError(f"session not found: {session_id}")
    bot = get_bot(session.bot_id)
    runtime_name = getattr(bot, "harness_runtime", None)
    if not runtime_name:
        raise ValueError("session bot is not a harness bot")
    runtime = get_runtime(runtime_name)
    compact = getattr(runtime, "compact_session", None)
    if compact is None:
        raise NotImplementedError(f"runtime {runtime_name} does not support native compaction")

    harness_paths = await resolve_harness_paths(
        db,
        channel_id=session.channel_id or session.parent_channel_id,
        bot=bot,
    )
    harness_meta, _last_turn_at = await load_latest_harness_metadata(db, session_id)
    prior_harness_session_id = (harness_meta or {}).get("session_id")
    prior_usage = (harness_meta or {}).get("usage") if isinstance(harness_meta, dict) else None
    prior_window = context_window_from_usage(prior_usage)
    context_before = _context_snapshot(
        prior_usage if isinstance(prior_usage, dict) else None,
        context_window_tokens=prior_window,
        source="last_turn",
        runtime=runtime_name,
    )
    permission_mode = await load_session_mode(db, session_id)
    settings = await load_session_settings(db, session_id)
    trace_correlation_id = uuid.uuid4()
    db.add(TraceEvent(
        correlation_id=trace_correlation_id,
        session_id=session_id,
        bot_id=bot.id,
        client_id=session.client_id,
        event_type="harness_native_compaction",
        event_name="started",
        data={
            "runtime": runtime_name,
            "source": source,
            "native_session_id": prior_harness_session_id,
            "context_before": context_before,
        },
        created_at=datetime.now(timezone.utc),
    ))
    await db.flush()

    ctx = build_turn_context(
        spindrel_session_id=session_id,
        channel_id=session.channel_id or session.parent_channel_id,
        bot_id=bot.id,
        turn_id=trace_correlation_id,
        workdir=harness_paths.workdir,
        harness_session_id=prior_harness_session_id,
        permission_mode=permission_mode,
        db_session_factory=async_session,
        model=settings.model,
        effort=settings.effort,
        runtime_settings=settings.runtime_settings,
    )
    result = await compact(ctx=ctx)
    result_metadata = dict(getattr(result, "metadata", None) or {})
    result_metadata.setdefault("trace_correlation_id", str(trace_correlation_id))
    result_metadata.setdefault("context_before", context_before)
    result_metadata.setdefault(
        "context_after",
        _native_compaction_snapshot(
            getattr(result, "usage", None),
            context_window_tokens=context_window_from_usage(getattr(result, "usage", None)) or prior_window,
            source="native_compaction",
        ),
    )
    try:
        result.metadata = result_metadata
    except Exception:
        pass
    return await record_native_compaction(
        db,
        session_id,
        runtime=runtime_name,
        result=result,
        source=source,
    )
