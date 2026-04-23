"""Internal tool-execution endpoint for programmatic tool calling.

Used by ``run_script`` (and any other workspace-side caller) to invoke tools
from a Python script running inside the bot's shared workspace. The script
authenticates with the per-bot scoped API key already injected as
``AGENT_SERVER_API_KEY`` (see ``app/services/shared_workspace.py:233``) — same
key issued by the ``workspace_bot`` preset and used by MC's container.

Routes through the same policy + tier gate as a regular LLM-driven tool call,
re-establishing the ContextVars that tools depend on (``current_bot_id`` etc.).
The bot's own preset/grant scopes are the ceiling — no admin elevation, no
static-key fallback.
"""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import ApiKeyAuth, get_db, verify_auth_or_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/tools", tags=["internal-tools"])


class ToolExecRequest(BaseModel):
    name: str = Field(..., description="Tool name as registered.")
    arguments: dict = Field(default_factory=dict, description="Argument dict — passed as JSON to call_local_tool.")
    parent_correlation_id: str | None = Field(
        default=None,
        description="Correlation id of the parent script call (for trace stitching).",
    )
    channel_id: str | None = Field(
        default=None,
        description=(
            "Optional channel id to set on ContextVars for tools that require channel context. "
            "Must be a channel the calling bot can already see; not enforced here — downstream "
            "tools fail closed if they can't resolve it."
        ),
    )


class ToolExecResponse(BaseModel):
    name: str
    ok: bool
    result: dict | list | str | int | float | bool | None
    error: str | None = None


