"""Blocking startup bootstrap phases for the FastAPI lifespan."""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings
from app.db.engine import async_session, run_migrations

logger = logging.getLogger(__name__)


@dataclass
class StartupBootstrapResult:
    """Values the lifespan needs after blocking bootstrap completes."""

    shared_workspace_rows: list[Any]


def _tlog(label: str, t0: float) -> float:
    """Log elapsed time since t0 and return current time for next section."""
    now = time.monotonic()
    logger.info("[%.1fs] %s", now - t0, label)
    return now


async def _cleanup_orphaned_tools(registered_tools: dict) -> None:
    """Remove local_tools entries from bot configs that reference unregistered tools."""
    from app.agent.bots import list_bots, load_bots
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
    # Reload so in-memory configs reflect the cleanup.
    await load_bots()


async def _run_database_phase() -> None:
    logger.info("Running database migrations...")
    try:
        await run_migrations()
    except Exception:
        logger.critical("Database migration failed; refusing to start with stale schema", exc_info=True)
        raise


async def _run_config_phase() -> None:
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


async def _run_usage_config_phase() -> None:
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
    await _restore_config_state_if_needed()


async def _restore_config_state_if_needed() -> None:
    if not settings.CONFIG_STATE_FILE:
        return

    from sqlalchemy import select as sa_sel, func as sa_func

    from app.db.models import Bot as BotModel

    async with async_session() as _cs_db:
        bot_count = (await _cs_db.execute(sa_sel(sa_func.count()).select_from(BotModel))).scalar() or 0
    if bot_count != 0:
        return

    from app.services.config_export import restore_from_file
    from app.services.integration_settings import load_from_db as load_integration_settings
    from app.services.mcp_servers import load_mcp_servers
    from app.services.providers import load_providers
    from app.services.server_config import load_server_config
    from app.services.server_settings import load_settings_from_db

    await restore_from_file()
    # Reload providers/settings/server_config/integration_settings after restore.
    await load_providers()
    await load_settings_from_db()
    await load_server_config()
    await load_integration_settings()
    await load_mcp_servers()


async def _run_bot_workspace_phase() -> Any:
    from app.agent.bots import ensure_default_bot, load_bots, seed_bots_from_yaml

    logger.info("Seeding bots from YAML (seed-once)...")
    await seed_bots_from_yaml()
    logger.info("Loading bot configurations from DB...")
    await load_bots()
    await ensure_default_bot()

    from app.services.workspace_bootstrap import ensure_default_workspace, ensure_all_bots_enrolled

    async with async_session() as _ws_db:
        default_ws = await ensure_default_workspace(_ws_db)
        added = await ensure_all_bots_enrolled(_ws_db, default_ws.id)
        if added:
            logger.info("Auto-enrolled %d bot(s) into workspace", added)
            await load_bots()  # Reload so shared_workspace_id is populated.
    return default_ws


async def _run_registry_seed_phase() -> None:
    logger.info("Loading secret values from DB...")
    from app.services.secret_values import load_from_db as load_secret_values

    await load_secret_values()
    logger.info("Building secret registry...")
    from app.services.secret_registry import rebuild as rebuild_secret_registry

    await rebuild_secret_registry()
    logger.info("Ensuring orchestrator landing channel...")
    from app.services.channels import ensure_orchestrator_channel

    await ensure_orchestrator_channel()
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
    from app.services.integration_manifests import seed_manifests, load_manifests

    await seed_manifests()
    logger.info("Loading integration manifests from DB...")
    await load_manifests()
    from app.services.integration_settings import apply_bootstrap_integrations

    bootstrapped_integrations = await apply_bootstrap_integrations()
    if bootstrapped_integrations:
        logger.info(
            "Applied bootstrap integration intent: %s",
            ", ".join(bootstrapped_integrations),
        )
    from app.services.runtime_services import ensure_required_providers_for_active_integrations

    runtime_provider_sync = await ensure_required_providers_for_active_integrations()
    if runtime_provider_sync:
        logger.info(
            "Enabled runtime provider integrations: %s",
            "; ".join(
                f"{consumer} -> {', '.join(providers)}"
                for consumer, providers in sorted(runtime_provider_sync.items())
            ),
        )
    from app.services.widget_packages_seeder import seed_widget_packages

    await seed_widget_packages()
    from app.services.widget_templates import load_widget_templates_from_db

    await load_widget_templates_from_db()
    from app.services.pin_contract import wire_pin_contract

    wire_pin_contract()


