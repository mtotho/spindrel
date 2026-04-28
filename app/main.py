import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException

from app.agent.bots import ensure_default_bot, list_bots, load_bots, seed_bots_from_yaml
from app.agent.skills import load_skills, seed_skills_from_files
from app.services import file_sync
from app.config import VERSION, settings
from app.db.engine import async_session, run_migrations
from app.tools.loader import discover_and_load_tools
from app.services.mcp_servers import load_mcp_servers, seed_from_yaml as seed_mcp_from_yaml, seed_from_integrations as seed_mcp_from_integrations
from app.services.integration_manifests import (
    seed_manifests, load_manifests,
    validate_capabilities, validate_provides, validate_manifest_consistency,
    validate_tool_result_rendering,
    get_all_manifests,
)

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"


def _tlog(label: str, t0: float) -> float:
    """Log elapsed time since t0 and return current time for next section."""
    now = time.monotonic()
    logger.info("[%.1fs] %s", now - t0, label)
    return now


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


@asynccontextmanager
async def lifespan(application: FastAPI):
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    # Durable JSONL log handler — survives container restarts so the
    # daily health summary can sweep yesterday's evidence even after a redeploy.
    from app.services.log_buffer import install as _install_log_buffer
    from app.services.log_file import install_jsonl_log_handler
    install_jsonl_log_handler()
    _install_log_buffer(capacity=10_000)
    # Validate EMBEDDING_DIMENSIONS — DB columns and halfvec indexes are built for 1536
    if settings.EMBEDDING_DIMENSIONS != 1536:
        raise RuntimeError(
            f"EMBEDDING_DIMENSIONS={settings.EMBEDDING_DIMENSIONS} but DB columns and indexes "
            f"are hardcoded to 1536. Do not change this value — models with different native "
            f"dimensions are zero-padded or Matryoshka-truncated automatically."
        )
    _t = _t_start = time.monotonic()
    logger.info("Running database migrations...")
    try:
        await run_migrations()
    except Exception:
        logger.critical("Database migration failed — refusing to start with stale schema", exc_info=True)
        raise
    _t = _tlog("Database migrations", _t)
    logger.info("Loading server settings from DB...")
    from app.services.server_settings import load_settings_from_db
    await load_settings_from_db()
    logger.info("Loading integration settings from DB...")
    from app.services.integration_settings import load_from_db as load_integration_settings
    await load_integration_settings()
    logger.info("Loading provider configs from DB...")
    from app.services.providers import seed_provider_from_file, load_providers
    await seed_provider_from_file()
    await load_providers()
    from app.services.startup_env import (
        ensure_encryption_key,
        ensure_jwt_secret,
        sync_home_host_dir_from_spindrel_home,
    )
    sync_home_host_dir_from_spindrel_home()
    await ensure_encryption_key()
    ensure_jwt_secret()
    _t = _tlog("Config loading (settings, integrations, providers, startup secrets)", _t)
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
    logger.info("Starting provider catalog refresh loop...")
    from app.services.provider_catalog_refresh import (
        start_refresh_task as _start_catalog_refresh,
    )
    _start_catalog_refresh()
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

    _t = _tlog("Usage limits, spike config, server config", _t)
    logger.info("Seeding bots from YAML (seed-once)...")
    await seed_bots_from_yaml()
    logger.info("Loading bot configurations from DB...")
    await load_bots()
    await ensure_default_bot()

    # Auto-create default workspace and enroll all bots
    from app.services.workspace_bootstrap import ensure_default_workspace, ensure_all_bots_enrolled
    async with async_session() as _ws_db:
        default_ws = await ensure_default_workspace(_ws_db)
        added = await ensure_all_bots_enrolled(_ws_db, default_ws.id)
        if added:
            logger.info("Auto-enrolled %d bot(s) into workspace", added)
            await load_bots()  # Reload so shared_workspace_id is populated
    _t = _tlog("Bot seeding, loading, workspace bootstrap", _t)

    logger.info("Loading secret values from DB...")
    from app.services.secret_values import load_from_db as load_secret_values
    await load_secret_values()
    logger.info("Building secret registry...")
    from app.services.secret_registry import rebuild as rebuild_secret_registry
    await rebuild_secret_registry()
    logger.info("Ensuring orchestrator landing channel...")
    from app.services.channels import ensure_orchestrator_channel
    await ensure_orchestrator_channel()
    # Backfill knowledge-base/ folders for channels that pre-date the KB
    # convention (shipped 2026-04-19). Idempotent; safe to run every boot.
    from app.services.channel_workspace import backfill_knowledge_base_dirs
    try:
        backfilled = await backfill_knowledge_base_dirs()
        if backfilled:
            logger.info("Ensured knowledge-base/ for %d existing channel(s)", backfilled)
    except Exception:
        logger.warning("KB backfill failed", exc_info=True)
    logger.info("Seeding system pipelines from YAML...")
    from app.services.task_seeding import ensure_system_pipelines
    await ensure_system_pipelines()
    logger.info("Synchronizing integration manifests...")
    await seed_manifests()
    logger.info("Loading integration manifests from DB...")
    await load_manifests()
    from app.services.integration_settings import apply_bootstrap_integrations
    _bootstrapped_integrations = await apply_bootstrap_integrations()
    if _bootstrapped_integrations:
        logger.info(
            "Applied bootstrap integration intent: %s",
            ", ".join(_bootstrapped_integrations),
        )
    from app.services.widget_packages_seeder import seed_widget_packages
    await seed_widget_packages()
    from app.services.widget_templates import load_widget_templates_from_db
    await load_widget_templates_from_db()
    # Wire pin contract resolver dependencies once registries are populated.
    # The package falls back to lazy auto-wiring when imported before this
    # call (e.g. by tests bypassing the lifespan), so this is just for
    # explicit ordering + observability.
    from app.services.pin_contract import wire_pin_contract
    wire_pin_contract()
    logger.info("Auto-installing missing integration dependencies...")
    from app.services.integration_deps import ensure_integration_deps
    await ensure_integration_deps()
    _t = _tlog("Integration dependency auto-install", _t)
    logger.info("Seeding MCP servers from YAML (if empty)...")
    await seed_mcp_from_yaml()
    logger.info("Seeding MCP servers from integration manifests...")
    await seed_mcp_from_integrations()
    logger.info("Loading MCP servers from DB...")
    await load_mcp_servers()
    extra_tool_dirs = [Path(p.strip()).expanduser().resolve() for p in settings.TOOL_DIRS.split(":") if p.strip()]
    # Also check SPINDREL_HOME for a top-level tools/ directory
    from app.services.paths import local_home_dir as _local_home_dir
    _home = _local_home_dir()
    if _home:
        _home_tools = Path(_home) / "tools"
        if _home_tools.is_dir() and _home_tools not in extra_tool_dirs:
            extra_tool_dirs.append(_home_tools)
    logger.info("Discovering extra tool directories...")
    discover_and_load_tools(extra_tool_dirs)
    # Import local tools to trigger @register decorators
    import app.tools.local  # noqa: F401
    # Import harness modules from active integrations so their runtimes
    # self-register before the bot dispatcher needs them.
    try:
        from app.services.agent_harnesses import discover_and_load_harnesses
        discover_and_load_harnesses()
    except Exception:
        logger.exception("Failed to discover agent harness runtimes")
    _t = _tlog("Secrets, MCP, tools, orchestrator channel", _t)

    # Orphan cleanup needs the registry but no embedding calls — keep blocking
    from app.tools.registry import _tools as _registered_tools
    await _cleanup_orphaned_tools(_registered_tools)
    _t = _tlog("Orphaned tool cleanup", _t)

    # Feature validation (memory scheme tools, etc.)
    from app.services.feature_validation import validate_features
    _feature_warnings = await validate_features()
    if _feature_warnings:
        logger.warning("Feature validation found %d warning(s)", len(_feature_warnings))

    logger.info("Syncing file-sourced skills and knowledge...")
    await file_sync.sync_all_files()
    _t = _tlog("File sync (skills, knowledge, prompts, workflows)", _t)
    logger.info("Loading skills from DB...")
    await load_skills()
    _t = _tlog("Load skills (embedding check)", _t)
    from app.services.skill_enrollment import backfill_missing_starter_skills
    try:
        starter_backfilled = await backfill_missing_starter_skills()
        if starter_backfilled:
            logger.info(
                "Ensured %d missing starter skill enrollment(s) for existing bots",
                starter_backfilled,
            )
    except Exception:
        logger.warning("Starter-skill backfill failed", exc_info=True)
    # Workflow YAML seeding is handled by sync_all_files() above; just load registry.
    from app.services.workflows import load_workflows
    logger.info("Loading workflows from DB...")
    await load_workflows()
    # Load webhook endpoints into cache
    from app.services.webhooks import load_webhook_endpoints
    logger.info("Loading webhook endpoints...")
    await load_webhook_endpoints()
    # Load bot hooks into cache
    from app.services.bot_hooks import load_bot_hooks
    await load_bot_hooks()
    # Load pinned-panel path index
    from app.services.pinned_panels import load_pinned_paths
    await load_pinned_paths()
    # Register workflow task completion hook
    from app.services.workflow_hooks import register_workflow_hooks
    register_workflow_hooks()
    _t = _tlog("Load workflows, webhooks", _t)

    from app.services.startup_runtime import (
        StartupRuntimeHandle,
        shutdown_runtime_services,
        start_boot_background_services,
        start_file_source_watcher,
        start_ready_runtime_services,
    )

    _runtime = StartupRuntimeHandle()
    logger.info("Starting file watcher...")
    start_file_source_watcher(_runtime)

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

    # Auto-append workspace integrations directory so bots can scaffold
    # integrations at /workspace/integrations/ and they're discovered on restart.
    from app.services.paths import add_runtime_integration_dir
    if default_ws:
        _ws_int_path = os.path.join(
            shared_workspace_service.get_host_root(str(default_ws.id)),
            "integrations",
        )
        os.makedirs(_ws_int_path, exist_ok=True)
        add_runtime_integration_dir(_ws_int_path)
        logger.info("Registered workspace integrations directory: %s", _ws_int_path)

    # Discover and register integration routers
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

    # Auto-register IntegrationMeta from manifests for integrations that
    # have binding.client_id_prefix but no hooks.py (or a minimal hooks.py).
    from app.agent.hooks import auto_register_from_manifest
    for _iid, _manifest in get_all_manifests().items():
        auto_register_from_manifest(_iid, _manifest)

    # Validate integration manifests against runtime state
    validate_capabilities()
    validate_tool_result_rendering()
    validate_provides()
    validate_manifest_consistency()

    # Build endpoint catalog from route introspection (after all routers registered)
    from app.services.endpoint_catalog import build_endpoint_catalog
    from app.services import api_keys as _api_keys_mod
    _api_keys_mod.ENDPOINT_CATALOG = build_endpoint_catalog(application)

    # Discover integration web UIs and populate the module-level registry.
    # The actual route handler is registered at module level (after app = FastAPI(...))
    # because the lifespan `app` parameter can collide with the `app` package name.
    from integrations import discover_web_uis as _discover_web_uis
    for _web_ui in _discover_web_uis():
        _iid = _web_ui["integration_id"]
        _INTEGRATION_WEB_UI_DIRS[_iid] = Path(_web_ui["static_dir_path"])
        logger.info("Registered integration web UI: /integrations/%s/ui → %s", _iid, _web_ui["static_dir_path"])

    _t = _tlog("Memory bootstrap, workspace dirs, integrations, endpoint catalog", _t)

    start_boot_background_services(_runtime, shared_workspace_rows=_sw_rows)
    _t = _tlog("Container auto-start, watchers, background warmup launched", _t)

    if settings.STT_PROVIDER:
        logger.info("Warming up STT provider (%s)...", settings.STT_PROVIDER)
        from app.stt import warm_up as stt_warm_up
        stt_warm_up()
        _t = _tlog("STT warmup", _t)
    logger.info("[%.1fs] TOTAL startup (blocking)", time.monotonic() - _t_start)
    logger.info(
        "Agent server ready. (LOG_LEVEL=%s instance=%s network=%s)",
        settings.LOG_LEVEL.upper(),
        settings.SPINDREL_INSTANCE_ID,
        settings.AGENT_NETWORK_NAME or "(none)",
    )
    await start_ready_runtime_services(_runtime)

    try:
        yield
    finally:
        await shutdown_runtime_services(_runtime)


