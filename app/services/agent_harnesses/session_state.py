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

from app.db.models import Message, Session
from app.services.agent_harnesses.base import HarnessContextHint

HARNESS_CONTEXT_HINTS_KEY = "harness_context_hints"
HARNESS_RESUME_RESET_AT_KEY = "harness_resume_reset_at"
HARNESS_LAST_COMPACT_SUMMARY_KEY = "harness_last_compact_summary"
HARNESS_BRIDGE_STATUS_KEY = "harness_bridge_status"

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
