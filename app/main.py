import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.agent.bots import list_bots, load_bots, seed_bots_from_yaml
from app.agent.skills import load_skills, seed_skills_from_files
from app.services import file_sync
from app.agent.tools import (
    index_local_tools,
    validate_pinned_tools,
    warm_mcp_tool_index_for_all_bots,
)
from app.config import settings
from app.db.engine import async_session, run_migrations
from app.tools.loader import discover_and_load_tools
from app.tools.mcp import load_mcp_config

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"


async def _cleanup_orphaned_tools(registered_tools: dict) -> None:
    """Remove local_tools entries from bot configs that reference unregistered tools."""
    from app.db.engine import async_session
    from app.db.models import Bot as BotRow

    registered = set(registered_tools.keys())
    for bot in list_bots():
        orphaned = set(bot.local_tools or []) - registered
        if not orphaned:
            continue
        cleaned = [t for t in bot.local_tools if t in registered]
        logger.info(
            "Bot '%s': removing %d orphaned local_tools: %s",
            bot.id, len(orphaned), sorted(orphaned),
        )
        async with async_session() as db:
            row = await db.get(BotRow, bot.id)
            if row:
                row.local_tools = cleaned
                await db.commit()
    # Reload so in-memory configs reflect the cleanup
    await load_bots()


