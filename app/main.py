import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException

from app.utils import safe_create_task

from app.agent.bots import ensure_default_bot, list_bots, load_bots, seed_bots_from_yaml
from app.agent.skills import load_skills, seed_skills_from_files
from app.services import file_sync
from app.agent.tools import (
    index_local_tools,
    validate_pinned_tools,
    warm_mcp_tool_index_for_all_bots,
)
from app.config import VERSION, settings
from app.db.engine import async_session, run_migrations
from app.tools.loader import discover_and_load_tools
from app.services.mcp_servers import load_mcp_servers, seed_from_yaml as seed_mcp_from_yaml, seed_from_integrations as seed_mcp_from_integrations
from app.services.integration_manifests import (
    seed_manifests, load_manifests,
    validate_capabilities, validate_provides, validate_manifest_consistency,
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


_LEGACY_INTEGRATION_CONTAINER_NAMES = (
    "spindrel-searxng",
    "spindrel-playwright",
    "spindrel-wyoming-whisper",
    "spindrel-wyoming-piper",
)
_LEGACY_CLEANUP_SETTING_KEY = "legacy_integration_containers_cleaned"


async def _legacy_integration_container_cleanup() -> None:
    """Remove pre-multi-instance integration containers that squat on globally
    unique names. One-shot, guarded by a ``server_settings`` flag so it only
    runs on the first boot after this code ships.
    """
    import asyncio as _asyncio
    from app.db.engine import async_session
    from app.db.models import ServerSetting
    from sqlalchemy import select

    async with async_session() as db:
        existing = (await db.execute(
            select(ServerSetting).where(ServerSetting.key == _LEGACY_CLEANUP_SETTING_KEY)
        )).scalar_one_or_none()
        if existing and existing.value == "1":
            return

    removed: list[str] = []
    for name in _LEGACY_INTEGRATION_CONTAINER_NAMES:
        try:
            proc = await _asyncio.create_subprocess_exec(
                "docker", "inspect", "--format",
                '{{index .Config.Labels "com.docker.stack-id"}}|{{.State.Status}}',
                name,
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.PIPE,
            )
            out, _ = await proc.communicate()
            if proc.returncode != 0:
                continue  # No such container — nothing to do
            label, _, _status = out.decode().strip().partition("|")
            if label:
                # Labeled by a stack — leave it to the stack service to manage
                continue
            rm = await _asyncio.create_subprocess_exec(
                "docker", "rm", "-f", name,
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.PIPE,
            )
            rm_out, rm_err = await rm.communicate()
            if rm.returncode == 0:
                removed.append(name)
            else:
                logger.warning(
                    "Legacy container cleanup: failed to rm %s: %s",
                    name, rm_err.decode().strip(),
                )
        except Exception:
            logger.warning("Legacy container cleanup: inspect failed for %s", name, exc_info=True)

    async with async_session() as db:
        row = ServerSetting(key=_LEGACY_CLEANUP_SETTING_KEY, value="1")
        await db.merge(row)
        await db.commit()

    if removed:
        logger.warning(
            "Legacy integration cleanup: removed %d orphan container(s): %s. "
            "Integration stacks will be recreated under instance-scoped names.",
            len(removed), ", ".join(removed),
        )


async def _index_filesystems_and_start_watchers() -> None:
    """Index workspace and legacy filesystem directories, then start file watchers.

    Runs as a background task so it doesn't block server startup.
    """
    from app.agent.fs_indexer import index_directory
    from app.agent.fs_watcher import start_watchers
    from app.services.bot_indexing import reindex_bot

    logger.info("Background: reindexing workspaces + memory for all bots...")
    for bot in list_bots():
        try:
            await reindex_bot(bot, force=True, cleanup_orphans=True)
        except Exception:
            logger.exception("Failed to reindex bot %s", bot.id)
        for cfg in bot.filesystem_indexes:
            try:
                stats = await index_directory(cfg.root, bot.id, cfg.patterns, force=True)
                logger.info("Indexed %s for bot %s: %s", cfg.root, bot.id, stats)
            except Exception:
                logger.exception("Failed to index %s for bot %s", cfg.root, bot.id)
    await start_watchers(list_bots())
    logger.info("Background: filesystem indexing complete.")

    # Warm contextual retrieval cache from existing filesystem chunk metadata
    if settings.CONTEXTUAL_RETRIEVAL_ENABLED:
        try:
            from sqlalchemy import select as _sel
            from app.agent.contextual_retrieval import warm_cache_from_metadata
            from app.db.models import FilesystemChunk
            async with async_session() as _db:
                cr_rows = (await _db.execute(
                    _sel(
                        FilesystemChunk.content_hash,
                        FilesystemChunk.chunk_index,
                        FilesystemChunk.metadata_["contextual_description"].as_string(),
                    ).where(
                        FilesystemChunk.metadata_["contextual_description"].as_string().is_not(None)
                    ).limit(10_000)
                )).all()
            warmed = warm_cache_from_metadata(cr_rows)
            if warmed:
                logger.info("Warmed contextual retrieval cache from %d filesystem chunk(s)", warmed)
        except Exception:
            logger.debug("Contextual retrieval cache warm-up failed", exc_info=True)


@asynccontextmanager
async def lifespan(application: FastAPI):
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    # Install in-memory ring buffer handler for /api/v1/admin/server-logs
    from app.services.log_buffer import install as _install_log_buffer
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
    # Sync SPINDREL_HOME → HOME_HOST_DIR in .env so docker-compose can mount it.
    # This runs inside the container after DB settings are loaded.  The value
    # takes effect on the NEXT container restart (compose re-reads .env).
    if settings.SPINDREL_HOME and not os.environ.get("HOME_HOST_DIR"):
        _env_path_home = os.path.join(os.getcwd(), ".env")
        try:
            import re as _re_home
            _home_val = settings.SPINDREL_HOME
            if os.path.isfile(_env_path_home):
                with open(_env_path_home) as f:
                    _env_content_home = f.read()
                if "HOME_HOST_DIR=" in _env_content_home:
                    _env_content_home = _re_home.sub(
                        r"^#?\s*HOME_HOST_DIR=.*$",
                        f"HOME_HOST_DIR={_home_val}",
                        _env_content_home,
                        count=1,
                        flags=_re_home.MULTILINE,
                    )
                else:
                    _env_content_home += f"\nHOME_HOST_DIR={_home_val}\n"
                with open(_env_path_home, "w") as f:
                    f.write(_env_content_home)
            else:
                with open(_env_path_home, "a") as f:
                    f.write(f"\nHOME_HOST_DIR={_home_val}\n")
            logger.info("Synced SPINDREL_HOME=%s to .env as HOME_HOST_DIR (takes effect on next restart)", _home_val)
        except OSError:
            logger.warning("Could not sync SPINDREL_HOME to .env — set HOME_HOST_DIR manually")

    # Auto-generate ENCRYPTION_KEY on first boot if not set and no encrypted
    # secrets exist yet.  Writes the key to .env so it persists across restarts.
    from app.services.encryption import is_encryption_enabled, generate_key, reset as _reset_encryption
    if not is_encryption_enabled():
        from app.services.providers import has_encrypted_secrets
        if await has_encrypted_secrets():
            raise RuntimeError(
                "ENCRYPTION_KEY is not set but the database contains encrypted secrets (enc: prefix). "
                "These values cannot be decrypted without the original key. "
                "Set ENCRYPTION_KEY in .env to the key used to encrypt them."
            )
        # No encrypted secrets — safe to generate a new key
        import re as _re
        new_key = generate_key()
        settings.ENCRYPTION_KEY = new_key
        _reset_encryption()  # clear cached state so next check picks up the new key
        # Persist to .env file
        _env_path = os.path.join(os.getcwd(), ".env")
        try:
            if os.path.isfile(_env_path):
                with open(_env_path) as f:
                    _env_content = f.read()
                if "ENCRYPTION_KEY=" in _env_content:
                    _env_content = _re.sub(
                        r"^#?\s*ENCRYPTION_KEY=.*$",
                        f"ENCRYPTION_KEY={new_key}",
                        _env_content,
                        count=1,
                        flags=_re.MULTILINE,
                    )
                else:
                    _env_content += f"\nENCRYPTION_KEY={new_key}\n"
                with open(_env_path, "w") as f:
                    f.write(_env_content)
            else:
                with open(_env_path, "w") as f:
                    f.write(f"ENCRYPTION_KEY={new_key}\n")
            logger.info("Auto-generated ENCRYPTION_KEY and saved to .env — back this up!")
        except OSError:
            logger.warning(
                "Auto-generated ENCRYPTION_KEY but could not write to .env. "
                "Add the key from the running config to your environment to persist it."
            )
    _t = _tlog("Config loading (settings, integrations, providers, encryption)", _t)
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
    from app.agent.base_prompt import load_base_prompt
    load_base_prompt()
    logger.info("Synchronizing integration manifests...")
    await seed_manifests()
    logger.info("Loading integration manifests from DB...")
    await load_manifests()
    from app.services.widget_packages_seeder import seed_widget_packages
    await seed_widget_packages()
    from app.services.widget_templates import load_widget_templates_from_db
    await load_widget_templates_from_db()
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
    logger.info("Starting file watcher...")
    _workers: list[asyncio.Task] = []
    _workers.append(safe_create_task(file_sync.watch_files(), name="file_watcher"))

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

    # Ensure shared workspace directories exist
    for _sw in _sw_rows:
        try:
            shared_workspace_service.ensure_host_dirs(str(_sw.id))
        except Exception:
            logger.warning("Failed to ensure workspace dirs for %s", _sw.name)
    # Start shared workspace watchers (fast — no embedding)
    _sw_watch_targets: list[tuple[str, str]] = [
        (str(_sw.id), shared_workspace_service.get_host_root(str(_sw.id)))
        for _sw in _sw_rows
    ]
    if _sw_watch_targets:
        from app.agent.fs_watcher import start_shared_workspace_watchers
        _workers.append(safe_create_task(start_shared_workspace_watchers(_sw_watch_targets), name="sw_watchers"))
    # Index filesystem directories + start watchers in background (doesn't block startup)
    _workers.append(safe_create_task(_index_filesystems_and_start_watchers(), name="fs_index"))

    # ---------------------------------------------------------------------------
    # Background warmup: embedding indexes, MCP tool fetching, docker stacks.
    # These are safe to run after the server is ready — they only populate RAG
    # indexes and reconcile container state.  Content-hash checks skip unchanged
    # items, so steady-state restarts finish quickly.
    # ---------------------------------------------------------------------------

    async def _background_warmup() -> None:
        import time as _time
        _t0 = _time.monotonic()
        logger.info("Background warmup: starting...")

        # Phase 1: Tool & MCP indexing (parallel)
        logger.info("Background warmup: indexing local tools + MCP tools...")
        async def _index_tools():
            await index_local_tools()
            await warm_mcp_tool_index_for_all_bots()
            await validate_pinned_tools()

        await asyncio.gather(
            _index_tools(),
            return_exceptions=True,
        )

        # Phase 2: Docker stack reconciliation
        if settings.DOCKER_STACKS_ENABLED:
            try:
                from app.services.docker_stacks import stack_service
                fixed = await stack_service.reconcile_running()
                if fixed:
                    logger.info("Reconciled %d docker stack(s) to stopped", fixed)
            except Exception:
                logger.exception("Failed to reconcile docker stacks")

            # One-shot legacy orphan sweep. Pre-multi-instance builds used
            # hard-coded container_name values (`spindrel-searxng`,
            # `spindrel-playwright`, `spindrel-wyoming-whisper/piper`) which
            # are globally unique on the Docker daemon. Remove any such
            # orphan containers (no ``com.docker.stack-id`` label, not owned
            # by a currently-tracked integration stack) so compose can
            # recreate them under instance-scoped names.
            try:
                await _legacy_integration_container_cleanup()
            except Exception:
                logger.exception("Legacy integration container cleanup failed")

        # Sync integration Docker Compose stacks
        try:
            from app.services.docker_stacks import stack_service
            from integrations import discover_docker_compose_stacks
            from app.services.integration_settings import get_value as _get_int_setting
            for _dc_info in discover_docker_compose_stacks():
                _int_id = _dc_info["integration_id"]
                try:
                    _enabled = False
                    _enabled_callable = _dc_info.get("enabled_callable")
                    if _enabled_callable is not None:
                        try:
                            _enabled = bool(_enabled_callable())
                        except Exception:
                            logger.exception("enabled_callable failed for %s", _int_id)
                            _enabled = False
                    elif _dc_info["enabled_setting"]:
                        _default = _dc_info.get("enabled_default", "false")
                        _val = _get_int_setting(_int_id, _dc_info["enabled_setting"], _default)
                        _enabled = _val.lower() in ("true", "1", "yes")
                    await stack_service.apply_integration_stack(
                        integration_id=_int_id,
                        name=_dc_info["description"] or _int_id,
                        compose_definition=_dc_info["compose_definition"],
                        project_name=_dc_info["project_name"],
                        enabled=_enabled,
                        description=_dc_info["description"],
                        config_files=_dc_info["config_files"],
                    )
                except Exception:
                    logger.exception("Failed to sync integration stack: %s", _int_id)
        except Exception:
            logger.exception("Failed to discover/sync integration docker stacks")

        _elapsed = _time.monotonic() - _t0
        logger.info("Background warmup: complete in %.1fs", _elapsed)

    _workers.append(safe_create_task(_background_warmup(), name="bg_warmup"))
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
    from app.agent.tasks import task_worker
    _workers.append(safe_create_task(task_worker(), name="task_worker"))
    from app.services.heartbeat import heartbeat_worker
    _workers.append(safe_create_task(heartbeat_worker(), name="heartbeat_worker"))
    from app.services.usage_spike import usage_spike_worker
    _workers.append(safe_create_task(usage_spike_worker(), name="usage_spike_worker"))
    from app.agent.fs_watcher import periodic_reindex_worker
    _workers.append(safe_create_task(periodic_reindex_worker(), name="periodic_reindex"))
    from app.services.attachment_summarizer import attachment_sweep_worker
    _workers.append(safe_create_task(attachment_sweep_worker(), name="attachment_sweep"))
    from app.services.attachment_retention import attachment_retention_worker
    _workers.append(safe_create_task(attachment_retention_worker(), name="attachment_retention"))
    from app.services.data_retention import data_retention_worker
    _workers.append(safe_create_task(data_retention_worker(), name="data_retention"))
    if settings.CONFIG_STATE_FILE:
        from app.services.config_export import config_export_worker
        _workers.append(safe_create_task(config_export_worker(), name="config_export"))

    # Periodic session store cleanup (session allows only)
    async def _session_cleanup_worker():
        while True:
            try:
                await asyncio.sleep(600)  # every 10 minutes
                from app.agent.session_allows import cleanup_stale as _allow_cleanup
                from app.services.session_locks import sweep_stale as _lock_sweep
                allow_removed = _allow_cleanup()
                # session_locks janitor: sweep entries older than the
                # default TTL (2 hours). Drops locks leaked by background
                # tasks cancelled before their try-block runs.
                lock_removed = _lock_sweep()
                if allow_removed or lock_removed:
                    logger.debug(
                        "Session cleanup: %d allow + %d session-lock entries evicted",
                        allow_removed, lock_removed,
                    )
            except Exception:
                logger.warning("Session cleanup failed", exc_info=True)
    _workers.append(safe_create_task(_session_cleanup_worker(), name="session_cleanup"))

    # Start integration background processes (non-blocking, like other workers)
    from app.services.integration_processes import process_manager
    _workers.append(safe_create_task(process_manager.start_auto_start_processes(), name="integration_processes"))

    # Start one IntegrationDispatcherTask per registered ChannelRenderer
    # (Phase B of the Integration Delivery refactor). Phase C1 imports
    # `app.integrations.core_renderers` so the four core renderers
    # (none / web / webhook / internal) self-register before this loop
    # runs. Phase F adds `SlackRenderer`. Phase D (this) wires the real
    # channel → DispatchTarget resolver via `dispatch_resolution`.
    import app.integrations.core_renderers  # noqa: F401  registers core renderers
    # Integration-specific renderers (Slack, Discord, BlueBubbles, …) are
    # auto-imported by the integration discovery loop above (line 424,
    # which calls `discover_integrations()` → `_load_single_integration`
    # → auto-imports `renderer.py`). Each integration's renderer.py runs
    # a `_register()` helper at import time so by the time we reach this
    # block, the registry is already populated. Never `import
    # integrations.X.renderer` explicitly from `app/` — that breaks the
    # boundary the discovery system was built to enforce.
    from app.integrations.renderer_registry import all_renderers
    from app.services.channel_renderers import IntegrationDispatcherTask
    from app.services.dispatch_resolution import resolve_target_for_renderer
    _renderer_dispatchers: list[IntegrationDispatcherTask] = []
    for _renderer in all_renderers().values():
        async def _resolve(channel_id, _r=_renderer):
            return await resolve_target_for_renderer(channel_id, _r.integration_id)
        _disp = IntegrationDispatcherTask(_renderer, _resolve)
        _disp.start()
        _renderer_dispatchers.append(_disp)
        logger.info("Started IntegrationDispatcherTask for renderer %r", _renderer.integration_id)

    # Outbox drainer. Pulls pending outbox rows and routes them through
    # the renderer registry. Persist_turn enqueues one row per dispatch
    # target inside the same DB transaction as the message inserts; the
    # drainer fans them out asynchronously to integration renderers.
    #
    # Recovery sweep first: any rows left in IN_FLIGHT from a previous
    # process that crashed mid-delivery are stranded — fetch_pending only
    # sees PENDING / FAILED_RETRYABLE. Reset them to PENDING so the
    # drainer picks them up on its next batch.
    from app.services.outbox import reset_stale_in_flight
    from app.services.outbox_drainer import outbox_drainer_worker
    try:
        from app.db.engine import async_session as _outbox_session
        async with _outbox_session() as _db:
            _recovered = await reset_stale_in_flight(_db)
        if _recovered:
            logger.info("outbox: recovered %d stale IN_FLIGHT row(s) from previous run", _recovered)
    except Exception:
        logger.exception("outbox: stale IN_FLIGHT recovery failed (drainer will continue)")
    _workers.append(safe_create_task(outbox_drainer_worker(), name="outbox_drainer"))

    # Heartbeat startup recovery — same crash-gap shape as outbox: a
    # HeartbeatRun row flipped to ``status='running'`` that never reached
    # its follow-up write is stranded forever, wedging the run history view.
    # Reset before the worker launches so the next fire starts from a clean
    # terminal state.
    try:
        from app.services.heartbeat import reset_stale_running_runs
        from app.db.engine import async_session as _hb_session
        async with _hb_session() as _db:
            _hb_recovered = await reset_stale_running_runs(_db)
        if _hb_recovered:
            logger.info("heartbeat: recovered %d stale running run(s) from previous process", _hb_recovered)
    except Exception:
        logger.exception("heartbeat: stale running-run recovery failed (worker will continue)")

    # Widget SDK Phase B.4 — restore widget.py @on_event subscribers for every
    # pin whose bundle declares events. Best-effort: a single broken bundle
    # must not block server boot.
    try:
        from app.services.widget_events import register_all_pins_on_startup
        await register_all_pins_on_startup()
    except Exception:
        logger.exception("widget_events: startup registration failed")

    try:
        yield
    finally:
        # Cancel every live widget @on_event subscriber task before SSE shutdown
        # so we don't spend shutdown time waiting on subscribe() generators.
        try:
            from app.services.widget_events import unregister_all_on_shutdown
            await unregister_all_on_shutdown()
        except Exception:
            logger.exception("widget_events: shutdown cancellation failed")

        # Signal SSE connections to close. By the time we get here, uvicorn's
        # --timeout-graceful-shutdown has already force-closed connections, but
        # this ensures clean subscriber cleanup for any stragglers.
        from app.services.channel_events import signal_shutdown
        signal_shutdown()

        # Stop renderer dispatchers cleanly so per-channel state is dropped.
        for _disp in _renderer_dispatchers:
            await _disp.stop()

        # Close every renderer's module-level httpx.AsyncClient so process
        # shutdown doesn't log a "Unclosed client session" resource warning.
        # Each renderer module exposes its client as ``_http``; we look it
        # up reflectively so adding a new integration doesn't require
        # editing this list.
        from app.integrations.renderer_registry import all_renderers
        import importlib
        _renderer_modules: set[str] = set()
        for _r in all_renderers().values():
            mod_name = type(_r).__module__
            _renderer_modules.add(mod_name)
        # Also close the core_renderers WebhookRenderer client.
        _renderer_modules.add("app.integrations.core_renderers")
        for _mod_name in _renderer_modules:
            try:
                _mod = importlib.import_module(_mod_name)
                _client = getattr(_mod, "_http", None)
                if _client is not None and hasattr(_client, "aclose"):
                    await _client.aclose()
            except Exception:
                logger.debug(
                    "Failed to close httpx client in %s during shutdown",
                    _mod_name, exc_info=True,
                )

        for w in _workers:
            w.cancel()
        await asyncio.gather(*_workers, return_exceptions=True)
        await process_manager.shutdown_all()


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

# CORS — always allow localhost UI ports; extend with CORS_ORIGINS env var
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
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
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
