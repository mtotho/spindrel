"""Admin JSON API — /api/v1/admin/

Provides admin endpoints that mirror the Jinja2/HTMX admin
dashboard, returning structured JSON for the Expo client.
"""
from fastapi import APIRouter, Depends

from app.dependencies import verify_admin_auth

from . import api_keys, bots, channels, config_state, diagnostics, elevation, fallbacks, integrations, limits, logs, memories, models, prompts, providers, settings, skills, stats, tasks, tools, turns, upcoming, usage

router = APIRouter(prefix="/admin", tags=["Admin API"], dependencies=[Depends(verify_admin_auth)])

router.include_router(api_keys.router)
router.include_router(stats.router)
router.include_router(bots.router)
router.include_router(channels.router)
router.include_router(tasks.router)
router.include_router(skills.router)
router.include_router(providers.router)
router.include_router(models.router)
router.include_router(memories.router)
router.include_router(elevation.router)
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
