"""API v1 — rich Markdown Notes on top of channel/project knowledge bases."""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot
from app.db.models import Channel
from app.dependencies import get_db, require_scopes
from app.services.knowledge_documents import authorize_knowledge_document
from app.services.notes import (
    append_note_assist_exchange,
    build_ai_assist_proposal,
    create_note,
    get_or_create_note_session,
    list_notes,
    read_note,
    resolve_notes_surface,
    update_note_session_binding,
    write_note,
)

router = APIRouter(prefix="/channels/{channel_id}/notes", tags=["Notes"])


class NoteCreateBody(BaseModel):
    title: str
    slug: str | None = None
    content: str | None = None


class NoteWriteBody(BaseModel):
    content: str
    base_hash: str | None = None


class NoteSessionBindingBody(BaseModel):
    mode: str
    session_id: str | None = None


class NoteSelection(BaseModel):
    start: int
    end: int
    text: str


class NoteAssistBody(BaseModel):
    mode: str = "clarify_structure"
    instruction: str | None = None
    selection: NoteSelection | None = None
    base_hash: str | None = None
    content: str | None = None
    model_override: str | None = None
    model_provider_id_override: str | None = None


async def _require_channel(channel_id: uuid.UUID, db: AsyncSession) -> tuple[Channel, object]:
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    return channel, get_bot(channel.bot_id)


def _schedule_reindex(channel_id: str, bot):
    from app.services.bot_indexing import reindex_channel
    asyncio.create_task(reindex_channel(channel_id, bot, force=True))


@router.get("")
async def list_channel_notes(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("channels:read")),
):
    channel, bot = await _require_channel(channel_id, db)
    surface = await resolve_notes_surface(db, channel, bot)
    authorize_knowledge_document(auth, surface, "list")
    return {
        "surface": {"scope": surface.scope, "kb_path": surface.kb_rel, "notes_path": f"{surface.kb_rel}/notes"},
        "notes": list_notes(surface),
    }


@router.post("", status_code=201)
async def create_channel_note(
    channel_id: uuid.UUID,
    body: NoteCreateBody,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("channels:write")),
):
    channel, bot = await _require_channel(channel_id, db)
    surface = await resolve_notes_surface(db, channel, bot)
    authorize_knowledge_document(auth, surface, "write")
    note = create_note(surface, title=body.title, slug=body.slug, content=body.content)
    _schedule_reindex(str(channel_id), bot)
    return note


@router.get("/{slug}")
async def get_channel_note(
    channel_id: uuid.UUID,
    slug: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("channels:read")),
):
    channel, bot = await _require_channel(channel_id, db)
    surface = await resolve_notes_surface(db, channel, bot)
    authorize_knowledge_document(auth, surface, "read")
    note = read_note(surface, slug)
    session = await get_or_create_note_session(
        db,
        channel=channel,
        bot=bot,
        surface=surface,
        note_path=note["path"],
        title=note["title"],
        content=note["content"],
    )
    await db.commit()
    return {**note, "session_id": str(session.id)}


@router.put("/{slug}")
async def put_channel_note(
    channel_id: uuid.UUID,
    slug: str,
    body: NoteWriteBody,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("channels:write")),
):
    channel, bot = await _require_channel(channel_id, db)
    surface = await resolve_notes_surface(db, channel, bot)
    authorize_knowledge_document(auth, surface, "write")
    note = write_note(surface, slug, body.content, body.base_hash)
    _schedule_reindex(str(channel_id), bot)
    return note


@router.put("/{slug}/session-binding")
async def put_channel_note_session_binding(
    channel_id: uuid.UUID,
    slug: str,
    body: NoteSessionBindingBody,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("channels:write")),
):
    channel, bot = await _require_channel(channel_id, db)
    surface = await resolve_notes_surface(db, channel, bot)
    authorize_knowledge_document(auth, surface, "session_binding")
    note = update_note_session_binding(surface, slug, {"mode": body.mode, "session_id": body.session_id})
    _schedule_reindex(str(channel_id), bot)
    return note


@router.post("/{slug}/assist")
async def assist_channel_note(
    channel_id: uuid.UUID,
    slug: str,
    body: NoteAssistBody,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("channels:read")),
):
    channel, bot = await _require_channel(channel_id, db)
    surface = await resolve_notes_surface(db, channel, bot)
    authorize_knowledge_document(auth, surface, "assist")
    note = read_note(surface, slug)
    if body.base_hash and body.base_hash != note["content_hash"]:
        raise HTTPException(status_code=409, detail={"message": "Note changed on disk", "content_hash": note["content_hash"], "content": note["content"]})
    content = body.content if body.content is not None else note["content"]
    selection = body.selection.model_dump() if body.selection else None
    session = await get_or_create_note_session(
        db,
        channel=channel,
        bot=bot,
        surface=surface,
        note_path=note["path"],
        title=note["title"],
        content=content,
    )
    proposal = await build_ai_assist_proposal(
        bot=bot,
        channel=channel,
        content=content,
        selection=selection,
        instruction=body.instruction,
        mode=body.mode,
        model_override=body.model_override,
        model_provider_id_override=body.model_provider_id_override,
    )
    await append_note_assist_exchange(
        db,
        session=session,
        bot=bot,
        note_path=note["path"],
        mode=body.mode,
        selection=selection,
        instruction=body.instruction,
        proposal=proposal,
    )
    await db.commit()
    return {**proposal, "session_id": str(session.id)}