async def _run_integration_dependency_phase() -> None:
    logger.info("Auto-installing missing integration dependencies...")
    from app.services.integration_deps import ensure_integration_deps

    await ensure_integration_deps()


async def _run_mcp_tool_phase() -> None:
    from app.services.mcp_servers import (
        load_mcp_servers,
        seed_from_integrations as seed_mcp_from_integrations,
        seed_from_yaml as seed_mcp_from_yaml,
    )

    logger.info("Seeding MCP servers from YAML (if empty)...")
    await seed_mcp_from_yaml()
    logger.info("Seeding MCP servers from integration manifests...")
    await seed_mcp_from_integrations()
    logger.info("Loading MCP servers from DB...")
    await load_mcp_servers()

    extra_tool_dirs = [Path(p.strip()).expanduser().resolve() for p in settings.TOOL_DIRS.split(":") if p.strip()]
    from app.services.paths import local_home_dir as _local_home_dir

    home = _local_home_dir()
    if home:
        home_tools = Path(home) / "tools"
        if home_tools.is_dir() and home_tools not in extra_tool_dirs:
            extra_tool_dirs.append(home_tools)
    logger.info("Discovering extra tool directories...")
    from app.tools.loader import discover_and_load_tools

    discover_and_load_tools(extra_tool_dirs)
    import app.tools.local  # noqa: F401

    try:
        from app.services.agent_harnesses import discover_and_load_harnesses

        discover_and_load_harnesses()
    except Exception:
        logger.exception("Failed to discover agent harness runtimes")


async def _run_orphan_tool_cleanup_phase() -> None:
    from app.tools.registry import _tools as _registered_tools

    await _cleanup_orphaned_tools(_registered_tools)


async def _run_file_skill_phase() -> None:
    from app.services.feature_validation import validate_features

    feature_warnings = await validate_features()
    if feature_warnings:
        logger.warning("Feature validation found %d warning(s)", len(feature_warnings))

    logger.info("Syncing file-sourced skills and knowledge...")
    from app.services import file_sync

    await file_sync.sync_all_files()
    logger.info("Loading skills from DB...")
    from app.agent.skills import load_skills

    await load_skills()


async def _run_skill_registry_phase() -> None:
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

    from app.services.workflows import load_workflows

    logger.info("Loading workflows from DB...")
    await load_workflows()
    from app.services.webhooks import load_webhook_endpoints

    logger.info("Loading webhook endpoints...")
    await load_webhook_endpoints()
    from app.services.bot_hooks import load_bot_hooks

    await load_bot_hooks()
    from app.services.pinned_panels import load_pinned_paths

    await load_pinned_paths()
    from app.services.workflow_hooks import register_workflow_hooks

    register_workflow_hooks()


