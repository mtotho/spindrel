import asyncio
import logging
import os
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
from app.services.mcp_servers import load_mcp_servers, seed_from_yaml as seed_mcp_from_yaml

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
    from sqlalchemy import delete

    from app.agent.fs_indexer import index_directory, cleanup_stale_roots
    from app.agent.fs_watcher import start_watchers
    from app.db.models import FilesystemChunk
    from app.services.workspace import workspace_service
    from app.services.memory_indexing import index_memory_for_bot

    from app.services.workspace_indexing import resolve_indexing, get_all_roots

    # Clean up chunks from stale roots (e.g. after workspace root path changes)
    logger.info("Background: cleaning up stale filesystem index roots...")
    _cleaned_bot_ids: set[str] = set()
    for bot in list_bots():
        if bot.workspace.enabled and bot.workspace.indexing.enabled:
            try:
                valid = get_all_roots(bot, workspace_service)
                removed = await cleanup_stale_roots(bot.id, valid)
                if removed:
                    logger.info("Cleaned up %d stale chunks for bot %s", removed, bot.id)
                _cleaned_bot_ids.add(bot.id)
            except Exception:
                logger.exception("Failed to clean up stale roots for bot %s", bot.id)
    # Also clean up memory-only bots (workspace-files but no general indexing)
    for bot in list_bots():
        if bot.id in _cleaned_bot_ids:
            continue
        if bot.workspace.enabled and bot.memory_scheme == "workspace-files":
            try:
                valid = get_all_roots(bot, workspace_service)
                removed = await cleanup_stale_roots(bot.id, valid)
                if removed:
                    logger.info("Cleaned up %d stale memory chunks for bot %s", removed, bot.id)
            except Exception:
                logger.exception("Failed to clean up stale roots for bot %s", bot.id)

    # Phase 1: Index memory files for workspace-files bots (independent of indexing toggle)
    logger.info("Background: indexing memory files for workspace-files bots...")
    for bot in list_bots():
        if bot.memory_scheme == "workspace-files" and bot.workspace.enabled:
            try:
                stats = await index_memory_for_bot(bot, force=True)
                if stats:
                    logger.info("Memory index for bot %s: %s", bot.id, stats)
            except Exception:
                logger.exception("Failed to index memory for bot %s", bot.id)

    # Phase 2: Segment-based workspace indexing (only for bots with indexing.enabled)
    # For shared workspace bots, indexing REQUIRES segments — without segments,
    # only memory (Phase 1) is indexed.  Standalone bots use blanket patterns.
    logger.info("Background: indexing configured filesystem directories...")
    for bot in list_bots():
        # Workspace-based indexing
        if bot.workspace.enabled and bot.workspace.indexing.enabled:
            _resolved = resolve_indexing(bot.workspace.indexing, bot._workspace_raw, bot._ws_indexing_config)
            _patterns = _resolved["patterns"]
            _segments = _resolved.get("segments")
            # Shared workspace bots without segments: skip Phase 2 entirely.
            # Only memory gets indexed (Phase 1).  Clean up any stale non-memory
            # chunks from previous blanket indexing runs.
            if not _segments:
                from app.services.memory_scheme import get_memory_index_prefix
                _mem_prefix = get_memory_index_prefix(bot)
                for root in get_all_roots(bot, workspace_service):
                    try:
                        _resolved_root = str(Path(root).resolve())
                        async with async_session() as _db:
                            _del = await _db.execute(
                                delete(FilesystemChunk).where(
                                    FilesystemChunk.bot_id == bot.id,
                                    FilesystemChunk.root == _resolved_root,
                                    ~FilesystemChunk.file_path.like(_mem_prefix.rstrip("/") + "/%"),
                                )
                            )
                            if _del.rowcount:
                                logger.info("Cleaned up %d non-memory chunks for bot %s (no segments)", _del.rowcount, bot.id)
                            await _db.commit()
                    except Exception:
                        logger.exception("Failed to clean up non-memory chunks for bot %s", bot.id)
                continue
            for root in get_all_roots(bot, workspace_service):
                try:
                    stats = await index_directory(
                        root, bot.id, _patterns, force=True,
                        embedding_model=_resolved["embedding_model"],
                        segments=_segments,
                    )
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
async def lifespan(application: FastAPI):
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    # Install in-memory ring buffer handler for /api/v1/admin/server-logs
    from app.services.log_buffer import install as _install_log_buffer
    _install_log_buffer(capacity=10_000)
    logger.info("Running database migrations...")
    try:
        await run_migrations()
    except Exception:
        logger.critical("Database migration failed — refusing to start with stale schema", exc_info=True)
        raise
    logger.info("Loading server settings from DB...")
    from app.services.server_settings import load_settings_from_db
    await load_settings_from_db()
    logger.info("Loading integration settings from DB...")
    from app.services.integration_settings import load_from_db as load_integration_settings
    await load_integration_settings()
    logger.info("Loading provider configs from DB...")
    from app.services.providers import load_providers
    await load_providers()
    # Check encryption status: hard error if encrypted secrets exist without key,
    # soft warning if plaintext secrets exist without key.
    from app.services.encryption import is_encryption_enabled
    if not is_encryption_enabled():
        from app.services.providers import has_encrypted_secrets
        if await has_encrypted_secrets():
            raise RuntimeError(
                "ENCRYPTION_KEY is not set but the database contains encrypted secrets (enc: prefix). "
                "These values cannot be decrypted without the original key. "
                "Set ENCRYPTION_KEY in .env to the key used to encrypt them."
            )
        from app.services.providers import list_providers as _list_providers
        if any(p.api_key for p in _list_providers()):
            logger.warning(
                "ENCRYPTION_KEY is not set — provider API keys are stored as plaintext in the database. "
                "Set ENCRYPTION_KEY in .env to enable encryption at rest."
            )
    logger.info("Loading usage limits...")
    from app.services.usage_limits import load_limits, start_refresh_task
    await load_limits()
    start_refresh_task()
    logger.info("Loading usage spike config...")
    from app.services.usage_spike import load_spike_config, start_spike_refresh_task
    await load_spike_config()
    start_spike_refresh_task()
    logger.info("Loading server config (global fallback models)...")
    from app.services.server_config import load_server_config
    await load_server_config()
    # Restore config state from file on first boot (empty DB)
    if settings.CONFIG_STATE_FILE:
        from sqlalchemy import select as sa_sel, func as sa_func
        from app.db.models import Bot as BotModel
        async with async_session() as _cs_db:
            bot_count = (await _cs_db.execute(sa_sel(sa_func.count()).select_from(BotModel))).scalar() or 0
        if bot_count == 0:
            from app.services.config_export import restore_from_file
            await restore_from_file()
            # Reload providers/settings/server_config/integration_settings after restore
            await load_providers()
            from app.services.server_settings import load_settings_from_db as _reload_ss
            await _reload_ss()
            from app.services.server_config import load_server_config as _reload_sc
            await _reload_sc()
            await load_integration_settings()
            await load_mcp_servers()

    logger.info("Seeding bots from YAML (seed-once)...")
    await seed_bots_from_yaml()
    logger.info("Loading bot configurations from DB...")
    await load_bots()

    # Auto-create default workspace and enroll all bots
    from app.services.workspace_bootstrap import ensure_default_workspace, ensure_all_bots_enrolled
    async with async_session() as _ws_db:
        default_ws = await ensure_default_workspace(_ws_db)
        added = await ensure_all_bots_enrolled(_ws_db, default_ws.id)
        if added:
            logger.info("Auto-enrolled %d bot(s) into workspace", added)
            await load_bots()  # Reload so shared_workspace_id is populated

    logger.info("Loading secret values from DB...")
    from app.services.secret_values import load_from_db as load_secret_values
    await load_secret_values()
    logger.info("Building secret registry...")
    from app.services.secret_registry import rebuild as rebuild_secret_registry
    await rebuild_secret_registry()
    logger.info("Ensuring orchestrator landing channel...")
    from app.services.channels import ensure_orchestrator_channel
    await ensure_orchestrator_channel()
    from app.agent.base_prompt import load_base_prompt
    load_base_prompt()
    logger.info("Seeding MCP servers from YAML (if empty)...")
    await seed_mcp_from_yaml()
    logger.info("Loading MCP servers from DB...")
    await load_mcp_servers()
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

    # Feature validation (carapace requires, memory scheme tools, etc.)
    from app.services.feature_validation import validate_features
    _feature_warnings = await validate_features()
    if _feature_warnings:
        logger.warning("Feature validation found %d warning(s)", len(_feature_warnings))

    logger.info("Syncing file-sourced skills and knowledge...")
    await file_sync.sync_all_files()
    logger.info("Loading skills from DB...")
    await load_skills()
    # Carapace YAML seeding is handled by sync_all_files() above; just load registry.
    from app.agent.carapaces import load_carapaces
    logger.info("Loading carapaces from DB...")
    await load_carapaces()
    # Workflow YAML seeding is handled by sync_all_files() above; just load registry.
    from app.services.workflows import load_workflows
    logger.info("Loading workflows from DB...")
    await load_workflows()
    # Register workflow task completion hook
    from app.services.workflow_hooks import register_workflow_hooks
    register_workflow_hooks()
    logger.info("Starting file watcher...")
    asyncio.create_task(file_sync.watch_files())

    # Bootstrap memory scheme for workspace-files bots (idempotent, creates MEMORY.md if missing)
    from app.services.memory_scheme import bootstrap_memory_scheme
    for bot in list_bots():
        if bot.memory_scheme == "workspace-files" and bot.workspace.enabled:
            try:
                bootstrap_memory_scheme(bot)
            except Exception:
                logger.exception("Failed to bootstrap memory scheme for bot %s", bot.id)

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

    # Auto-append workspace integrations directory to INTEGRATION_DIRS
    # so bots can scaffold integrations at /workspace/integrations/ and
    # they'll be discovered on next restart.
    if default_ws:
        _ws_int_path = os.path.join(
            shared_workspace_service.get_host_root(str(default_ws.id)),
            "integrations",
        )
        os.makedirs(_ws_int_path, exist_ok=True)
        _existing = settings.INTEGRATION_DIRS
        _existing_paths = {p.strip() for p in _existing.split(":")} if _existing else set()
        if _ws_int_path not in _existing_paths:
            settings.INTEGRATION_DIRS = (
                f"{_existing}:{_ws_int_path}" if _existing else _ws_int_path
            )
            logger.info("Added workspace integrations directory: %s", _ws_int_path)

    # Discover and register integration routers (must happen inside lifespan
    # so workspace integrations path is available in INTEGRATION_DIRS)
    from integrations import discover_integrations as _discover_integrations
    for _integration_id, _integration_router in _discover_integrations():
        try:
            application.include_router(
                _integration_router,
                prefix=f"/integrations/{_integration_id}",
                tags=[f"Integration: {_integration_id}"],
            )
            logger.info("Registered integration: %s", _integration_id)
        except Exception:
            logger.exception("Failed to register integration router: %s", _integration_id)

    # Discover integration web UIs and populate the module-level registry.
    # The actual route handler is registered at module level (after app = FastAPI(...))
    # because the lifespan `app` parameter can collide with the `app` package name.
    from integrations import discover_web_uis as _discover_web_uis
    for _web_ui in _discover_web_uis():
        _iid = _web_ui["integration_id"]
        _INTEGRATION_WEB_UI_DIRS[_iid] = Path(_web_ui["static_dir_path"])
        logger.info("Registered integration web UI: /integrations/%s/ui → %s", _iid, _web_ui["static_dir_path"])

    # Auto-start shared workspace containers that were previously running
    for _sw in _sw_rows:
        if _sw.status == "running":
            try:
                await shared_workspace_service.ensure_container(_sw)
            except Exception:
                logger.warning("Failed to auto-start shared workspace %s", _sw.name)
    # Embed workspace skills + start shared workspace watchers
    from app.services.workspace_skills import embed_workspace_skills as _embed_ws_skills
    _sw_watch_targets: list[tuple[str, str, bool]] = []
    for _sw in _sw_rows:
        if _sw.workspace_skills_enabled:
            try:
                await _embed_ws_skills(str(_sw.id))
            except Exception:
                logger.warning("Failed to embed workspace skills for %s", _sw.name)
        _sw_watch_targets.append(
            (str(_sw.id), shared_workspace_service.get_host_root(str(_sw.id)), bool(_sw.workspace_skills_enabled))
        )
    if _sw_watch_targets:
        from app.agent.fs_watcher import start_shared_workspace_watchers
        asyncio.create_task(start_shared_workspace_watchers(_sw_watch_targets))
    # Index filesystem directories + start watchers in background (doesn't block startup)
    asyncio.create_task(_index_filesystems_and_start_watchers())

    if settings.STT_PROVIDER:
        logger.info("Warming up STT provider (%s)...", settings.STT_PROVIDER)
        from app.stt import warm_up as stt_warm_up
        stt_warm_up()
    logger.info("Agent server ready. (LOG_LEVEL=%s)", settings.LOG_LEVEL.upper())
    from app.agent.tasks import task_worker
    asyncio.create_task(task_worker())
    from app.services.heartbeat import heartbeat_worker
    asyncio.create_task(heartbeat_worker())
    from app.services.usage_spike import usage_spike_worker
    asyncio.create_task(usage_spike_worker())
    from app.agent.fs_watcher import periodic_reindex_worker
    asyncio.create_task(periodic_reindex_worker())
    from app.services.attachment_summarizer import attachment_sweep_worker
    asyncio.create_task(attachment_sweep_worker())
    from app.services.attachment_retention import attachment_retention_worker
    asyncio.create_task(attachment_retention_worker())
    from app.services.data_retention import data_retention_worker
    asyncio.create_task(data_retention_worker())
    if settings.CONFIG_STATE_FILE:
        from app.services.config_export import config_export_worker
        asyncio.create_task(config_export_worker())

    # Start integration background processes (non-blocking, like other workers)
    from app.services.integration_processes import process_manager
    asyncio.create_task(process_manager.start_auto_start_processes())

    try:
        yield
    finally:
        await process_manager.shutdown_all()


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
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    )

