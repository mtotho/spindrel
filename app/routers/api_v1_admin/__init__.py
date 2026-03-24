"""Admin JSON API — /api/v1/admin/

Provides admin endpoints that mirror the Jinja2/HTMX admin
dashboard, returning structured JSON for the Expo client.
"""
from fastapi import APIRouter

from . import bots, channels, logs, memories, models, providers, skills, stats, tasks

router = APIRouter(prefix="/admin", tags=["Admin API"])

router.include_router(stats.router)
router.include_router(bots.router)
router.include_router(channels.router)
router.include_router(tasks.router)
router.include_router(skills.router)
router.include_router(providers.router)
router.include_router(logs.router)
router.include_router(models.router)
router.include_router(memories.router)
