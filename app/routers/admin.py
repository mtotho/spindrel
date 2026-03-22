"""Admin dashboard router — all routes under /admin."""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, or_, select, text

from app.config import settings
from app.agent.bots import get_bot, list_bots
from app.agent.knowledge import upsert_knowledge, update_knowledge_entry
from app.agent.persona import get_persona, write_persona
from app.agent.tools import index_local_tools, warm_mcp_tool_index_for_all_bots
from app.db.engine import async_session
from app.services.sessions import (
    derive_integration_session_id,
    is_integration_client_id,
    upsert_integration_session,
)
from app.db.models import (
    BotKnowledge,
    KnowledgePin,
    KnowledgeWrite,
    Memory,
    Message,
    Plan,
    PlanItem,
    SandboxInstance,
    Session,
    Task,
    ToolCall,
    ToolEmbedding,
    TraceEvent,
)
from app.routers.admin_template_filters import install_admin_template_filters

router = APIRouter(prefix="/admin", tags=["admin"])

# Import and include sub-routers
from app.routers.admin_tasks import router as _tasks_router  # noqa: E402
from app.routers.admin_fs import router as _fs_router  # noqa: E402
from app.routers.admin_knowledge_pins import router as _pins_router  # noqa: E402
from app.routers.admin_sandbox import router as _sandbox_router  # noqa: E402
from app.routers.admin_bots import router as _bots_router  # noqa: E402
from app.routers.admin_skills import router as _skills_router  # noqa: E402
from app.routers.admin_channels import router as _channels_router  # noqa: E402
from app.routers.admin_providers import router as _providers_router  # noqa: E402
router.include_router(_bots_router)
router.include_router(_skills_router)
router.include_router(_channels_router)
router.include_router(_tasks_router)
router.include_router(_fs_router)
router.include_router(_pins_router)
router.include_router(_sandbox_router)
router.include_router(_providers_router)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
install_admin_template_filters(templates.env)


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
    root_only: Optional[str] = None,
):
    page_size = 25
    offset = (page - 1) * page_size
    async with async_session() as db:
        stmt = select(Session).order_by(Session.last_active.desc())
        if bot_id:
            stmt = stmt.where(Session.bot_id == bot_id)
        if root_only:
            stmt = stmt.where(Session.depth == 0)
        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        sessions = (await db.execute(stmt.offset(offset).limit(page_size))).scalars().all()

        # Get child session counts for displayed sessions
        session_ids = [s.id for s in sessions]
        child_counts: dict = {}
        if session_ids:
            child_count_rows = (await db.execute(
                select(Session.parent_session_id, func.count(Session.id).label("cnt"))
                .where(Session.parent_session_id.in_(session_ids))
                .group_by(Session.parent_session_id)
            )).all()
            child_counts = {row.parent_session_id: row.cnt for row in child_count_rows}

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
            "root_only": bool(root_only),
            "child_counts": child_counts,
        },
    )


@router.get("/sessions/{session_id}/children", response_class=HTMLResponse)
async def admin_session_children(request: Request, session_id: uuid.UUID):
    """HTMX partial: return child session rows for a given parent session."""
    async with async_session() as db:
        children = (await db.execute(
            select(Session)
            .where(Session.parent_session_id == session_id)
            .order_by(Session.created_at)
        )).scalars().all()
        child_ids = [c.id for c in children]
        child_counts: dict = {}
        if child_ids:
            grandchild_rows = (await db.execute(
                select(Session.parent_session_id, func.count(Session.id).label("cnt"))
                .where(Session.parent_session_id.in_(child_ids))
                .group_by(Session.parent_session_id)
            )).all()
            child_counts = {row.parent_session_id: row.cnt for row in grandchild_rows}

    return templates.TemplateResponse(
        "admin/session_children.html",
        {
            "request": request,
            "children": children,
            "child_counts": child_counts,
        },
    )