async def _index_filesystems_and_start_watchers() -> None:
    """Index workspace and legacy filesystem directories, then start file watchers.

    Runs as a background task so it doesn't block server startup.
    """
    from app.agent.fs_indexer import index_directory
    from app.agent.fs_watcher import start_watchers
    from app.services.workspace import workspace_service

    from app.services.workspace_indexing import resolve_indexing, get_all_roots

    logger.info("Background: indexing configured filesystem directories...")
    for bot in list_bots():
        # Workspace-based indexing
        if bot.workspace.enabled and bot.workspace.indexing.enabled:
            _resolved = resolve_indexing(bot.workspace.indexing, bot._workspace_raw, bot._ws_indexing_config)
            for root in get_all_roots(bot, workspace_service):
                try:
                    stats = await index_directory(root, bot.id, _resolved["patterns"], force=True)
                    logger.info("Indexed workspace root %s for bot %s: %s", root, bot.id, stats)
                except Exception:
                    logger.exception("Failed to index workspace root %s for bot %s", root, bot.id)
        # Legacy filesystem_indexes (backwards compat)
        for cfg in bot.filesystem_indexes:
            try:
                stats = await index_directory(cfg.root, bot.id, cfg.patterns, force=True)
                logger.info("Indexed %s for bot %s: %s", cfg.root, bot.id, stats)
            except Exception:
                logger.exception("Failed to index %s for bot %s", cfg.root, bot.id)
    await start_watchers(list_bots())
    logger.info("Background: filesystem indexing complete.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    logger.info("Running database migrations...")
    await run_migrations()
    logger.info("Loading provider configs from DB...")
    from app.services.providers import load_providers
    await load_providers()
    logger.info("Seeding bots from YAML (seed-once)...")
    await seed_bots_from_yaml()
    logger.info("Loading bot configurations from DB...")
    await load_bots()
    from app.agent.base_prompt import load_base_prompt
    load_base_prompt()
    logger.info("Loading MCP server config...")
    load_mcp_config()
    extra_tool_dirs = [Path(p.strip()) for p in settings.TOOL_DIRS.split(":") if p.strip()]
    logger.info("Discovering extra tool directories...")
    discover_and_load_tools(extra_tool_dirs)
    # Import local tools to trigger @register decorators
    import app.tools.local  # noqa: F401

    logger.info("Indexing local tool schemas for retrieval...")
    await index_local_tools()
    # Auto-remove orphaned local_tools entries (tools that no longer exist)
    from app.tools.registry import _tools as _registered_tools
    await _cleanup_orphaned_tools(_registered_tools)
    logger.info("Fetching and indexing MCP tool schemas...")
    await warm_mcp_tool_index_for_all_bots()
    await validate_pinned_tools()

    logger.info("Syncing file-sourced skills and knowledge...")
    await file_sync.sync_all_files()
    logger.info("Loading skills from DB...")
    await load_skills()
    logger.info("Starting file watcher...")
    asyncio.create_task(file_sync.watch_files())

    # Ensure workspace host dirs exist (fast, doesn't block)
    from app.services.workspace import workspace_service
    for bot in list_bots():
        if bot.workspace.enabled:
            workspace_service.ensure_host_dir(bot.id, bot=bot)
    # Ensure shared workspace host dirs exist
    from app.services.shared_workspace import shared_workspace_service
    from sqlalchemy import select as sa_select
    async with async_session() as _sw_db:
        from app.db.models import SharedWorkspace as _SW
        _sw_rows = (await _sw_db.execute(sa_select(_SW))).scalars().all()
    for _sw in _sw_rows:
        shared_workspace_service.ensure_host_dirs(str(_sw.id))
        # Auto-start containers that were previously running
        if _sw.status == "running":
            try:
                await shared_workspace_service.ensure_container(_sw)
            except Exception:
                logger.warning("Failed to auto-start shared workspace %s", _sw.name)
    # Embed workspace skills for all workspaces
    from app.services.workspace_skills import embed_workspace_skills as _embed_ws_skills
    for _sw in _sw_rows:
        if _sw.workspace_skills_enabled:
            try:
                await _embed_ws_skills(str(_sw.id))
            except Exception:
                logger.warning("Failed to embed workspace skills for %s", _sw.name)
    # Index filesystem directories + start watchers in background (doesn't block startup)
    asyncio.create_task(_index_filesystems_and_start_watchers())

    if settings.HARNESS_CONFIG_FILE and Path(settings.HARNESS_CONFIG_FILE).exists():
        logger.info("Loading harness configs from %s...", settings.HARNESS_CONFIG_FILE)
        from app.services.harness import harness_service
        harness_service.load(settings.HARNESS_CONFIG_FILE)

    if settings.STT_PROVIDER:
        logger.info("Warming up STT provider (%s)...", settings.STT_PROVIDER)
        from app.stt import warm_up as stt_warm_up
        stt_warm_up()
    logger.info("Agent server ready. (LOG_LEVEL=%s)", settings.LOG_LEVEL.upper())
    from app.agent.tasks import task_worker
    asyncio.create_task(task_worker())
    from app.services.heartbeat import heartbeat_worker
    asyncio.create_task(heartbeat_worker())
    from app.services.attachment_summarizer import attachment_sweep_worker
    asyncio.create_task(attachment_sweep_worker())
    from app.services.attachment_retention import attachment_retention_worker
    asyncio.create_task(attachment_retention_worker())
    yield


app = FastAPI(
    title="Agent Server",
    description="Self-hosted LLM agent server. Integration API at /api/v1/ — see /docs.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow Expo dev server and any origins from CORS_ORIGINS env var
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

_cors_origins: list[str] = [
    o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()
]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Register routers
from app.routers import admin, auth, chat, sessions, transcribe  # noqa: E402
from app.routers.admin_channels import api_router as _slack_api_router  # noqa: E402
from app.routers.api_v1 import router as _api_v1_router  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(transcribe.router)
app.include_router(admin.router)
app.include_router(_slack_api_router, prefix="/api")
app.include_router(_api_v1_router)

app.mount("/admin/static", StaticFiles(directory="app/static"), name="admin-static")

# Auto-discover and register integrations from integrations/*/router.py
from integrations import discover_integrations as _discover_integrations  # noqa: E402
for _integration_id, _integration_router in _discover_integrations():
    app.include_router(
        _integration_router,
        prefix=f"/integrations/{_integration_id}",
        tags=[f"Integration: {_integration_id}"],
    )
    logger.info("Registered integration: %s", _integration_id)


@app.get("/health")
async def health():
    return {"status": "ok"}
