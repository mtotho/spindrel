"""Admin routes for filesystem indexing."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select

from app.agent.bots import list_bots
from app.db.engine import async_session
from app.db.models import FilesystemChunk
from app.routers.admin_template_filters import install_admin_template_filters

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
install_admin_template_filters(templates.env)


def _scope_badge(bot_id: str | None, client_id: str | None) -> str:
    if bot_id is None and client_id is None:
        return "global"
    if bot_id is None:
        return "channel"
    if client_id is None:
        return "bot"
    return "session"


@router.get("/filesystem", response_class=HTMLResponse)
async def admin_fs_index(request: Request):
    async with async_session() as db:
        rows = (await db.execute(
            select(
                FilesystemChunk.bot_id,
                FilesystemChunk.client_id,
                FilesystemChunk.root,
                func.count(FilesystemChunk.id).label("chunk_count"),
                func.count(FilesystemChunk.file_path.distinct()).label("file_count"),
                func.max(FilesystemChunk.indexed_at).label("last_indexed"),
            )
            .group_by(FilesystemChunk.bot_id, FilesystemChunk.client_id, FilesystemChunk.root)
            .order_by(FilesystemChunk.bot_id, FilesystemChunk.root)
        )).all()

    # Build lookup of watch/patterns/cooldown from bot config
    watch_lookup: dict[tuple[str | None, str | None, str], bool] = {}
    patterns_lookup: dict[tuple[str | None, str | None, str], list[str]] = {}
    cooldown_lookup: dict[tuple[str | None, str | None, str], int] = {}
    for bot in list_bots():
        for cfg in bot.filesystem_indexes:
            abs_root = str(Path(cfg.root).resolve())
            # YAML-based configs are always bot-scoped (bot_id=bot.id, client_id=None)
            watch_lookup[(bot.id, None, abs_root)] = cfg.watch
            patterns_lookup[(bot.id, None, abs_root)] = cfg.patterns
            cooldown_lookup[(bot.id, None, abs_root)] = cfg.cooldown_seconds

    indexes = []
    for row in rows:
        key = (row.bot_id, row.client_id, row.root)
        indexes.append(_build_idx(
            row.bot_id, row.client_id, row.root,
            chunk_count=row.chunk_count,
            file_count=row.file_count,
            last_indexed=row.last_indexed,
            watch=watch_lookup.get(key, False),
            patterns=patterns_lookup.get(key, []),
            cooldown_seconds=cooldown_lookup.get(key, 300),
        ))

    return templates.TemplateResponse(
        "admin/fs_indexes.html",
        {"request": request, "indexes": indexes},
    )


@router.post("/filesystem/reindex", response_class=HTMLResponse)
async def admin_fs_reindex(
    request: Request,
    root: str = Form(...),
    bot_id: str = Form(...),
    client_id: str = Form(default=""),
):
    from app.agent.bots import get_bot
    from app.agent.fs_indexer import index_directory

    resolved_client_id = client_id.strip() or None
    resolved_bot_id = bot_id.strip() or None

    # Find patterns from bot config if applicable
    patterns = ["**/*.py", "**/*.md", "**/*.yaml"]
    if resolved_bot_id:
        try:
            bot = get_bot(resolved_bot_id)
            abs_root = str(Path(root).resolve())
            cfg = next(
                (c for c in bot.filesystem_indexes if str(Path(c.root).resolve()) == abs_root),
                None,
            )
            if cfg is not None:
                patterns = cfg.patterns
        except Exception:
            pass

    stats = await index_directory(
        root, resolved_bot_id, patterns,
        client_id=resolved_client_id,
        force=True,
    )

    abs_root = str(Path(root).resolve())

    # Return updated row partial
    async with async_session() as db:
        conds = [FilesystemChunk.root == abs_root]
        if resolved_bot_id is None:
            conds.append(FilesystemChunk.bot_id.is_(None))
        else:
            conds.append(FilesystemChunk.bot_id == resolved_bot_id)
        if resolved_client_id is None:
            conds.append(FilesystemChunk.client_id.is_(None))
        else:
            conds.append(FilesystemChunk.client_id == resolved_client_id)

        agg = (await db.execute(
            select(
                func.count(FilesystemChunk.id).label("chunk_count"),
                func.count(FilesystemChunk.file_path.distinct()).label("file_count"),
                func.max(FilesystemChunk.indexed_at).label("last_indexed"),
            )
            .where(*conds)
        )).one()

    watch = False
    cooldown_seconds = 300
    if resolved_bot_id:
        try:
            bot = get_bot(resolved_bot_id)
            abs_root_check = str(Path(root).resolve())
            cfg = next(
                (c for c in bot.filesystem_indexes if str(Path(c.root).resolve()) == abs_root_check),
                None,
            )
            if cfg:
                watch = cfg.watch
                cooldown_seconds = cfg.cooldown_seconds
        except Exception:
            pass

    idx = _build_idx(
        resolved_bot_id, resolved_client_id, abs_root,
        chunk_count=agg.chunk_count,
        file_count=agg.file_count,
        last_indexed=agg.last_indexed,
        watch=watch,
        patterns=patterns,
        cooldown_seconds=cooldown_seconds,
    )
    return templates.TemplateResponse(
        "admin/fs_index_row.html",
        {"request": request, "idx": idx},
    )


def _row_key(bot_id: str | None, client_id: str | None, root: str) -> str:
    return f"{bot_id or ''}-{client_id or ''}-{root.replace('/', '-')}"


def _build_idx(bot_id: str | None, client_id: str | None, root: str,
               chunk_count: int, file_count: int, last_indexed,
               watch: bool, patterns: list[str], cooldown_seconds: int) -> dict:
    scope = _scope_badge(bot_id, client_id)
    return {
        "bot_id": bot_id,
        "client_id": client_id,
        "root": root,
        "chunk_count": chunk_count,
        "file_count": file_count,
        "last_indexed": last_indexed,
        "watch": watch,
        "patterns": patterns,
        "cooldown_seconds": cooldown_seconds,
        "scope": scope,
        "row_key": _row_key(bot_id, client_id, root),
    }


@router.get("/filesystem/edit-form", response_class=HTMLResponse)
async def admin_fs_edit_form(request: Request, root: str, bot_id: str = "", client_id: str = ""):
    resolved_bot_id = bot_id.strip() or None
    resolved_client_id = client_id.strip() or None

    # Load current patterns/watch/cooldown from bot config if available
    patterns = ["**/*.py", "**/*.md", "**/*.yaml"]
    watch = False
    cooldown_seconds = 300
    if resolved_bot_id:
        try:
            from app.agent.bots import get_bot
            bot = get_bot(resolved_bot_id)
            abs_root = str(Path(root).resolve())
            cfg = next(
                (c for c in bot.filesystem_indexes if str(Path(c.root).resolve()) == abs_root),
                None,
            )
            if cfg:
                patterns = cfg.patterns
                watch = cfg.watch
                cooldown_seconds = cfg.cooldown_seconds
        except Exception:
            pass

    idx = _build_idx(
        resolved_bot_id, resolved_client_id, root,
        chunk_count=0, file_count=0, last_indexed=None,
        watch=watch, patterns=patterns, cooldown_seconds=cooldown_seconds,
    )
    return templates.TemplateResponse(
        "admin/fs_index_edit.html",
        {"request": request, "idx": idx},
    )


@router.post("/filesystem/save-edit", response_class=HTMLResponse)
async def admin_fs_save_edit(
    request: Request,
    root: str = Form(...),
    bot_id: str = Form(default=""),
    client_id: str = Form(default=""),
    patterns: str = Form(default="**/*.py\n**/*.md\n**/*.yaml"),
    cooldown_seconds: int = Form(default=300),
    watch: str = Form(default=""),
):
    from app.agent.fs_indexer import index_directory

    resolved_bot_id = bot_id.strip() or None
    resolved_client_id = client_id.strip() or None
    parsed_patterns = [p.strip() for p in patterns.splitlines() if p.strip()]
    watch_bool = bool(watch)  # checkbox sends "on" when checked, absent when not

    # Persist to bot config if this is a bot-owned index
    if resolved_bot_id:
        try:
            from app.agent.bots import get_bot, reload_bots
            from app.db.engine import async_session as _session
            from app.db.models import Bot as BotRow
            from sqlalchemy import select as sa_select

            bot = get_bot(resolved_bot_id)
            abs_root = str(Path(root).resolve())
            async with _session() as db:
                row = (await db.execute(
                    sa_select(BotRow).where(BotRow.id == resolved_bot_id)
                )).scalar_one_or_none()
                if row is not None:
                    existing = list(row.filesystem_indexes or [])
                    updated = False
                    for entry in existing:
                        if str(Path(entry.get("root", "")).resolve()) == abs_root:
                            entry["patterns"] = parsed_patterns
                            entry["watch"] = watch_bool
                            entry["cooldown_seconds"] = cooldown_seconds
                            updated = True
                            break
                    if not updated:
                        existing.append({
                            "root": root,
                            "patterns": parsed_patterns,
                            "watch": watch_bool,
                            "cooldown_seconds": cooldown_seconds,
                        })
                    row.filesystem_indexes = existing
                    await db.commit()
            reload_bots()
        except Exception:
            pass  # non-fatal — still re-index with new patterns

    stats = await index_directory(
        root, resolved_bot_id, parsed_patterns,
        client_id=resolved_client_id,
        cooldown_seconds=0,  # force
        force=True,
    )

    abs_root = str(Path(root).resolve())

    # Fetch updated counts
    conds = [FilesystemChunk.root == abs_root]
    if resolved_bot_id is None:
        conds.append(FilesystemChunk.bot_id.is_(None))
    else:
        conds.append(FilesystemChunk.bot_id == resolved_bot_id)
    if resolved_client_id is None:
        conds.append(FilesystemChunk.client_id.is_(None))
    else:
        conds.append(FilesystemChunk.client_id == resolved_client_id)

    async with async_session() as db:
        agg = (await db.execute(
            select(
                func.count(FilesystemChunk.id).label("chunk_count"),
                func.count(FilesystemChunk.file_path.distinct()).label("file_count"),
                func.max(FilesystemChunk.indexed_at).label("last_indexed"),
            ).where(*conds)
        )).one()

    idx = _build_idx(
        resolved_bot_id, resolved_client_id, abs_root,
        chunk_count=agg.chunk_count,
        file_count=agg.file_count,
        last_indexed=agg.last_indexed,
        watch=watch_bool,
        patterns=parsed_patterns,
        cooldown_seconds=cooldown_seconds,
    )

    # Render updated data row for OOB swap + clear the edit slot
    row_key = _row_key(resolved_bot_id, resolved_client_id, abs_root)
    tmpl = templates.env.get_template("admin/fs_index_row.html")
    data_row_html = tmpl.render(request=request, idx=idx)
    oob_row = data_row_html.replace(
        f'id="fs-row-{row_key}"',
        f'id="fs-row-{row_key}" hx-swap-oob="outerHTML:#fs-row-{row_key}"',
        1,
    )
    # Standard response clears the edit slot; OOB updates the data row
    return HTMLResponse(oob_row)


@router.delete("/filesystem/chunks", response_class=HTMLResponse)
async def admin_fs_delete_chunks(root: str, bot_id: str, client_id: str = ""):
    resolved_client_id = client_id.strip() or None
    resolved_bot_id = bot_id.strip() or None

    conds = [FilesystemChunk.root == root]
    if resolved_bot_id is None:
        conds.append(FilesystemChunk.bot_id.is_(None))
    else:
        conds.append(FilesystemChunk.bot_id == resolved_bot_id)
    if resolved_client_id is None:
        conds.append(FilesystemChunk.client_id.is_(None))
    else:
        conds.append(FilesystemChunk.client_id == resolved_client_id)

    async with async_session() as db:
        await db.execute(delete(FilesystemChunk).where(*conds))
        await db.commit()
    return HTMLResponse("", status_code=200)
