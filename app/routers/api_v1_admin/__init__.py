"""Admin JSON API — /api/v1/admin/

Provides admin endpoints that mirror the Jinja2/HTMX admin
dashboard, returning structured JSON for the Expo client.
"""
from fastapi import APIRouter, Depends

from app.dependencies import verify_admin_auth

from . import api_keys, attachments, bots, carapaces, channels, config_state, diagnostics, docker_stacks, docs, fallbacks, health, integrations, limits, logs, mcp_servers, memories, models, operations, prompts, providers, secret_values, settings, skills, spike_alerts, stats, storage, tasks, tools, turns, upcoming, usage, webhooks, workflows

router = APIRouter(prefix="/admin", tags=["Admin API"], dependencies=[Depends(verify_admin_auth)])

router.include_router(api_keys.router)
router.include_router(attachments.router)
router.include_router(stats.router)
router.include_router(bots.router)
router.include_router(carapaces.router)
router.include_router(channels.router)
router.include_router(tasks.router)
router.include_router(skills.router)
router.include_router(providers.router)
router.include_router(models.router)
router.include_router(memories.router)
router.include_router(mcp_servers.router)
router.include_router(tools.router)
router.include_router(prompts.router)
router.include_router(settings.router)
router.include_router(usage.router)
router.include_router(limits.router)
router.include_router(config_state.router)
router.include_router(diagnostics.router)
router.include_router(integrations.router)
router.include_router(fallbacks.router)
router.include_router(logs.router)
router.include_router(turns.router)
router.include_router(upcoming.router)
router.include_router(health.router)
router.include_router(operations.router)
router.include_router(secret_values.router)
router.include_router(workflows.router)
router.include_router(spike_alerts.router)
router.include_router(storage.router)
router.include_router(webhooks.router)
router.include_router(docker_stacks.router)
router.include_router(docs.router)