# Config-mutation middleware: mark config dirty after admin mutations.
# Uses raw ASGI (not BaseHTTPMiddleware) to avoid buffering streaming responses.
from app.services.config_export import is_config_mutation, mark_config_dirty  # noqa: E402


class ConfigExportMiddleware:
    """ASGI middleware that marks config dirty on successful admin mutations."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")

        # Fast path: skip non-mutation requests entirely (zero overhead)
        if not is_config_mutation(method, path):
            await self.app(scope, receive, send)
            return

        status_code = None

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        await self.app(scope, receive, send_wrapper)

        if status_code is not None and status_code < 300:
            mark_config_dirty()


if settings.CONFIG_STATE_FILE:
    app.add_middleware(ConfigExportMiddleware)

# Register routers
from app.routers import auth, chat, sessions, transcribe  # noqa: E402
from app.routers.api_v1 import router as _api_v1_router  # noqa: E402

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(transcribe.router)
app.include_router(_api_v1_router)



@app.get("/health")
async def health():
    from app.config import VERSION
    return {"status": "ok", "version": VERSION}


# ---------------------------------------------------------------------------
# Integration web UI serving (SPA fallback)
# ---------------------------------------------------------------------------
# Registry populated during lifespan by discover_web_uis(); route defined here
# at module level so `app` unambiguously refers to the FastAPI instance.
_INTEGRATION_WEB_UI_DIRS: dict[str, Path] = {}


@app.get("/integrations/{integration_id}/ui/{path:path}")
async def serve_integration_ui(integration_id: str, path: str = ""):
    """Serve integration dashboard files with SPA fallback."""
    dist_dir = _INTEGRATION_WEB_UI_DIRS.get(integration_id)
    if not dist_dir:
        raise HTTPException(status_code=404, detail=f"No web UI for integration '{integration_id}'")

    # Serve exact file if it exists (JS/CSS assets, images, etc.)
    if path:
        file_path = (dist_dir / path).resolve()
        # Security: ensure resolved path doesn't escape dist_dir
        if str(file_path).startswith(str(dist_dir.resolve())) and file_path.is_file():
            from starlette.responses import FileResponse
            return FileResponse(file_path)

    # SPA fallback: serve index.html for any unknown path
    index = dist_dir / "index.html"
    if index.is_file():
        from starlette.responses import FileResponse
        return FileResponse(index, media_type="text/html")

    raise HTTPException(
        status_code=404,
        detail=f"Dashboard not built for '{integration_id}'. "
               f"Run 'npm run build' in the dashboard directory.",
    )
