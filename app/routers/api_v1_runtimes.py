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
from pydantic import BaseModel, Field

from app.dependencies import verify_auth_or_user
from app.services.agent_harnesses import HARNESS_REGISTRY
from app.services.agent_harnesses.capabilities import resolve_runtime_model_surface

router = APIRouter(prefix="/runtimes", tags=["Runtimes"])


class HarnessSlashCommandPolicyOut(BaseModel):
    allowed_command_ids: list[str]


class HarnessModelOptionOut(BaseModel):
    id: str
    label: str | None = None
    effort_values: list[str]
    default_effort: str | None = None


class HarnessRuntimeCommandOut(BaseModel):
    id: str
    label: str
    description: str
    readonly: bool = True
    mutability: str = "readonly"
    aliases: list[str] = Field(default_factory=list)
    interaction_kind: str = "structured"
    fallback_behavior: str = "none"


class RuntimeCapabilitiesOut(BaseModel):
    name: str
    display_name: str
    supported_models: list[str]
    model_options: list[HarnessModelOptionOut]
    # Live list from runtime.list_models(). Distinct from supported_models
    # (curated UI hint) — this is the authoritative set the picker shows.
    available_models: list[str]
    default_model: str | None = None
    default_effort: str | None = None
    model_is_freeform: bool
    effort_values: list[str]
    approval_modes: list[str]
    slash_policy: HarnessSlashCommandPolicyOut
    native_compaction: bool = False
    context_window_tokens: int | None = None
    native_commands: list[HarnessRuntimeCommandOut] = Field(default_factory=list)


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
    surface = await resolve_runtime_model_surface(runtime)
    caps = surface.caps
    model_options = [
        HarnessModelOptionOut(
            id=opt.id,
            label=opt.label,
            effort_values=list(opt.effort_values),
            default_effort=opt.default_effort,
        )
        for opt in surface.model_options
    ]
    return RuntimeCapabilitiesOut(
        name=name,
        display_name=caps.display_name,
        supported_models=list(caps.supported_models),
        model_options=model_options,
        available_models=list(surface.available_models),
        default_model=surface.default_model,
        default_effort=surface.default_effort,
        model_is_freeform=caps.model_is_freeform,
        effort_values=list(surface.effort_values),
        approval_modes=list(caps.approval_modes),
        slash_policy=HarnessSlashCommandPolicyOut(
            allowed_command_ids=sorted(caps.slash_policy.allowed_command_ids),
        ),
        native_compaction=bool(getattr(caps, "native_compaction", False)),
        context_window_tokens=getattr(caps, "context_window_tokens", None),
        native_commands=[
            HarnessRuntimeCommandOut(
                id=cmd.id,
                label=cmd.label,
                description=cmd.description,
                readonly=cmd.readonly,
                mutability=getattr(cmd, "mutability", "readonly"),
                aliases=list(getattr(cmd, "aliases", ()) or ()),
                interaction_kind=getattr(cmd, "interaction_kind", "structured"),
                fallback_behavior=getattr(cmd, "fallback_behavior", "none"),
            )
            for cmd in getattr(caps, "native_commands", ())
        ],
    )
