"""Admin routes for filesystem indexing."""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select

from app.agent.bots import list_bots
from app.db.engine import async_session
from app.db.models import FilesystemChunk

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M")


templates.env.filters["fmt_dt"] = _fmt_dt  # type: ignore[attr-defined]


@router.get("/filesystem", response_class=HTMLResponse)
async def admin_fs_index(request: Request):
    async with async_session() as db:
        rows = (await db.execute(
            select(
                FilesystemChunk.bot_id,
                FilesystemChunk.root,
                func.count(FilesystemChunk.id).label("chunk_count"),
                func.count(FilesystemChunk.file_path.distinct()).label("file_count"),
                func.max(FilesystemChunk.indexed_at).label("last_indexed"),
            )
            .group_by(FilesystemChunk.bot_id, FilesystemChunk.root)
            .order_by(FilesystemChunk.bot_id, FilesystemChunk.root)
        )).all()

    # Build lookup of watch status from bot config
    watch_lookup: dict[tuple[str, str], bool] = {}
    patterns_lookup: dict[tuple[str, str], list[str]] = {}
    for bot in list_bots():
        for cfg in bot.filesystem_indexes:
            abs_root = str(Path(cfg.root).resolve())
            watch_lookup[(bot.id, abs_root)] = cfg.watch
            patterns_lookup[(bot.id, abs_root)] = cfg.patterns

    indexes = []
    for row in rows:
        key = (row.bot_id, row.root)
        indexes.append({
            "bot_id": row.bot_id,
            "root": row.root,
            "chunk_count": row.chunk_count,
            "file_count": row.file_count,
            "last_indexed": row.last_indexed,
            "watch": watch_lookup.get(key, False),
            "patterns": patterns_lookup.get(key, []),
        })

    return templates.TemplateResponse(
        "admin/fs_indexes.html",
        {"request": request, "indexes": indexes},
    )


@router.post("/filesystem/reindex", response_class=HTMLResponse)
async def admin_fs_reindex(
    request: Request,
    root: str = Form(...),
    bot_id: str = Form(...),
):
    from app.agent.bots import get_bot
    from app.agent.fs_indexer import index_directory
    try:
        bot = get_bot(bot_id)
    except Exception:
        return HTMLResponse(f"<span class='text-red-400'>Bot {bot_id!r} not found</span>", status_code=404)

    abs_root = str(Path(root).resolve())
    cfg = next(
        (c for c in bot.filesystem_indexes if str(Path(c.root).resolve()) == abs_root),
        None,
    )
    if cfg is None:
        return HTMLResponse(f"<span class='text-red-400'>Root not configured for this bot</span>", status_code=400)

    stats = await index_directory(cfg.root, bot_id, cfg.patterns, force=True)

    # Return updated row partial
    async with async_session() as db:
        agg = (await db.execute(
            select(
                func.count(FilesystemChunk.id).label("chunk_count"),
                func.count(FilesystemChunk.file_path.distinct()).label("file_count"),
                func.max(FilesystemChunk.indexed_at).label("last_indexed"),
            )
            .where(FilesystemChunk.bot_id == bot_id, FilesystemChunk.root == abs_root)
        )).one()

    idx = {
        "bot_id": bot_id,
        "root": abs_root,
        "chunk_count": agg.chunk_count,
        "file_count": agg.file_count,
        "last_indexed": agg.last_indexed,
        "watch": cfg.watch,
        "patterns": cfg.patterns,
    }
    return templates.TemplateResponse(
        "admin/fs_index_row.html",
        {"request": request, "idx": idx},
    )


@router.delete("/filesystem/chunks", response_class=HTMLResponse)
async def admin_fs_delete_chunks(root: str, bot_id: str):
    async with async_session() as db:
        await db.execute(
            delete(FilesystemChunk).where(
                FilesystemChunk.bot_id == bot_id,
                FilesystemChunk.root == root,
            )
        )
        await db.commit()
    return HTMLResponse("", status_code=200)