app = FastAPI(
    title="Spindrel",
    description="Self-hosted LLM agent server. Integration API at /api/v1/ — see /docs.",
    version=VERSION,
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Chat", "description": "Send messages and stream responses"},
        {"name": "Admin — Bots", "description": "Bot configuration and management"},
        {"name": "Admin — Channels", "description": "Channel CRUD, settings, heartbeats, integrations"},
        {"name": "Admin — Tasks", "description": "Scheduled and deferred task management"},
        {"name": "Admin — Workflows", "description": "Workflow definitions and run management"},
        {"name": "Admin — Carapaces", "description": "Composable expertise bundle management"},
        {"name": "Admin — Providers", "description": "LLM provider configuration"},
        {"name": "Admin — Settings", "description": "Server settings and operations"},
        {"name": "Admin — Users", "description": "User and API key management"},
        {"name": "Admin — Tools", "description": "Tool listing, execution, and policies"},
        {"name": "Admin — Integrations", "description": "Integration activation and configuration"},
        {"name": "Admin — Usage", "description": "Token usage, cost tracking, and budgets"},
        {"name": "Sessions", "description": "Session and message history"},
        {"name": "Discovery", "description": "Endpoint discovery and API documentation"},
    ],
)

# CORS — always allow loopback UI origins for local dev; extend with
# CORS_ORIGINS env var for non-loopback hosts.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

