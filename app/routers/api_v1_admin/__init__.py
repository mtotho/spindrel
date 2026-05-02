"""Admin JSON API — /api/v1/admin/

Provides admin endpoints that mirror the Jinja2/HTMX admin
dashboard, returning structured JSON for the Expo client.
"""
from fastapi import APIRouter, Depends

from app.dependencies import verify_admin_auth

from . import api_keys, attachments, bot_grants, bots, channel_pipelines, channels, config_state, diagnostics, docker_stacks, docs, fallbacks, harnesses, health, install_cache, integrations, learning, limits, logs, machines, mcp_servers, models, notification_targets, openai_oauth, operations, prompts, providers, run_presets, secret_values, security_audit, settings, skills, spike_alerts, stats, storage, tasks, tools, turns, upcoming, usage, webhooks, widget_packages, widget_themes, widget_tokens, workflows

router = APIRouter(prefix="/admin", tags=["Admin API"], dependencies=[Depends(verify_admin_auth)])

router.include_router(api_keys.router)
router.include_router(attachments.router)
router.include_router(stats.router)
router.include_router(bots.router)
router.include_router(bot_grants.router)
router.include_router(channels.router)
router.include_router(channel_pipelines.router)
router.include_router(tasks.router)
router.include_router(run_presets.router)
router.include_router(skills.router)
router.include_router(providers.router)
router.include_router(openai_oauth.router)
router.include_router(models.router)
router.include_router(mcp_servers.router)
router.include_router(tools.router)
router.include_router(widget_packages.router)
router.include_router(widget_themes.router)
router.include_router(widget_tokens.router)
router.include_router(prompts.router)
router.include_router(settings.router)
router.include_router(usage.router)
router.include_router(limits.router)
router.include_router(config_state.router)
router.include_router(diagnostics.router)
router.include_router(integrations.router)
router.include_router(machines.router)
router.include_router(learning.router)
router.include_router(fallbacks.router)
router.include_router(logs.router)
router.include_router(turns.router)
router.include_router(upcoming.router)
router.include_router(health.router)
router.include_router(operations.router)
router.include_router(secret_values.router)
router.include_router(workflows.router)
router.include_router(notification_targets.router)
router.include_router(spike_alerts.router)
router.include_router(storage.router)
router.include_router(webhooks.router)
router.include_router(docker_stacks.router)
router.include_router(security_audit.router)
router.include_router(install_cache.router)
router.include_router(docs.router)
router.include_router(harnesses.router)