async def _resolve_calling_bot(db: AsyncSession, auth: ApiKeyAuth) -> str:
    """Resolve the bot that owns the calling API key. Raises 403 if none."""
    from app.db.models import Bot
    if not isinstance(auth, ApiKeyAuth):
        raise HTTPException(status_code=403, detail="Internal tools/exec requires a bot API key, not a JWT.")
    if str(auth.key_id) == "00000000-0000-0000-0000-000000000000":
        raise HTTPException(status_code=403, detail="Internal tools/exec rejects the static admin key — call through the per-bot key.")

    row = (await db.execute(
        select(Bot.id).where(Bot.api_key_id == auth.key_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=403, detail="API key is not bound to a bot.")
    return str(row)


@router.post("/exec", response_model=ToolExecResponse)
async def exec_tool(
    payload: ToolExecRequest,
    auth: ApiKeyAuth = Depends(verify_auth_or_user),
    db: AsyncSession = Depends(get_db),
):
    """Dispatch a single tool call from a workspace-side script.

    Behavior:
    - 403 if the API key isn't bound to a bot or the policy denies the call.
    - 409 ``{detail: "approval_required", ...}`` if the policy gate requires approval.
      Scripts should ``try/except`` this and decide whether to skip or surface.
    - 200 with ``{name, ok, result, error}`` on success — ``result`` is the parsed
      JSON of the tool's return value (or the raw string if it isn't JSON).
    """
    # --- Budget check --- caps how many inner tool calls a single
    # run_script invocation may dispatch. Budget is opened by run_script
    # keyed on the parent correlation id; untracked calls (no budget
    # entry for this id) are allowed through. Checked early so the
    # reject path doesn't pay for bot-resolution / registry lookups.
    from app.services.script_budget import spend as _spend_budget
    allowed, _remaining, _limit = await _spend_budget(payload.parent_correlation_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "script_tool_budget_exhausted",
                "limit": _limit,
                "hint": (
                    f"This run_script invocation already made {_limit} inner tool calls. "
                    "Cap prevents cost-amplification from a looping script. "
                    "Split the work across multiple run_script calls or raise "
                    "bot.max_script_tool_calls."
                ),
            },
        )

    bot_id = await _resolve_calling_bot(db, auth)

    from app.tools.registry import is_local_tool, get_tool_execution_policy, get_tool_safety_tier
    from app.tools.mcp import is_mcp_tool

    is_local = is_local_tool(payload.name)
    is_mcp = (not is_local) and is_mcp_tool(payload.name)
    if not (is_local or is_mcp):
        # Try MCP namespace resolution (LiteLLM gateway prefixes "<server>-<tool>"
        # but small models drop the prefix — same forgiving lookup get_tool_info uses).
        try:
            from app.tools.mcp import resolve_mcp_tool_name
            resolved = resolve_mcp_tool_name(payload.name)
        except Exception:
            resolved = None
        if resolved and resolved != payload.name:
            payload.name = resolved
            is_mcp = True
        else:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Tool {payload.name!r} is not a registered local tool or MCP tool. "
                    "Client tools (browser-side) are not exposed via this endpoint."
                ),
            )

    if is_local:
        execution_policy = get_tool_execution_policy(payload.name)
        if execution_policy != "normal":
            from app.services.machine_control import validate_current_execution_policy

            resolution = await validate_current_execution_policy(execution_policy)
            if not resolution.allowed:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "local_control_required",
                        "message": resolution.reason or "Machine-control tools are not available from this surface.",
                    },
                )

    # --- Policy check --- same gate the LLM-driven dispatch uses.
    from app.agent.tool_dispatch import _check_tool_policy
    correlation_id = payload.parent_correlation_id or str(uuid.uuid4())
    try:
        decision = await _check_tool_policy(
            bot_id, payload.name, payload.arguments,
            correlation_id=correlation_id,
        )
    except Exception:
        logger.exception("Policy check failed for %s/%s", bot_id, payload.name)
        raise HTTPException(status_code=500, detail="Policy evaluation error.")

    if decision is not None:
        if decision.action == "deny":
            raise HTTPException(
                status_code=403,
                detail=f"Denied by policy: {decision.reason or '(no reason)'}",
            )
        if decision.action == "require_approval":
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "approval_required",
                    "tier": decision.tier,
                    "reason": decision.reason,
                    "hint": (
                        "This tool requires user approval. A script-driven call cannot "
                        "wait inline — surface this back to the user, or call a different "
                        "tool that doesn't require approval."
                    ),
                },
            )

    # --- Set ContextVars so tools that read current_bot_id / current_channel_id work.
    from app.agent.context import (
        current_bot_id,
        current_channel_id,
        current_correlation_id,
    )
    resets: list[tuple] = []
    resets.append((current_bot_id, current_bot_id.set(bot_id)))
    if payload.channel_id:
        try:
            ch_uuid = uuid.UUID(payload.channel_id)
            resets.append((current_channel_id, current_channel_id.set(ch_uuid)))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"channel_id is not a valid UUID: {payload.channel_id}")
    try:
        cor_uuid = uuid.UUID(correlation_id)
        resets.append((current_correlation_id, current_correlation_id.set(cor_uuid)))
    except ValueError:
        pass  # parent_correlation_id was a non-UUID string; tools tolerate None

    try:
        if is_local:
            from app.tools.registry import call_local_tool
            result_str = await call_local_tool(payload.name, json.dumps(payload.arguments))
        else:
            from app.tools.mcp import call_mcp_tool
            result_str = await call_mcp_tool(payload.name, json.dumps(payload.arguments))
    finally:
        # Reset ContextVars in reverse order.
        for var, tok in reversed(resets):
            try:
                var.reset(tok)
            except Exception:
                pass

    # Try to parse as JSON for ergonomic Python-side access; fall back to string.
    try:
        parsed = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        parsed = result_str

    # Tools encode errors as ``{"error": "..."}``; surface ok=False but still 200
    # so the script's helper can ``try/except``-style branch on the response.
    err = None
    if isinstance(parsed, dict) and isinstance(parsed.get("error"), str):
        err = parsed["error"]

    tier = get_tool_safety_tier(payload.name)
    logger.info("internal/tools/exec: bot=%s tool=%s tier=%s ok=%s", bot_id, payload.name, tier, err is None)

    return ToolExecResponse(name=payload.name, ok=err is None, result=parsed, error=err)
