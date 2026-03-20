"""Admin HTMX partials for knowledge pin management (embedded in knowledge edit and bot detail pages)."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.agent.bots import get_bot, list_bots
from app.agent.knowledge import create_knowledge_pin
from app.db.engine import async_session
from app.db.models import BotKnowledge, KnowledgePin, Session

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


async def _distinct_clients() -> list[str]:
    async with async_session() as db:
        rows = (await db.execute(select(Session.client_id).distinct().order_by(Session.client_id))).scalars().all()
    return [c for c in rows if c]


async def _pins_for_entry_id(entry_id: uuid.UUID) -> tuple[BotKnowledge | None, list[KnowledgePin]]:
    async with async_session() as db:
        entry = await db.get(BotKnowledge, entry_id)
        if not entry:
            return None, []
        pins = list((await db.execute(
            select(KnowledgePin)
            .where(KnowledgePin.knowledge_name == entry.name)
            .order_by(KnowledgePin.bot_id, KnowledgePin.client_id)
        )).scalars().all())
    return entry, pins


async def _bot_knowledge_section_ctx(bot_id: str) -> dict:
    """Load knowledge docs visible to this bot + their pin status."""
    bot = get_bot(bot_id)

    async with async_session() as db:
        stmt = select(BotKnowledge).order_by(BotKnowledge.name).where(
            (BotKnowledge.bot_id == bot_id) | (BotKnowledge.bot_id.is_(None))
        )
        knowledge_docs = list((await db.execute(stmt)).scalars().all())

        all_bot_pins = list((await db.execute(
            select(KnowledgePin)
            .where(KnowledgePin.bot_id == bot_id)
            .order_by(KnowledgePin.knowledge_name, KnowledgePin.client_id)
        )).scalars().all())

    # bot-scope pins (client_id=None) are the toggleable ones; channel-specific shown read-only
    pin_by_name = {p.knowledge_name: p for p in all_bot_pins if p.client_id is None}
    channel_pins = [p for p in all_bot_pins if p.client_id is not None]

    return {
        "bot_id": bot_id,
        "bot": bot,
        "knowledge_docs": knowledge_docs,
        "pin_by_name": pin_by_name,
        "pinned_names": set(pin_by_name.keys()),
        "channel_pins": channel_pins,
    }


# ---------------------------------------------------------------------------
# Knowledge entry pins (sidebar in knowledge_edit_full.html)
# ---------------------------------------------------------------------------

@router.get("/knowledge/{entry_id}/pins", response_class=HTMLResponse)
async def knowledge_pins_partial(request: Request, entry_id: uuid.UUID):
    entry, pins = await _pins_for_entry_id(entry_id)
    if not entry:
        return HTMLResponse("<div class='text-red-400 text-xs p-2'>Not found.</div>", status_code=404)
    return templates.TemplateResponse(request, "admin/knowledge_pins_partial.html", {
        "entry": entry,
        "pins": pins,
        "bots": list_bots(),
        "distinct_clients": await _distinct_clients(),
    })


@router.post("/knowledge/{entry_id}/pins", response_class=HTMLResponse)
async def create_pin_for_entry(
    request: Request,
    entry_id: uuid.UUID,
    scope: str = Form(...),
    bot_id: str = Form(""),
    client_id: str = Form(""),
):
    entry, _ = await _pins_for_entry_id(entry_id)
    if not entry:
        return HTMLResponse("<div class='text-red-400 text-xs p-2'>Not found.</div>", status_code=404)

    pin_bot = bot_id.strip() or None
    pin_client = client_id.strip() or None
    if scope == "bot":
        pin_client = None
    elif scope == "channel":
        pin_bot = None

    ok, err = await create_knowledge_pin(entry.name, pin_bot, pin_client)
    entry, pins = await _pins_for_entry_id(entry_id)
    return templates.TemplateResponse(request, "admin/knowledge_pins_partial.html", {
        "entry": entry,
        "pins": pins,
        "bots": list_bots(),
        "distinct_clients": await _distinct_clients(),
        "error": err if not ok else None,
    })


@router.delete("/knowledge/pins/{pin_id}", response_class=HTMLResponse)
async def delete_entry_pin(request: Request, pin_id: uuid.UUID):
    async with async_session() as db:
        pin = await db.get(KnowledgePin, pin_id)
        if not pin:
            return HTMLResponse("", status_code=200)
        knowledge_name = pin.knowledge_name
        await db.delete(pin)
        await db.commit()
        entry_row = (await db.execute(
            select(BotKnowledge).where(BotKnowledge.name == knowledge_name).limit(1)
        )).scalar_one_or_none()

    if not entry_row:
        return HTMLResponse("", status_code=200)

    entry, pins = await _pins_for_entry_id(entry_row.id)
    return templates.TemplateResponse(request, "admin/knowledge_pins_partial.html", {
        "entry": entry,
        "pins": pins,
        "bots": list_bots(),
        "distinct_clients": await _distinct_clients(),
    })


# ---------------------------------------------------------------------------
# Bot knowledge section (embedded in bot_page.html)
# ---------------------------------------------------------------------------

@router.get("/bots/{bot_id}/knowledge-section", response_class=HTMLResponse)
async def bot_knowledge_section(request: Request, bot_id: str):
    try:
        ctx = await _bot_knowledge_section_ctx(bot_id)
    except HTTPException:
        return HTMLResponse("<div class='text-red-400 text-xs'>Bot not found.</div>", status_code=404)
    return templates.TemplateResponse(request, "admin/bot_knowledge_section.html", ctx)


@router.post("/bots/{bot_id}/knowledge-section", response_class=HTMLResponse)
async def pin_knowledge_for_bot(
    request: Request,
    bot_id: str,
    knowledge_name: str = Form(...),
):
    try:
        get_bot(bot_id)
    except HTTPException:
        return HTMLResponse("<div class='text-red-400 text-xs'>Bot not found.</div>", status_code=404)

    await create_knowledge_pin(knowledge_name.strip(), bot_id, None)  # bot-scope, all channels
    ctx = await _bot_knowledge_section_ctx(bot_id)
    return templates.TemplateResponse(request, "admin/bot_knowledge_section.html", ctx)


@router.delete("/bots/{bot_id}/knowledge-section/{pin_id}", response_class=HTMLResponse)
async def unpin_knowledge_for_bot(request: Request, bot_id: str, pin_id: uuid.UUID):
    async with async_session() as db:
        pin = await db.get(KnowledgePin, pin_id)
        if pin:
            await db.delete(pin)
            await db.commit()
    ctx = await _bot_knowledge_section_ctx(bot_id)
    return templates.TemplateResponse(request, "admin/bot_knowledge_section.html", ctx)
