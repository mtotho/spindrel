"""Optional base class for integrations."""
from __future__ import annotations

from fastapi import APIRouter


class IntegrationBase:
    """Base class integrations may extend. All fields are optional."""

    id: str = ""
    name: str = ""
    version: str = "0.1.0"

    async def on_startup(self) -> None:
        """Called after the integration router is registered. Override to run startup logic."""
