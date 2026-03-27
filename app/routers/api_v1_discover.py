"""Discovery endpoint — GET /api/v1/discover."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.dependencies import ApiKeyAuth, verify_auth_or_user
from app.services.api_keys import ENDPOINT_CATALOG, has_scope

router = APIRouter(tags=["Discovery"])


class EndpointInfo(BaseModel):
    method: str
    path: str
    description: str
    scope: str | None = None


class DiscoverResponse(BaseModel):
    name: str | None = None
    scopes: list[str] | None = None
    endpoints: list[EndpointInfo]


@router.get("/discover", response_model=DiscoverResponse)
async def discover(
    auth=Depends(verify_auth_or_user),
):
    """Return available endpoints for the current key/user."""
    if isinstance(auth, ApiKeyAuth):
        # Scoped key: filter by scopes
        endpoints = []
        for ep in ENDPOINT_CATALOG:
            scope = ep.get("scope")
            if scope is None or has_scope(auth.scopes, scope):
                endpoints.append(EndpointInfo(
                    method=ep["method"],
                    path=ep["path"],
                    description=ep["description"],
                    scope=scope,
                ))
        return DiscoverResponse(
            name=auth.name,
            scopes=auth.scopes,
            endpoints=endpoints,
        )

    # Static API key or JWT user: return all endpoints
    return DiscoverResponse(
        endpoints=[
            EndpointInfo(
                method=ep["method"],
                path=ep["path"],
                description=ep["description"],
                scope=ep.get("scope"),
            )
            for ep in ENDPOINT_CATALOG
        ],
    )