_cors_origins: list[str] = [
    "http://localhost:5173",   # Vite dev server
    "http://localhost:8081",
    "http://localhost:19006",  # Expo dev server (legacy)
]
_cors_origins.extend(
    o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"^https?://(localhost|127(?:\.\d{1,3}){3}|\[::1\])(?::\d+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

# Vendored widget runtime — React + ReactDOM + Babel-standalone served
# same-origin so `runtime: react` HTML widgets inside the iframe sandbox
# can <script src="/widget-runtime/..."> them without a CSP carve-out.
# Self-host friendly: no CDN dependency.
from fastapi.staticfiles import StaticFiles  # noqa: E402

_WIDGET_RUNTIME_DIR = Path(__file__).resolve().parent / "static" / "widget-runtime"
if _WIDGET_RUNTIME_DIR.is_dir():
    app.mount(
        "/widget-runtime",
        StaticFiles(directory=str(_WIDGET_RUNTIME_DIR)),
        name="widget-runtime",
    )

# Rate limiting (opt-in, in-memory token bucket)
if settings.RATE_LIMIT_ENABLED:
    from app.services.rate_limiter import RateLimitMiddleware, RateSpec  # noqa: E402
    app.add_middleware(
        RateLimitMiddleware,
        default_spec=RateSpec.parse(settings.RATE_LIMIT_DEFAULT),
        chat_spec=RateSpec.parse(settings.RATE_LIMIT_CHAT),
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

# Domain-error → HTTP adapter. Keeps services/agent code out of ``fastapi``.
from app.domain.errors import install_domain_error_handler  # noqa: E402

install_domain_error_handler(app)


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


# ---------------------------------------------------------------------------
# Main UI — serve built React SPA from ui-dist/ (baked into Docker image)
# ---------------------------------------------------------------------------
# IMPORTANT: We cannot use app.mount("/", ...) because Starlette Mounts at "/"
# swallow ALL requests including API routes. Instead, we add a lowest-priority
# middleware that serves static files only when no API route matched (404).
_UI_DIST = Path(__file__).resolve().parent.parent / "ui-dist"
if _UI_DIST.is_dir():
    import mimetypes
    from starlette.responses import FileResponse, Response
    from starlette.types import Receive, Scope, Send

    _UI_INDEX = _UI_DIST / "index.html"

    class SPAFallbackMiddleware:
        """ASGI middleware that serves the SPA when the app returns 404.

        Only intercepts GET requests — API POSTs etc. pass through untouched.
        Serves exact file matches from ui-dist/, falls back to index.html
        for client-side routing.
        """
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            path = scope.get("path", "")
            if (
                scope["type"] != "http"
                or scope.get("method", "") != "GET"
                or path.startswith("/api/")
                or path.startswith("/health")
                or path.startswith("/integrations/")
            ):
                await self.app(scope, receive, send)
                return

            # Capture the response status
            response_started = False
            status_code = 0

            async def send_wrapper(message):
                nonlocal response_started, status_code
                if message["type"] == "http.response.start":
                    status_code = message["status"]
                    if status_code != 404:
                        response_started = True
                        await send(message)
                        return
                    # 404 — don't send yet, we'll try the SPA
                    return
                if message["type"] == "http.response.body":
                    if response_started:
                        await send(message)
                        return
                    # This is the 404 body — suppress it, serve SPA instead

            await self.app(scope, receive, send_wrapper)

            if not response_started and status_code == 404:
                # Try serving a static file from ui-dist
                path = scope.get("path", "/").lstrip("/")
                file_path = (_UI_DIST / path).resolve()
                if (
                    path
                    and str(file_path).startswith(str(_UI_DIST.resolve()))
                    and file_path.is_file()
                ):
                    resp = FileResponse(file_path)
                else:
                    resp = FileResponse(_UI_INDEX, media_type="text/html")
                await resp(scope, receive, send)

    app = SPAFallbackMiddleware(app)