@router.get("/sessions/{session_id}/detail", response_class=HTMLResponse)
async def admin_session_detail(request: Request, session_id: uuid.UUID, page: int = 1):
    page_size = 30
    is_htmx = request.headers.get("HX-Request") == "true"
    async with async_session() as db:
        session = await db.get(Session, session_id)
        if not session:
            return HTMLResponse("<div class='text-red-400 p-4'>Session not found.</div>", status_code=404)
        total = (await db.execute(
            select(func.count()).where(Message.session_id == session_id)
        )).scalar_one()
        last_page = max(1, ((total - 1) // page_size) + 1)
        # Full-page direct links (e.g. from trace) default to newest messages
        if not is_htmx and page == 1:
            page = last_page
        offset = (page - 1) * page_size
        messages = (
            await db.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at.asc())
                .offset(offset)
                .limit(page_size)
            )
        ).scalars().all()
        plans = (await db.execute(
            select(Plan).where(Plan.session_id == session_id).order_by(Plan.created_at)
        )).scalars().all()
        plan_items_map: dict[str, list] = {}
        for _p in plans:
            _items = (await db.execute(
                select(PlanItem).where(PlanItem.plan_id == _p.id).order_by(PlanItem.position)
            )).scalars().all()
            plan_items_map[str(_p.id)] = list(_items)

    # Group messages into turns by correlation_id
    turns = []
    current_turn: dict = {"correlation_id": None, "messages": []}
    for msg in messages:
        if msg.correlation_id != current_turn["correlation_id"]:
            if current_turn["messages"]:
                turns.append(current_turn)
            current_turn = {"correlation_id": msg.correlation_id, "messages": []}
        current_turn["messages"].append(msg)
    if current_turn["messages"]:
        turns.append(current_turn)

    template = "admin/session_detail.html" if is_htmx else "admin/session_detail_page.html"
    return templates.TemplateResponse(
        template,
        {
            "request": request,
            "session": session,
            "messages": messages,
            "turns": turns,
            "page": page,
            "page_size": page_size,
            "total": total,
            "last_page": last_page,
            "plans": plans,
            "plan_items": plan_items_map,
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
# Delegation Trees
# ---------------------------------------------------------------------------

async def _delegation_walk_root_and_latest(
    db, start_id: uuid.UUID
) -> tuple[uuid.UUID | None, datetime | None]:
    """Follow parent_session_id links to the chain root; return (root_id, max last_active on path)."""
    seen: set[uuid.UUID] = set()
    cur: uuid.UUID | None = start_id
    best: datetime | None = None
    while cur is not None:
        if cur in seen:
            return None, None
        seen.add(cur)
        row = await db.get(Session, cur)
        if row is None:
            return None, None
        if best is None or row.last_active > best:
            best = row.last_active
        if row.parent_session_id is None:
            return cur, best
        cur = row.parent_session_id
    return None, None


async def _delegation_expand_subtree_ids(db, root_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """All session ids reachable downward via parent_session_id from any root (BFS fixpoint)."""
    ids = set(root_ids)
    while True:
        child_ids = (
            await db.execute(select(Session.id).where(Session.parent_session_id.in_(ids)))
        ).scalars().all()
        new = set(child_ids) - ids
        if not new:
            break
        ids |= new
    return ids


@router.get("/delegations", response_class=HTMLResponse)
async def admin_delegations(
    request: Request,
    page: int = 1,
    bot_id: Optional[str] = None,
):
    page_size = 15
    async with async_session() as db:
        # Chains from rows that record root_session_id (normal delegate_to_agent / cross-bot tasks)
        root_q = (
            select(Session.root_session_id, func.max(Session.last_active).label("latest"))
            .where(Session.root_session_id.is_not(None))
            .group_by(Session.root_session_id)
        )
        sql_roots = (await db.execute(root_q)).all()
        root_latest: dict[uuid.UUID, datetime] = {r.root_session_id: r.latest for r in sql_roots}

        # Legacy / inconsistent rows: parent set but root_session_id NULL — infer root by walking up
        stray_ids = (
            await db.execute(
                select(Session.id).where(
                    Session.parent_session_id.is_not(None),
                    Session.root_session_id.is_(None),
                )
            )
        ).scalars().all()
        for sid in stray_ids:
            r_id, latest = await _delegation_walk_root_and_latest(db, sid)
            if r_id is None or latest is None:
                continue
            prev = root_latest.get(r_id)
            root_latest[r_id] = latest if prev is None or latest > prev else prev

        sorted_roots = sorted(root_latest.keys(), key=lambda rid: root_latest[rid], reverse=True)

        if bot_id and sorted_roots:
            matching = (
                await db.execute(
                    select(Session.id).where(Session.id.in_(sorted_roots), Session.bot_id == bot_id)
                )
            ).scalars().all()
            match_set = set(matching)
            sorted_roots = [rid for rid in sorted_roots if rid in match_set]

        total = len(sorted_roots)
        paged_root_ids = sorted_roots[(page - 1) * page_size : page * page_size]

        trees_data = []
        if paged_root_ids:
            load_ids = await _delegation_expand_subtree_ids(db, paged_root_ids)
            tagged = (
                await db.execute(select(Session.id).where(Session.root_session_id.in_(paged_root_ids)))
            ).scalars().all()
            load_ids |= set(tagged)

            all_tree_sessions = (
                await db.execute(select(Session).where(Session.id.in_(load_ids)).order_by(Session.created_at))
            ).scalars().all()

            session_map = {s.id: s for s in all_tree_sessions}
            children_map: dict = {}
            for s in all_tree_sessions:
                if s.parent_session_id:
                    children_map.setdefault(s.parent_session_id, []).append(s)

            def _build_node(s):
                return {
                    "session": s,
                    "children": [
                        _build_node(c)
                        for c in sorted(children_map.get(s.id, []), key=lambda x: x.created_at)
                    ],
                }

            def _flatten(node, prefix=None, is_last=True):
                if prefix is None:
                    prefix = []
                rows = [{
                    "session": node["session"],
                    "depth": len(prefix),
                    "prefix": list(prefix),
                    "is_last": is_last,
                    "child_count": len(node["children"]),
                }]
                for i, child in enumerate(node["children"]):
                    child_is_last = (i == len(node["children"]) - 1)
                    rows.extend(_flatten(child, prefix + [not child_is_last], child_is_last))
                return rows

            def _subtree_size(rid: uuid.UUID) -> int:
                stack = [rid]
                seen: set[uuid.UUID] = set()
                while stack:
                    i = stack.pop()
                    if i in seen:
                        continue
                    seen.add(i)
                    for ch in children_map.get(i, []):
                        stack.append(ch.id)
                return len(seen)

            for root_id in paged_root_ids:
                root = session_map.get(root_id)
                if root:
                    tree_node = _build_node(root)
                    trees_data.append({
                        "root": root,
                        "rows": _flatten(tree_node),
                        "size": _subtree_size(root_id),
                    })

        harness_tasks = (
            await db.execute(
                select(Task)
                .where(Task.dispatch_type == "harness")
                .order_by(Task.created_at.desc())
                .limit(25)
            )
        ).scalars().all()

    bots = list_bots()
    return templates.TemplateResponse(
        "admin/delegations.html",
        {
            "request": request,
            "trees": trees_data,
            "total": total,
            "page": page,
            "page_size": page_size,
            "bots": bots,
            "bot_filter": bot_id or "",
            "harness_tasks": harness_tasks,
        },
    )


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

def _knowledge_session_filter_label(sess: Session | None, sid: uuid.UUID) -> str:
    if sess and (sess.title or "").strip():
        t = (sess.title or "").strip()
        if len(t) > 52:
            t = t[:51] + "…"
        return f"{t} · {sid}"
    return str(sid)


@router.get("/knowledge", response_class=HTMLResponse)
async def admin_knowledge(
    request: Request,
    bot_id: Optional[str] = None,
    client_id: Optional[str] = None,
    session_filter: Optional[str] = None,
):
    """List knowledge rows with optional filters (bot, client, session)."""
    from sqlalchemy.orm import selectinload
    sf_raw = (session_filter or "").strip()
    async with async_session() as db:
        stmt = select(BotKnowledge).options(selectinload(BotKnowledge.access_entries)).order_by(BotKnowledge.updated_at.desc())
        if bot_id:
            stmt = stmt.where(BotKnowledge.bot_id == bot_id)
        if client_id:
            stmt = stmt.where(BotKnowledge.client_id == client_id)
        if sf_raw == "__none__":
            stmt = stmt.where(BotKnowledge.session_id.is_(None))
        elif sf_raw:
            try:
                stmt = stmt.where(BotKnowledge.session_id == uuid.UUID(sf_raw))
            except ValueError:
                pass
        entries = (await db.execute(stmt)).scalars().all()
        bot_ids = (await db.execute(select(BotKnowledge.bot_id).distinct())).scalars().all()
        client_ids = (await db.execute(select(BotKnowledge.client_id).distinct())).scalars().all()
        distinct_session_ids = list(
            (await db.execute(
                select(BotKnowledge.session_id).distinct().where(BotKnowledge.session_id.isnot(None))
            )).scalars().all()
        )
        session_by_id: dict[uuid.UUID, Session] = {}
        session_filter_choices: list[dict[str, str]] = []
        if distinct_session_ids:
            sess_rows = (
                await db.execute(
                    select(Session)
                    .where(Session.id.in_(distinct_session_ids))
                    .order_by(Session.last_active.desc())
                )
            ).scalars().all()
            session_by_id = {s.id: s for s in sess_rows}
            distinct_set = set(distinct_session_ids)
            ordered_sids: list[uuid.UUID] = []
            seen: set[uuid.UUID] = set()
            for s in sess_rows:
                if s.id in distinct_set and s.id not in seen:
                    ordered_sids.append(s.id)
                    seen.add(s.id)
            for sid in sorted(distinct_session_ids, key=str):
                if sid not in seen:
                    ordered_sids.append(sid)
            for sid in ordered_sids:
                session_filter_choices.append(
                    {
                        "value": str(sid),
                        "label": _knowledge_session_filter_label(session_by_id.get(sid), sid),
                    }
                )
    return templates.TemplateResponse(
        "admin/knowledge.html",
        {
            "request": request,
            "entries": entries,
            "bot_ids": sorted(filter(None, bot_ids)),
            "client_ids": sorted(filter(None, client_ids)),
            "bot_filter": bot_id,
            "client_filter": client_id,
            "session_filter": sf_raw,
            "session_by_id": session_by_id,
            "session_filter_choices": session_filter_choices,
        },
    )


@router.get("/knowledge/new", response_class=HTMLResponse)
async def admin_knowledge_new_form(request: Request):
    return templates.TemplateResponse(
        "admin/knowledge_new.html",
        {"request": request, "bots": list_bots()},
    )


@router.post("/knowledge", response_class=HTMLResponse)
async def admin_knowledge_create(
    request: Request,
    name: str = Form(...),
    content: str = Form(...),
    bot_id: str = Form(""),
    client_id: str = Form(""),
):
    await upsert_knowledge(
        name=name.strip(),
        content=content,
        bot_id=bot_id.strip() or None,
        client_id=client_id.strip() or None,
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
        sessions_same_client: list[Session] = []
        if entry.client_id:
            sessions_same_client = list(
                (await db.execute(
                    select(Session)
                    .where(Session.client_id == entry.client_id)
                    .order_by(Session.last_active.desc())
                )).scalars().all()
            )
    derived_session_str: str | None = None
    if is_integration_client_id(entry.client_id):
        derived_session_str = str(derive_integration_session_id(entry.client_id))

    seen_ids: set[str] = set()
    session_options: list[tuple[str, str]] = []
    if derived_session_str:
        session_options.append(
            (
                derived_session_str,
                "This channel’s chat session (integration — one stable UUID per client_id)",
            )
        )
        seen_ids.add(derived_session_str)
    for s in sessions_same_client:
        sid = str(s.id)
        if sid in seen_ids:
            continue
        seen_ids.add(sid)
        title = (s.title or "").strip()
        if title:
            label = f"{title[:48]}{'…' if len(title) > 48 else ''} · {sid[:8]}…"
        else:
            label = f"Session {sid[:8]}… (same client_id)"
        session_options.append((sid, label))

    if entry.session_id:
        es = str(entry.session_id)
        if es not in seen_ids:
            session_options.insert(0, (es, f"Current binding · {es[:8]}…"))
            seen_ids.add(es)

    _bots = list_bots()
    _known_bot_ids = {b.id for b in _bots}
    orphan_bot_id = (
        entry.bot_id
        if entry.bot_id and entry.bot_id not in _known_bot_ids
        else None
    )

    return templates.TemplateResponse(
        "admin/knowledge_edit_full.html",
        {
            "request": request,
            "entry": entry,
            "bots": _bots,
            "orphan_bot_id": orphan_bot_id,
            "distinct_clients": distinct_clients,
            "derived_session_str": derived_session_str,
            "session_options": session_options,
            "is_integration_client": derived_session_str is not None,
            "default_knowledge_similarity": settings.KNOWLEDGE_SIMILARITY_THRESHOLD,
        },
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
            bot_id=entry.bot_id,
            client_id=entry.client_id,
            session_id=entry.session_id,
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
    bot_id: str = Form(""),
    client_id: str = Form(""),
    session_id: str = Form(""),
    knowledge_similarity_threshold: str = Form(""),
):
    """Full-page save (browser form POST, redirects back to list)."""
    async with async_session() as db:
        _entry = await db.get(BotKnowledge, entry_id)
        if not _entry:
            raise HTTPException(status_code=404, detail="Not found")
    b = bot_id.strip() or None
    c = client_id.strip() or None
    _raw_sid = (session_id or "").strip()
    _new_sid: uuid.UUID | None = None
    if _raw_sid:
        try:
            _new_sid = uuid.UUID(_raw_sid)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid session UUID")
        async with async_session() as db:
            existing_sess = await db.get(Session, _new_sid)
            if existing_sess is None:
                if c and is_integration_client_id(c) and derive_integration_session_id(c) == _new_sid:
                    await upsert_integration_session(db, c, b or "default")
                else:
                    raise HTTPException(status_code=400, detail="Session not found")
    _sim_raw = (knowledge_similarity_threshold or "").strip()
    _sim: float | None
    if not _sim_raw:
        _sim = None
    else:
        try:
            _sim = float(_sim_raw)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid similarity threshold")
    ok = await update_knowledge_entry(
        entry_id=entry_id,
        content=content,
        bot_id=b,
        client_id=c,
        session_id=_new_sid,
        similarity_threshold=_sim,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    return RedirectResponse(f"/admin/knowledge/{entry_id}/edit-full?saved=1", status_code=303)


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

        # Message time ranges per correlation (for duration)
        msg_times = (
            await db.execute(
                select(
                    Message.correlation_id,
                    func.min(Message.created_at).label("msg_first_at"),
                    func.max(Message.created_at).label("msg_last_at"),
                )
                .where(Message.session_id == session_id)
                .where(Message.correlation_id.is_not(None))
                .group_by(Message.correlation_id)
            )
        ).all()

        # First user message content per correlation
        user_msgs = (
            await db.execute(
                select(Message.correlation_id, Message.content)
                .where(Message.session_id == session_id)
                .where(Message.correlation_id.is_not(None))
                .where(Message.role == "user")
                .order_by(Message.correlation_id, Message.created_at.asc())
                .distinct(Message.correlation_id)
            )
        ).all()

        # First assistant message content per correlation
        asst_msgs = (
            await db.execute(
                select(Message.correlation_id, Message.content)
                .where(Message.session_id == session_id)
                .where(Message.correlation_id.is_not(None))
                .where(Message.role == "assistant")
                .where(Message.content.is_not(None))
                .where(Message.content != "")
                .order_by(Message.correlation_id, Message.created_at.asc())
                .distinct(Message.correlation_id)
            )
        ).all()

    # Build lookup dicts
    msg_times_map = {row.correlation_id: row for row in msg_times}
    user_preview_map = {row.correlation_id: (row.content or "")[:120] for row in user_msgs}
    asst_preview_map = {row.correlation_id: (row.content or "")[:120] for row in asst_msgs}

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

    # Enrich with preview and duration
    for cid, entry in corr_map.items():
        entry["user_preview"] = user_preview_map.get(cid, "")
        entry["response_preview"] = asst_preview_map.get(cid, "")
        mt = msg_times_map.get(cid)
        if mt and mt.msg_last_at and mt.msg_first_at:
            delta = mt.msg_last_at - mt.msg_first_at
            entry["duration_ms"] = int(delta.total_seconds() * 1000)
        else:
            entry["duration_ms"] = None

    correlations = sorted(corr_map.values(), key=lambda x: x["first_at"], reverse=True)

    return templates.TemplateResponse(
        "admin/session_correlations.html",
        {"request": request, "session": session, "correlations": correlations},
    )


@router.get("/knowledge/{entry_id}/history", response_class=HTMLResponse)
async def admin_knowledge_history(request: Request, entry_id: uuid.UUID):
    """Write audit for this ``bot_knowledge`` row (FK ``knowledge_writes.bot_knowledge_id``)."""
    async with async_session() as db:
        entry = await db.get(BotKnowledge, entry_id)
        if not entry:
            return HTMLResponse("<div class='text-red-400 p-4'>Not found.</div>", status_code=404)
        _ws = (
            select(KnowledgeWrite)
            .where(KnowledgeWrite.bot_knowledge_id == entry_id)
            .order_by(KnowledgeWrite.created_at.desc())
            .limit(200)
        )
        writes = (await db.execute(_ws)).scalars().all()
    return templates.TemplateResponse(
        "admin/knowledge_history.html",
        {"request": request, "entry": entry, "writes": writes},
    )