async def _run_workspace_route_phase(
    application: Any,
    *,
    default_workspace: Any,
    integration_web_ui_dirs: dict[str, Path],
) -> list[Any]:
    from app.agent.bots import list_bots
    from app.services.memory_scheme import bootstrap_memory_scheme

    for bot in list_bots():
        if bot.memory_scheme == "workspace-files" and bot.workspace.enabled:
            try:
                bootstrap_memory_scheme(bot)
            except Exception:
                logger.exception("Failed to bootstrap memory scheme for bot %s", bot.id)

    from app.services.workspace import workspace_service

    for bot in list_bots():
        if bot.workspace.enabled:
            workspace_service.ensure_host_dir(bot.id, bot=bot)

    from sqlalchemy import select as sa_select

    from app.db.models import SharedWorkspace as _SW
    from app.services.shared_workspace import shared_workspace_service

    async with async_session() as _sw_db:
        sw_rows = (await _sw_db.execute(sa_select(_SW))).scalars().all()
    for sw in sw_rows:
        shared_workspace_service.ensure_host_dirs(str(sw.id))

    from app.services.paths import add_runtime_integration_dir

    if default_workspace:
        ws_int_path = os.path.join(
            shared_workspace_service.get_host_root(str(default_workspace.id)),
            "integrations",
        )
        os.makedirs(ws_int_path, exist_ok=True)
        add_runtime_integration_dir(ws_int_path)
        logger.info("Registered workspace integrations directory: %s", ws_int_path)

    from integrations.discovery import discover_integrations as _discover_integrations

    for integration_id, integration_router in _discover_integrations():
        try:
            application.include_router(
                integration_router,
                prefix=f"/integrations/{integration_id}",
                tags=[f"Integration: {integration_id}"],
            )
            logger.info("Registered integration: %s", integration_id)
        except Exception:
            logger.exception("Failed to register integration router: %s", integration_id)

    from app.agent.hooks import auto_register_from_manifest
    from app.services.integration_manifests import (
        get_all_manifests,
        validate_capabilities,
        validate_manifest_consistency,
        validate_provides,
        validate_tool_result_rendering,
    )

    for iid, manifest in get_all_manifests().items():
        auto_register_from_manifest(iid, manifest)

    validate_capabilities()
    validate_tool_result_rendering()
    validate_provides()
    validate_manifest_consistency()

    from app.services.endpoint_catalog import build_endpoint_catalog
    from app.services import api_keys as _api_keys_mod

    _api_keys_mod.ENDPOINT_CATALOG = build_endpoint_catalog(application)

    from app.services.integration_catalog import discover_web_uis as _discover_web_uis

    for web_ui in _discover_web_uis():
        iid = web_ui["integration_id"]
        integration_web_ui_dirs[iid] = Path(web_ui["static_dir_path"])
        logger.info("Registered integration web UI: /integrations/%s/ui -> %s", iid, web_ui["static_dir_path"])

    return list(sw_rows)


async def run_startup_bootstrap(
    application: Any,
    *,
    integration_web_ui_dirs: dict[str, Path],
) -> StartupBootstrapResult:
    """Run blocking startup setup and return state needed by runtime workers."""

    t = time.monotonic()
    await _run_database_phase()
    t = _tlog("Database migrations", t)
    await _run_config_phase()
    t = _tlog("Config loading (settings, integrations, providers, startup secrets)", t)
    await _run_usage_config_phase()
    t = _tlog("Usage limits, spike config, server config", t)
    default_workspace = await _run_bot_workspace_phase()
    t = _tlog("Bot seeding, loading, workspace bootstrap", t)
    await _run_registry_seed_phase()
    await _run_integration_dependency_phase()
    t = _tlog("Integration dependency auto-install", t)
    await _run_mcp_tool_phase()
    t = _tlog("Secrets, MCP, tools, orchestrator channel", t)
    await _run_orphan_tool_cleanup_phase()
    t = _tlog("Orphaned tool cleanup", t)
    await _run_file_skill_phase()
    t = _tlog("File sync (skills, knowledge, prompts, workflows)", t)
    await _run_skill_registry_phase()
    t = _tlog("Load workflows, webhooks", t)
    shared_workspace_rows = await _run_workspace_route_phase(
        application,
        default_workspace=default_workspace,
        integration_web_ui_dirs=integration_web_ui_dirs,
    )
    _tlog("Memory bootstrap, workspace dirs, integrations, endpoint catalog", t)
    return StartupBootstrapResult(shared_workspace_rows=shared_workspace_rows)
