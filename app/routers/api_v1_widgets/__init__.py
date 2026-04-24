"""Widget / dashboard API — ``/api/v1/widgets/...``

Per-theme split of the former monolithic ``api_v1_dashboard.py`` router,
mirroring the ``api_v1_admin/`` package layout. Sub-routers:

- ``dashboards`` — named-board CRUD + rails + redirect + channel-pins list
- ``pins`` — pin CRUD, layout, panel promotion, refresh
- ``library`` — read-only widget catalog, library, manifests, content serving
- ``presets`` — preset templates, suites, previews, recent-call render
"""
from __future__ import annotations

from fastapi import APIRouter

from . import dashboards, library, pins, presets


router = APIRouter(prefix="/widgets", tags=["widget-dashboard"])
router.include_router(dashboards.router)
router.include_router(pins.router)
router.include_router(library.router)
router.include_router(presets.router)
