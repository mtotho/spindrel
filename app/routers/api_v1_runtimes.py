"""Public read of harness runtime capabilities.

Each registered ``HarnessRuntime`` (claude-code, future codex, ...) exposes
a ``RuntimeCapabilities`` dataclass that the UI consumes to render the
harness control surface (model + effort pills, slash-command filter,
approval modes). Capabilities are static per process; the UI caches with a
generous staleTime.

Authenticated with ``verify_auth_or_user`` — capabilities themselves are
non-sensitive but the endpoint joins the rest of the authed API surface
rather than being publicly readable.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import verify_auth_or_user
from app.services.agent_harnesses import HARNESS_REGISTRY

router = APIRouter(prefix="/runtimes", tags=["Runtimes"])


class HarnessSlashCommandPolicyOut(BaseModel):
    allowed_command_ids: list[str]


class RuntimeCapabilitiesOut(BaseModel):
    name: str
    display_name: str
    supported_models: list[str]
    # Live list from runtime.list_models(). Distinct from supported_models
    # (curated UI hint) — this is the authoritative set the picker shows.
    available_models: list[str]
    model_is_freeform: bool
    effort_values: list[str]
    approval_modes: list[str]
    slash_policy: HarnessSlashCommandPolicyOut


@router.get("/{name}/capabilities", response_model=RuntimeCapabilitiesOut)
async def get_runtime_capabilities(
    name: str,
    _auth=Depends(verify_auth_or_user),
):
    runtime = HARNESS_REGISTRY.get(name)
    if runtime is None:
        raise HTTPException(status_code=404, detail=f"unknown runtime: {name!r}")
    if not hasattr(runtime, "capabilities"):
        # Defensive — older runtimes loaded from a stale wheel might not yet
        # implement the Phase 4 capabilities() method.
        raise HTTPException(
            status_code=501,
            detail=f"runtime {name!r} does not expose capabilities",
        )
    caps = runtime.capabilities()
    available_models: list[str] = []
    if hasattr(runtime, "list_models"):
        try:
            available_models = list(await runtime.list_models())
        except Exception:
            # Don't 500 the endpoint if a runtime adapter's list_models
            # raises (e.g. SDK call fails). Fall back to the curated
            # supported_models hint and let the UI render that.
            available_models = list(caps.supported_models)
    return RuntimeCapabilitiesOut(
        name=name,
        display_name=caps.display_name,
        supported_models=list(caps.supported_models),
        available_models=available_models,
        model_is_freeform=caps.model_is_freeform,
        effort_values=list(caps.effort_values),
        approval_modes=list(caps.approval_modes),
        slash_policy=HarnessSlashCommandPolicyOut(
            allowed_command_ids=sorted(caps.slash_policy.allowed_command_ids),
        ),
    )
