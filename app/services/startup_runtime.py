"""Startup runtime lifecycle helpers.

This module owns long-lived background workers and shutdown cleanup launched
from the FastAPI lifespan. Startup bootstrap remains in ``app.main``; runtime
processes live here so recovery, worker launch, and shutdown policy have one
local seam.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from app.config import settings
from app.utils import safe_create_task

logger = logging.getLogger(__name__)

_LEGACY_INTEGRATION_CONTAINER_NAMES = (
    "spindrel-searxng",
    "spindrel-playwright",
    "spindrel-wyoming-whisper",
    "spindrel-wyoming-piper",
)
_LEGACY_CLEANUP_SETTING_KEY = "legacy_integration_containers_cleaned"


@dataclass
class StartupRuntimeHandle:
    """Mutable handle for runtime tasks started by the lifespan."""

    workers: list[asyncio.Task] = field(default_factory=list)
    renderer_dispatchers: list[Any] = field(default_factory=list)
    process_manager: Any | None = None

    def schedule(self, coro: Any, *, name: str) -> asyncio.Task:
        task = safe_create_task(coro, name=name)
        self.workers.append(task)
        return task


def start_file_source_watcher(handle: StartupRuntimeHandle) -> None:
    """Start the file-sync watcher at the same point as the legacy lifespan."""
    from app.services import file_sync

    handle.schedule(file_sync.watch_files(), name="file_watcher")


def start_boot_background_services(
    handle: StartupRuntimeHandle,
    *,
    shared_workspace_rows: Iterable[Any],
) -> None:
    """Launch non-blocking boot work after workspace/integration setup."""
    from app.agent.fs_watcher import start_shared_workspace_watchers
    from app.services.shared_workspace import shared_workspace_service

    sw_rows = list(shared_workspace_rows)
    for sw in sw_rows:
        try:
            shared_workspace_service.ensure_host_dirs(str(sw.id))
        except Exception:
            logger.warning("Failed to ensure workspace dirs for %s", sw.name)

    sw_watch_targets = [
        (str(sw.id), shared_workspace_service.get_host_root(str(sw.id)))
        for sw in sw_rows
    ]
    if sw_watch_targets:
        handle.schedule(
            start_shared_workspace_watchers(sw_watch_targets),
            name="sw_watchers",
        )
    handle.schedule(index_filesystems_and_start_watchers(), name="fs_index")
    handle.schedule(background_warmup(), name="bg_warmup")

    from app.services.project_run_stall_sweep import (
        _sweep_disabled_via_env,
        project_run_stall_sweep_loop,
    )
    if not _sweep_disabled_via_env():
        handle.schedule(project_run_stall_sweep_loop(), name="project_run_stall_sweep")


async def index_filesystems_and_start_watchers() -> None:
    """Start filesystem watchers without storming the DB on boot.

    Startup used to force-reindex every bot workspace before starting
    watchers. On instances with shared workspaces and contextual retrieval,
    that fan-out can open enough concurrent DB write/backfill work to exhaust
    the SQLAlchemy pool before the first inbound chat request finishes.
    Watchers and explicit admin/maintenance reindex paths still handle actual
    changes; boot should not compete with chat for the whole pool.
    """
    from app.agent.bots import list_bots
    from app.agent.fs_watcher import start_watchers

    bots = list_bots()
    await start_watchers(bots)
    logger.info("Background: filesystem watchers started.")

    if settings.CONTEXTUAL_RETRIEVAL_ENABLED:
        try:
            from sqlalchemy import select as sa_select

            from app.agent.contextual_retrieval import warm_cache_from_metadata
            from app.db.engine import async_session
            from app.db.models import FilesystemChunk

            async with async_session() as db:
                cr_rows = (
                    await db.execute(
                        sa_select(
                            FilesystemChunk.content_hash,
                            FilesystemChunk.chunk_index,
                            FilesystemChunk.metadata_["contextual_description"].as_string(),
                        )
                        .where(
                            FilesystemChunk.metadata_["contextual_description"]
                            .as_string()
                            .is_not(None)
                        )
                        .limit(10_000)
                    )
                ).all()
            warmed = warm_cache_from_metadata(cr_rows)
            if warmed:
                logger.info(
                    "Warmed contextual retrieval cache from %d filesystem chunk(s)",
                    warmed,
                )
        except Exception:
            logger.debug("Contextual retrieval cache warm-up failed", exc_info=True)


async def legacy_integration_container_cleanup() -> None:
    """Remove pre-multi-instance integration containers squatting on old names."""
    from sqlalchemy import select

    from app.db.engine import async_session
    from app.db.models import ServerSetting

    async with async_session() as db:
        existing = (
            await db.execute(
                select(ServerSetting).where(
                    ServerSetting.key == _LEGACY_CLEANUP_SETTING_KEY
                )
            )
        ).scalar_one_or_none()
        if existing and existing.value == "1":
            return

    removed: list[str] = []
    for name in _LEGACY_INTEGRATION_CONTAINER_NAMES:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "inspect",
                "--format",
                '{{index .Config.Labels "com.docker.stack-id"}}|{{.State.Status}}',
                name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await proc.communicate()
            if proc.returncode != 0:
                continue
            label, _, _status = out.decode().strip().partition("|")
            if label:
                continue
            rm = await asyncio.create_subprocess_exec(
                "docker",
                "rm",
                "-f",
                name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _rm_out, rm_err = await rm.communicate()
            if rm.returncode == 0:
                removed.append(name)
            else:
                logger.warning(
                    "Legacy container cleanup: failed to rm %s: %s",
                    name,
                    rm_err.decode().strip(),
                )
        except Exception:
            logger.warning(
                "Legacy container cleanup: inspect failed for %s",
                name,
                exc_info=True,
            )

    async with async_session() as db:
        row = ServerSetting(key=_LEGACY_CLEANUP_SETTING_KEY, value="1")
        await db.merge(row)
        await db.commit()

    if removed:
        logger.warning(
            "Legacy integration cleanup: removed %d orphan container(s): %s. "
            "Integration stacks will be recreated under instance-scoped names.",
            len(removed),
            ", ".join(removed),
        )


async def background_warmup() -> None:
    """Run non-blocking post-ready indexing and integration stack reconciliation."""
    from app.agent.tools import (
        index_local_tools,
        validate_pinned_tools,
        warm_mcp_tool_index_for_all_bots,
    )

    t0 = time.monotonic()
    logger.info("Background warmup: starting...")

    logger.info("Background warmup: indexing local tools + MCP tools...")

    async def _index_tools() -> None:
        await index_local_tools()
        await warm_mcp_tool_index_for_all_bots()
        await validate_pinned_tools()

    await asyncio.gather(_index_tools(), return_exceptions=True)

    if settings.DOCKER_STACKS_ENABLED:
        try:
            from app.services.docker_stacks import stack_service

            fixed = await stack_service.reconcile_running()
            if fixed:
                logger.info("Reconciled %d docker stack(s) to stopped", fixed)
        except Exception:
            logger.exception("Failed to reconcile docker stacks")

        try:
            await legacy_integration_container_cleanup()
        except Exception:
            logger.exception("Legacy integration container cleanup failed")

    try:
        from app.services.docker_stacks import stack_service
        from app.services.integration_settings import get_value as get_int_setting
        from app.services.integration_settings import is_active as is_integration_active
        from app.services.integration_catalog import discover_docker_compose_stacks

        for dc_info in discover_docker_compose_stacks():
            int_id = dc_info["integration_id"]
            try:
                enabled = False
                if is_integration_active(int_id):
                    enabled_callable = dc_info.get("enabled_callable")
                    if enabled_callable is not None:
                        try:
                            enabled = bool(enabled_callable())
                        except Exception:
                            logger.exception("enabled_callable failed for %s", int_id)
                            enabled = False
                    elif dc_info["enabled_setting"]:
                        default = dc_info.get("enabled_default", "false")
                        val = get_int_setting(int_id, dc_info["enabled_setting"], default)
                        enabled = val.lower() in ("true", "1", "yes")
                await stack_service.apply_integration_stack(
                    integration_id=int_id,
                    name=dc_info["description"] or int_id,
                    compose_definition=dc_info["compose_definition"],
                    project_name=dc_info["project_name"],
                    enabled=enabled,
                    description=dc_info["description"],
                    config_files=dc_info["config_files"],
                )
            except Exception:
                logger.exception("Failed to sync integration stack: %s", int_id)
    except Exception:
        logger.exception("Failed to discover/sync integration docker stacks")

    elapsed = time.monotonic() - t0
    logger.info("Background warmup: complete in %.1fs", elapsed)


async def start_ready_runtime_services(handle: StartupRuntimeHandle) -> None:
    """Start workers that should launch once the server is ready."""
    from app.agent.fs_watcher import periodic_reindex_worker
    from app.agent.tasks import task_worker
    from app.services.attachment_retention import attachment_retention_worker
    from app.services.attachment_summarizer import attachment_sweep_worker
    from app.services.data_retention import data_retention_worker
    from app.services.heartbeat import heartbeat_worker
    from app.services.pin_contract import pin_contract_drift_worker
    from app.services.usage_spike import usage_spike_worker

    handle.schedule(task_worker(), name="task_worker")
    await recover_heartbeat_runs_before_worker()
    handle.schedule(heartbeat_worker(), name="heartbeat_worker")
    handle.schedule(usage_spike_worker(), name="usage_spike_worker")
    handle.schedule(periodic_reindex_worker(), name="periodic_reindex")
    handle.schedule(attachment_sweep_worker(), name="attachment_sweep")
    handle.schedule(attachment_retention_worker(), name="attachment_retention")
    handle.schedule(data_retention_worker(), name="data_retention")
    handle.schedule(pin_contract_drift_worker(), name="pin_contract_drift")
    if settings.CONFIG_STATE_FILE:
        from app.services.config_export import config_export_worker

        handle.schedule(config_export_worker(), name="config_export")

    handle.schedule(session_cleanup_worker(), name="session_cleanup")

    from app.services.integration_processes import process_manager

    handle.process_manager = process_manager
    handle.schedule(
        process_manager.start_auto_start_processes(),
        name="integration_processes",
    )

    start_renderer_dispatchers(handle)
    await recover_outbox_before_drainer()

    from app.services.outbox_drainer import outbox_drainer_worker
    from app.services.workspace_attention import structured_attention_worker
    from app.services.unread import unread_reminder_worker

    handle.schedule(outbox_drainer_worker(), name="outbox_drainer")
    handle.schedule(structured_attention_worker(), name="workspace_attention")
    handle.schedule(unread_reminder_worker(), name="unread_reminders")

    await register_widget_events_on_startup()


async def session_cleanup_worker() -> None:
    """Periodically evict stale session allows and leaked session locks."""
    while True:
        try:
            await asyncio.sleep(600)
            from app.agent.session_allows import cleanup_stale as allow_cleanup
            from app.db.engine import async_session
            from app.services.project_instances import cleanup_expired_task_project_instances
            from app.services.session_locks import sweep_stale as lock_sweep

            allow_removed = allow_cleanup()
            lock_removed = lock_sweep()
            async with async_session() as db:
                project_instance_cleanup = await cleanup_expired_task_project_instances(db)
            cleaned_instances = int(project_instance_cleanup.get("cleaned") or 0)
            if allow_removed or lock_removed or cleaned_instances:
                logger.debug(
                    "Session cleanup: %d allow + %d session-lock entries evicted, %d expired Project instances cleaned",
                    allow_removed,
                    lock_removed,
                    cleaned_instances,
                )
        except Exception:
            logger.warning("Session cleanup failed", exc_info=True)


def start_renderer_dispatchers(handle: StartupRuntimeHandle) -> None:
    """Start one IntegrationDispatcherTask per registered ChannelRenderer."""
    import app.integrations.core_renderers  # noqa: F401  registers core renderers
    from app.integrations.renderer_registry import all_renderers
    from app.services.channel_renderers import IntegrationDispatcherTask
    from app.services.dispatch_resolution import resolve_target_for_renderer

    for renderer in all_renderers().values():
        async def resolve(channel_id, r=renderer):
            return await resolve_target_for_renderer(channel_id, r.integration_id)

        dispatcher = IntegrationDispatcherTask(renderer, resolve)
        dispatcher.start()
        handle.renderer_dispatchers.append(dispatcher)
        logger.info(
            "Started IntegrationDispatcherTask for renderer %r",
            renderer.integration_id,
        )


async def recover_outbox_before_drainer() -> None:
    """Reset stale outbox rows before the drainer starts."""
    from app.db.engine import async_session
    from app.services.outbox import reset_stale_in_flight

    try:
        async with async_session() as db:
            recovered = await reset_stale_in_flight(db)
        if recovered:
            logger.info(
                "outbox: recovered %d stale IN_FLIGHT row(s) from previous run",
                recovered,
            )
    except Exception:
        logger.exception("outbox: stale IN_FLIGHT recovery failed (drainer will continue)")


async def recover_heartbeat_runs_before_worker() -> None:
    """Reset stale heartbeat runs before the heartbeat worker handles new runs."""
    from app.db.engine import async_session
    from app.services.heartbeat import reset_stale_running_runs

    try:
        async with async_session() as db:
            recovered = await reset_stale_running_runs(db)
        if recovered:
            logger.info(
                "heartbeat: recovered %d stale running run(s) from previous process",
                recovered,
            )
    except Exception:
        logger.exception("heartbeat: stale running-run recovery failed (worker will continue)")


async def register_widget_events_on_startup() -> None:
    """Restore widget.py event subscribers without blocking server startup."""
    try:
        from app.services.widget_events import register_all_pins_on_startup

        await register_all_pins_on_startup()
    except Exception:
        logger.exception("widget_events: startup registration failed")


async def shutdown_runtime_services(handle: StartupRuntimeHandle) -> None:
    """Stop runtime workers and close shared renderer/process resources."""
    try:
        from app.services.widget_events import unregister_all_on_shutdown

        await unregister_all_on_shutdown()
    except Exception:
        logger.exception("widget_events: shutdown cancellation failed")

    from app.services.channel_events import signal_shutdown
    from app.services.user_events import signal_shutdown as signal_user_events_shutdown

    signal_shutdown()
    signal_user_events_shutdown()

    for dispatcher in handle.renderer_dispatchers:
        await dispatcher.stop()

    await close_renderer_http_clients()

    for worker in handle.workers:
        worker.cancel()
    await asyncio.gather(*handle.workers, return_exceptions=True)

    if handle.process_manager is not None:
        await handle.process_manager.shutdown_all()


async def close_renderer_http_clients() -> None:
    """Close module-level renderer HTTP clients exposed as ``_http``."""
    from app.integrations.renderer_registry import all_renderers

    renderer_modules: set[str] = {
        type(renderer).__module__ for renderer in all_renderers().values()
    }
    renderer_modules.add("app.integrations.core_renderers")
    for mod_name in renderer_modules:
        try:
            mod = importlib.import_module(mod_name)
            client = getattr(mod, "_http", None)
            if client is not None and hasattr(client, "aclose"):
                await client.aclose()
        except Exception:
            logger.debug(
                "Failed to close httpx client in %s during shutdown",
                mod_name,
                exc_info=True,
            )
