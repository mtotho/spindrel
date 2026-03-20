"""Admin dashboard router — all routes under /admin."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select, text

from app.agent.bots import get_bot, list_bots
from app.agent.knowledge import upsert_knowledge
from app.agent.persona import get_persona, write_persona
from app.agent.tools import index_local_tools, warm_mcp_tool_index_for_all_bots
from app.db.engine import async_session
from app.db.models import BotKnowledge, KnowledgePin, KnowledgeWrite, Memory, Message, SandboxInstance, Session, ToolCall, ToolEmbedding, TraceEvent

router = APIRouter(prefix="/admin", tags=["admin"])

# Import and include sub-routers
from app.routers.admin_tasks import router as _tasks_router  # noqa: E402
from app.routers.admin_fs import router as _fs_router  # noqa: E402
from app.routers.admin_knowledge_pins import router as _pins_router  # noqa: E402
from app.routers.admin_sandbox import router as _sandbox_router  # noqa: E402
router.include_router(_tasks_router)
router.include_router(_fs_router)
router.include_router(_pins_router)
router.include_router(_sandbox_router)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M")


templates.env.filters["fmt_dt"] = _fmt_dt  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Dashboard overview
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
async def admin_index(request: Request):
    async with async_session() as db:
        session_count = (await db.execute(select(func.count()).select_from(Session))).scalar_one()
        memory_count = (await db.execute(select(func.count()).select_from(Memory))).scalar_one()
        knowledge_count = (await db.execute(select(func.count()).select_from(BotKnowledge))).scalar_one()
        tool_count = (await db.execute(select(func.count()).select_from(ToolEmbedding))).scalar_one()
        tool_call_count = (await db.execute(select(func.count()).select_from(ToolCall))).scalar_one()
        sandbox_running = (await db.execute(
            select(func.count()).select_from(SandboxInstance).where(SandboxInstance.status == "running")
        )).scalar_one()

        recent_sessions = (
            await db.execute(select(Session).order_by(Session.last_active.desc()).limit(5))
        ).scalars().all()

        recent_tool_calls = (
            await db.execute(select(ToolCall).order_by(ToolCall.created_at.desc()).limit(10))
        ).scalars().all()

    bots = list_bots()
    stats = [
        {"label": "Bots", "count": len(bots), "href": "/admin/bots"},
        {"label": "Sessions", "count": session_count, "href": "/admin/sessions"},
        {"label": "Memories", "count": memory_count, "href": "/admin/memories"},
        {"label": "Knowledge", "count": knowledge_count, "href": "/admin/knowledge"},
        {"label": "Tools", "count": tool_count, "href": "/admin/tools"},
        {"label": "Logs", "count": tool_call_count, "href": "/admin/logs"},
        {"label": "Sandboxes", "count": sandbox_running, "href": "/admin/sandboxes"},
    ]
    return templates.TemplateResponse(
        "admin/index.html",
        {
            "request": request,
            "stats": stats,
            "recent_sessions": recent_sessions,
            "recent_tool_calls": recent_tool_calls,
        },
    )


# ---------------------------------------------------------------------------
# Bots
# ---------------------------------------------------------------------------

@router.get("/bots", response_class=HTMLResponse)
async def admin_bots(request: Request):
    bots = list_bots()
    return templates.TemplateResponse("admin/bots.html", {"request": request, "bots": bots})


@router.get("/bots/{bot_id}", response_class=HTMLResponse)
async def admin_bot_detail(request: Request, bot_id: str):
    try:
        bot = get_bot(bot_id)
    except HTTPException:
        return HTMLResponse("<div class='text-red-400 p-4'>Bot not found.</div>", status_code=404)
    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        return templates.TemplateResponse("admin/bot_detail.html", {"request": request, "bot": bot})
    persona = await get_persona(bot_id)
    async with async_session() as db:
        distinct_clients = [c for c in (await db.execute(
            select(Session.client_id).distinct().order_by(Session.client_id)
        )).scalars().all() if c]
    return templates.TemplateResponse("admin/bot_page.html", {
        "request": request,
        "bot": bot,
        "persona": persona or "",
        "distinct_clients": distinct_clients,
    })


@router.post("/bots/{bot_id}/persona", response_class=HTMLResponse)
async def admin_bot_save_persona(request: Request, bot_id: str, content: str = Form(...)):
    try:
        get_bot(bot_id)
    except HTTPException:
        raise HTTPException(status_code=404, detail="Bot not found")
    ok, err = await write_persona(bot_id, content)
    if not ok:
        return HTMLResponse(f"<div class='text-red-400 text-sm p-2'>Failed: {err}</div>", status_code=500)
    return HTMLResponse("<div class='text-green-400 text-sm'>Saved.</div>")


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@router.get("/sessions", response_class=HTMLResponse)
async def admin_sessions(
    request: Request,
    bot_id: Optional[str] = None,
    page: int = 1,
    expand: Optional[str] = None,
):
    page_size = 25
    offset = (page - 1) * page_size
    async with async_session() as db:
        stmt = select(Session).order_by(Session.last_active.desc())
        if bot_id:
            stmt = stmt.where(Session.bot_id == bot_id)
        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        sessions = (await db.execute(stmt.offset(offset).limit(page_size))).scalars().all()

    bots = list_bots()
    return templates.TemplateResponse(
        "admin/sessions.html",
        {
            "request": request,
            "sessions": sessions,
            "bots": bots,
            "bot_filter": bot_id,
            "page": page,
            "page_size": page_size,
            "total": total,
            "expand": expand,
        },
    )


@router.get("/sessions/{session_id}/detail", response_class=HTMLResponse)
async def admin_session_detail(request: Request, session_id: uuid.UUID, page: int = 1):
    page_size = 30
    offset = (page - 1) * page_size
    async with async_session() as db:
        session = await db.get(Session, session_id)
        if not session:
            return HTMLResponse("<div class='text-red-400 p-4'>Session not found.</div>", status_code=404)
        total = (await db.execute(
            select(func.count()).where(Message.session_id == session_id)
        )).scalar_one()
        messages = (
            await db.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at.desc())
                .offset(offset)
                .limit(page_size)
            )
        ).scalars().all()
    return templates.TemplateResponse(
        "admin/session_detail.html",
        {
            "request": request,
            "session": session,
            "messages": messages,
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )


@router.post("/sessions/{session_id}/compact", response_class=HTMLResponse)
async def admin_compact_session(request: Request, session_id: uuid.UUID):
    from app.services.compaction import run_compaction_forced
    async with async_session() as db:
        session = await db.get(Session, session_id)
        if not session:
            return HTMLResponse("<div class='text-red-400'>Session not found.</div>", status_code=404)
        try:
            bot = get_bot(session.bot_id)
            title, summary = await run_compaction_forced(session_id, bot, db)
            await db.commit()
            await db.refresh(session)
        except Exception as exc:
            return HTMLResponse(f"<div class='text-red-400'>Compaction failed: {exc}</div>", status_code=400)
    return templates.TemplateResponse(
        "admin/session_row.html",
        {"request": request, "session": session},
    )


@router.delete("/sessions/{session_id}", response_class=HTMLResponse)
async def admin_delete_session(session_id: uuid.UUID):
    from app.config import settings
    async with async_session() as db:
        session = await db.get(Session, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        try:
            bot = get_bot(session.bot_id)
            wipe = bot.memory.wipe_on_session_delete
        except HTTPException:
            wipe = settings.WIPE_MEMORY_ON_SESSION_DELETE
        if wipe:
            await db.execute(delete(Memory).where(Memory.session_id == session_id))
        await db.execute(delete(Session).where(Session.id == session_id))
        await db.commit()
    return HTMLResponse("", status_code=200)


# ---------------------------------------------------------------------------
# Memories
# ---------------------------------------------------------------------------

@router.get("/memories", response_class=HTMLResponse)
async def admin_memories(
    request: Request,
    bot_id: Optional[str] = None,
    client_id: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
):
    page_size = 30
    offset = (page - 1) * page_size
    async with async_session() as db:
        stmt = select(Memory).order_by(Memory.created_at.desc())
        if bot_id:
            stmt = stmt.where(Memory.bot_id == bot_id)
        if client_id:
            stmt = stmt.where(Memory.client_id == client_id)
        if q:
            stmt = stmt.where(Memory.content.ilike(f"%{q}%"))
        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        memories = (await db.execute(stmt.offset(offset).limit(page_size))).scalars().all()

        # Get distinct bot_ids and client_ids for filters
        bot_ids = (await db.execute(select(Memory.bot_id).distinct())).scalars().all()
        client_ids = (await db.execute(select(Memory.client_id).distinct())).scalars().all()

    return templates.TemplateResponse(
        "admin/memories.html",
        {
            "request": request,
            "memories": memories,
            "bot_ids": sorted(filter(None, bot_ids)),
            "client_ids": sorted(filter(None, client_ids)),
            "bot_filter": bot_id,
            "client_filter": client_id,
            "q": q or "",
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )


@router.delete("/memories/{memory_id}", response_class=HTMLResponse)
async def admin_delete_memory(memory_id: uuid.UUID):
    async with async_session() as db:
        mem = await db.get(Memory, memory_id)
        if not mem:
            raise HTTPException(status_code=404, detail="Memory not found")
        await db.delete(mem)
        await db.commit()
    return HTMLResponse("", status_code=200)


# ---------------------------------------------------------------------------
# Knowledge
# ---------------------------------------------------------------------------

@router.get("/knowledge", response_class=HTMLResponse)
async def admin_knowledge(
    request: Request,
    bot_id: Optional[str] = None,
    client_id: Optional[str] = None,
):
    async with async_session() as db:
        stmt = select(BotKnowledge).order_by(BotKnowledge.updated_at.desc())
        if bot_id:
            stmt = stmt.where(BotKnowledge.bot_id == bot_id)
        if client_id:
            stmt = stmt.where(BotKnowledge.client_id == client_id)
        entries = (await db.execute(stmt)).scalars().all()
        bot_ids = (await db.execute(select(BotKnowledge.bot_id).distinct())).scalars().all()
        client_ids = (await db.execute(select(BotKnowledge.client_id).distinct())).scalars().all()
    return templates.TemplateResponse(
        "admin/knowledge.html",
        {
            "request": request,
            "entries": entries,
            "bot_ids": sorted(filter(None, bot_ids)),
            "client_ids": sorted(filter(None, client_ids)),
            "bot_filter": bot_id,
            "client_filter": client_id,
        },
    )


@router.get("/knowledge/new", response_class=HTMLResponse)
async def admin_knowledge_new_form(request: Request):
    return templates.TemplateResponse("admin/knowledge_new.html", {"request": request})


@router.post("/knowledge", response_class=HTMLResponse)
async def admin_knowledge_create(
    request: Request,
    name: str = Form(...),
    content: str = Form(...),
    bot_id: str = Form(""),
    client_id: str = Form(""),
):
    effective_bot = bot_id.strip() or "_admin"
    effective_client = client_id.strip() or "_admin"
    await upsert_knowledge(
        name=name.strip(),
        content=content,
        bot_id=effective_bot,
        client_id=effective_client,
        cross_bot=not bool(bot_id.strip()),
    )
    return RedirectResponse("/admin/knowledge", status_code=303)


@router.get("/knowledge/{entry_id}/edit", response_class=HTMLResponse)
async def admin_knowledge_edit_form(request: Request, entry_id: uuid.UUID):
    """Inline partial (used by knowledge_row "Edit" button)."""
    async with async_session() as db:
        entry = await db.get(BotKnowledge, entry_id)
        if not entry:
            return HTMLResponse("<div class='text-red-400 p-4'>Not found.</div>", status_code=404)
    return templates.TemplateResponse(
        "admin/knowledge_edit.html", {"request": request, "entry": entry}
    )


@router.get("/knowledge/{entry_id}/edit-full", response_class=HTMLResponse)
async def admin_knowledge_edit_full(request: Request, entry_id: uuid.UUID):
    """Full-page editor."""
    async with async_session() as db:
        entry = await db.get(BotKnowledge, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Not found")
        distinct_clients = [c for c in (await db.execute(
            select(Session.client_id).distinct().order_by(Session.client_id)
        )).scalars().all() if c]
    return templates.TemplateResponse(
        "admin/knowledge_edit_full.html", {
            "request": request,
            "entry": entry,
            "bots": list_bots(),
            "distinct_clients": distinct_clients,
        }
    )


@router.put("/knowledge/{entry_id}", response_class=HTMLResponse)
async def admin_knowledge_update(
    request: Request,
    entry_id: uuid.UUID,
    content: str = Form(...),
):
    """HTMX inline update — returns updated row partial."""
    async with async_session() as db:
        entry = await db.get(BotKnowledge, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Not found")
        await upsert_knowledge(
            name=entry.name,
            content=content,
            bot_id=entry.bot_id or entry.created_by_bot,
            client_id=entry.client_id or "",
            cross_bot=entry.bot_id is None,
        )
        entry = await db.get(BotKnowledge, entry_id)
    return templates.TemplateResponse(
        "admin/knowledge_row.html", {"request": request, "entry": entry}
    )


@router.post("/knowledge/{entry_id}/save", response_class=HTMLResponse)
async def admin_knowledge_save_full(
    request: Request,
    entry_id: uuid.UUID,
    content: str = Form(...),
):
    """Full-page save (browser form POST, redirects back to list)."""
    async with async_session() as db:
        entry = await db.get(BotKnowledge, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Not found")
        await upsert_knowledge(
            name=entry.name,
            content=content,
            bot_id=entry.bot_id or entry.created_by_bot,
            client_id=entry.client_id or "",
            cross_bot=entry.bot_id is None,
        )
    return RedirectResponse("/admin/knowledge", status_code=303)


@router.delete("/knowledge/{entry_id}", response_class=HTMLResponse)
async def admin_knowledge_delete(entry_id: uuid.UUID):
    async with async_session() as db:
        entry = await db.get(BotKnowledge, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Not found")
        await db.delete(entry)
        await db.commit()
    return HTMLResponse("", status_code=200)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@router.get("/tools", response_class=HTMLResponse)
async def admin_tools(request: Request):
    async with async_session() as db:
        tools = (
            await db.execute(select(ToolEmbedding).order_by(ToolEmbedding.server_name.nullsfirst(), ToolEmbedding.tool_name))
        ).scalars().all()
    return templates.TemplateResponse("admin/tools.html", {"request": request, "tools": tools})


@router.post("/tools/reindex", response_class=HTMLResponse)
async def admin_tools_reindex(request: Request):
    await index_local_tools()
    await warm_mcp_tool_index_for_all_bots()
    async with async_session() as db:
        tools = (
            await db.execute(select(ToolEmbedding).order_by(ToolEmbedding.server_name.nullsfirst(), ToolEmbedding.tool_name))
        ).scalars().all()
    return templates.TemplateResponse(
        "admin/tools_table.html", {"request": request, "tools": tools}
    )


# ---------------------------------------------------------------------------
# Logs (unified tool_calls + trace_events)
# ---------------------------------------------------------------------------

@router.get("/tool-calls", response_class=HTMLResponse)
async def admin_tool_calls_redirect():
    return RedirectResponse("/admin/logs", status_code=301)


@router.get("/tool-calls/trace/{session_id}", response_class=HTMLResponse)
async def admin_tool_call_trace_redirect(session_id: uuid.UUID):
    return RedirectResponse(f"/admin/sessions/{session_id}/correlations", status_code=301)


@router.get("/logs", response_class=HTMLResponse)
async def admin_logs(
    request: Request,
    event_type: Optional[str] = None,
    bot_id: Optional[str] = None,
    session_id: Optional[str] = None,
    page: int = 1,
):
    page_size = 50
    offset = (page - 1) * page_size

    async with async_session() as db:
        # Build tool_calls query
        tc_stmt = select(ToolCall).order_by(ToolCall.created_at.desc())
        te_stmt = select(TraceEvent).order_by(TraceEvent.created_at.desc())

        if bot_id:
            tc_stmt = tc_stmt.where(ToolCall.bot_id == bot_id)
            te_stmt = te_stmt.where(TraceEvent.bot_id == bot_id)

        if session_id:
            try:
                sid = uuid.UUID(session_id)
                tc_stmt = tc_stmt.where(ToolCall.session_id == sid)
                te_stmt = te_stmt.where(TraceEvent.session_id == sid)
            except ValueError:
                pass

        if event_type == "tool_call":
            te_stmt = te_stmt.where(text("false"))
        elif event_type and event_type != "tool_call":
            tc_stmt = tc_stmt.where(text("false"))
            te_stmt = te_stmt.where(TraceEvent.event_type == event_type)

        tool_calls = (await db.execute(tc_stmt.limit(500))).scalars().all()
        trace_events = (await db.execute(te_stmt.limit(500))).scalars().all()

        # Merge and sort by created_at desc
        merged = []
        for tc in tool_calls:
            merged.append({"kind": "tool_call", "obj": tc, "created_at": tc.created_at})
        for te in trace_events:
            merged.append({"kind": "trace_event", "obj": te, "created_at": te.created_at})
        merged.sort(key=lambda x: x["created_at"], reverse=True)

        total = len(merged)
        rows = merged[offset: offset + page_size]

        bot_ids = (await db.execute(select(ToolCall.bot_id).distinct())).scalars().all()

    return templates.TemplateResponse(
        "admin/logs.html",
        {
            "request": request,
            "rows": rows,
            "bot_ids": sorted(filter(None, bot_ids)),
            "event_type_filter": event_type or "",
            "bot_filter": bot_id or "",
            "session_filter": session_id or "",
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )


@router.get("/trace/{correlation_id}", response_class=HTMLResponse)
async def admin_trace(request: Request, correlation_id: uuid.UUID):
    async with async_session() as db:
        tool_calls = (
            await db.execute(
                select(ToolCall)
                .where(ToolCall.correlation_id == correlation_id)
                .order_by(ToolCall.created_at)
            )
        ).scalars().all()
        trace_events = (
            await db.execute(
                select(TraceEvent)
                .where(TraceEvent.correlation_id == correlation_id)
                .order_by(TraceEvent.created_at)
            )
        ).scalars().all()
        messages = (
            await db.execute(
                select(Message)
                .where(Message.correlation_id == correlation_id)
                .where(Message.role.in_(["user", "assistant"]))
                .order_by(Message.created_at)
            )
        ).scalars().all()

    # Merge and sort by created_at
    merged = []
    for tc in tool_calls:
        merged.append({"kind": "tool_call", "obj": tc, "created_at": tc.created_at})
    for te in trace_events:
        merged.append({"kind": "trace_event", "obj": te, "created_at": te.created_at})
    for msg in messages:
        # Only show user messages and assistant messages with text content (not tool-call-only turns)
        if msg.role == "user" or (msg.role == "assistant" and msg.content):
            merged.append({"kind": "message", "obj": msg, "created_at": msg.created_at})
    merged.sort(key=lambda x: x["created_at"])

    # Derive session_id and bot_id from any event
    session_id = None
    bot_id = None
    client_id = None
    for item in merged:
        obj = item["obj"]
        if hasattr(obj, "session_id") and obj.session_id:
            session_id = obj.session_id
        if hasattr(obj, "bot_id") and obj.bot_id:
            bot_id = obj.bot_id
        if hasattr(obj, "client_id") and obj.client_id:
            client_id = obj.client_id
        if session_id and bot_id and client_id:
            break

    time_range_start = merged[0]["created_at"] if merged else None
    time_range_end = merged[-1]["created_at"] if merged else None

    def _tc_to_dict(tc: ToolCall) -> dict:
        return {
            "kind": "tool_call",
            "tool_name": tc.tool_name,
            "tool_type": tc.tool_type,
            "arguments": tc.arguments,
            "result": tc.result,
            "error": tc.error,
            "duration_ms": tc.duration_ms,
            "created_at": tc.created_at.isoformat() if tc.created_at else None,
        }

    def _te_to_dict(te: TraceEvent) -> dict:
        return {
            "kind": "trace_event",
            "event_type": te.event_type,
            "event_name": te.event_name,
            "count": te.count,
            "data": te.data,
            "duration_ms": te.duration_ms,
            "created_at": te.created_at.isoformat() if te.created_at else None,
        }

    def _msg_to_dict(msg: Message) -> dict:
        content = msg.content or ""
        if isinstance(content, str) and content.startswith("["):
            try:
                import json as _json
                parsed = _json.loads(content)
                if isinstance(parsed, list):
                    content = " ".join(
                        p.get("text", "") for p in parsed if isinstance(p, dict) and p.get("type") == "text"
                    ) or "[multimodal]"
            except Exception:
                pass
        return {
            "kind": "message",
            "role": msg.role,
            "content": content,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        }

    events_json = []
    for item in merged:
        if item["kind"] == "tool_call":
            events_json.append(_tc_to_dict(item["obj"]))
        elif item["kind"] == "trace_event":
            events_json.append(_te_to_dict(item["obj"]))
        else:
            events_json.append(_msg_to_dict(item["obj"]))

    return templates.TemplateResponse(
        "admin/trace.html",
        {
            "request": request,
            "correlation_id": correlation_id,
            "events": merged,
            "events_json": events_json,
            "session_id": session_id,
            "bot_id": bot_id,
            "client_id": client_id,
            "time_range_start": time_range_start,
            "time_range_end": time_range_end,
        },
    )


@router.get("/sessions/{session_id}/correlations", response_class=HTMLResponse)
async def admin_session_correlations(request: Request, session_id: uuid.UUID):
    async with async_session() as db:
        session = await db.get(Session, session_id)
        if not session:
            return HTMLResponse("<div class='text-red-400 p-4'>Session not found.</div>", status_code=404)

        # Get all distinct correlation_ids from both tables for this session
        tc_corr = (
            await db.execute(
                select(ToolCall.correlation_id, func.min(ToolCall.created_at).label("first_at"),
                       func.count(ToolCall.id).label("tc_count"))
                .where(ToolCall.session_id == session_id, ToolCall.correlation_id.is_not(None))
                .group_by(ToolCall.correlation_id)
            )
        ).all()

        te_corr = (
            await db.execute(
                select(TraceEvent.correlation_id, func.min(TraceEvent.created_at).label("first_at"),
                       func.count(TraceEvent.id).label("te_count"),
                       func.count(TraceEvent.id).filter(TraceEvent.event_type == "error").label("error_count"))
                .where(TraceEvent.session_id == session_id, TraceEvent.correlation_id.is_not(None))
                .group_by(TraceEvent.correlation_id)
            )
        ).all()

    # Merge by correlation_id
    corr_map: dict[uuid.UUID, dict] = {}
    for row in tc_corr:
        cid = row.correlation_id
        corr_map[cid] = {
            "correlation_id": cid,
            "first_at": row.first_at,
            "tc_count": row.tc_count,
            "te_count": 0,
            "has_error": False,
        }
    for row in te_corr:
        cid = row.correlation_id
        if cid not in corr_map:
            corr_map[cid] = {
                "correlation_id": cid,
                "first_at": row.first_at,
                "tc_count": 0,
                "te_count": row.te_count,
                "has_error": bool(row.error_count and row.error_count > 0),
            }
        else:
            corr_map[cid]["te_count"] = row.te_count
            corr_map[cid]["has_error"] = bool(row.error_count and row.error_count > 0)
            if row.first_at < corr_map[cid]["first_at"]:
                corr_map[cid]["first_at"] = row.first_at

    correlations = sorted(corr_map.values(), key=lambda x: x["first_at"], reverse=True)

    return templates.TemplateResponse(
        "admin/session_correlations.html",
        {"request": request, "session": session, "correlations": correlations},
    )


@router.get("/knowledge/{entry_id}/history", response_class=HTMLResponse)
async def admin_knowledge_history(request: Request, entry_id: uuid.UUID):
    async with async_session() as db:
        entry = await db.get(BotKnowledge, entry_id)
        if not entry:
            return HTMLResponse("<div class='text-red-400 p-4'>Not found.</div>", status_code=404)
        writes = (
            await db.execute(
                select(KnowledgeWrite)
                .where(
                    KnowledgeWrite.knowledge_name == entry.name,
                    KnowledgeWrite.bot_id == entry.bot_id,
                    KnowledgeWrite.client_id == entry.client_id,
                )
                .order_by(KnowledgeWrite.created_at.desc())
                .limit(50)
            )
        ).scalars().all()
    return templates.TemplateResponse(
        "admin/knowledge_history.html",
        {"request": request, "entry": entry, "writes": writes},
    )
