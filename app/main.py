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
from app.db.engine import run_migrations
from app.tools.loader import discover_and_load_tools
from app.tools.mcp import load_mcp_config

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"


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
    logger.info("Loading MCP server config...")
    load_mcp_config()
    extra_tool_dirs = [Path(p.strip()) for p in settings.TOOL_DIRS.split(":") if p.strip()]
    logger.info("Discovering extra tool directories...")
    discover_and_load_tools(extra_tool_dirs)
    # Import local tools to trigger @register decorators
    import app.tools.local  # noqa: F401

    logger.info("Indexing local tool schemas for retrieval...")
    await index_local_tools()
    # Warn about deprecated tool name
    for _bot in list_bots():
        if "run_host_command" in (_bot.local_tools or []):
            logger.warning(
                "Bot '%s' lists 'run_host_command' in local_tools — this tool has been renamed "
                "to 'exec_command'. Update the bot config to remove this warning.",
                _bot.id,
            )
    logger.info("Fetching and indexing MCP tool schemas...")
    await warm_mcp_tool_index_for_all_bots()
    await validate_pinned_tools()

    logger.info("Syncing file-sourced skills and knowledge...")
    await file_sync.sync_all_files()
    logger.info("Loading skills from DB...")
    await load_skills()
    logger.info("Starting file watcher...")
    asyncio.create_task(file_sync.watch_files())

    logger.info("Indexing configured filesystem directories...")
    from app.agent.fs_indexer import index_directory
    from app.agent.fs_watcher import start_watchers
    for bot in list_bots():
        for cfg in bot.filesystem_indexes:
            try:
                stats = await index_directory(cfg.root, bot.id, cfg.patterns, force=True)
                logger.info("Indexed %s for bot %s: %s", cfg.root, bot.id, stats)
            except Exception:
                logger.exception("Failed to index %s for bot %s", cfg.root, bot.id)
    await start_watchers(list_bots())

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

# Register routers
from app.routers import admin, chat, sessions, transcribe  # noqa: E402
from app.routers.admin_channels import api_router as _slack_api_router  # noqa: E402
from app.routers.api_v1 import router as _api_v1_router  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

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
