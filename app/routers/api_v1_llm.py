"""LLM proxy endpoint — /api/v1/llm/completions

Thin proxy that lets integrations make LLM calls through the server's
multi-provider infrastructure without needing to know about provider URLs,
API keys, or routing.  Usage is recorded as a TraceEvent so it appears in
cost tracking, usage logs, and spike detection.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.dependencies import ApiKeyAuth, require_scopes
from app.utils import safe_create_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm", tags=["LLM"])


class CompletionRequest(BaseModel):
    model: str | None = Field(None, description="Model ID. Defaults to server's DEFAULT_MODEL.")
    messages: list[dict[str, Any]] = Field(..., min_length=1, description="OpenAI-format messages.")
    temperature: float | None = Field(None, ge=0, le=2)
    max_tokens: int | None = Field(None, gt=0)
    extra: dict[str, Any] | None = Field(None, description="Extra provider-specific params (e.g. safety_settings for Gemini).")


class CompletionResponse(BaseModel):
    content: str
    model: str
    usage: dict[str, int] | None = None


@router.post(
    "/completions",
    response_model=CompletionResponse,
    summary="LLM chat completion",
    description="Make a chat completion call through the server's provider system.",
)
async def llm_completions(
    body: CompletionRequest,
    auth=Depends(require_scopes("llm:completions")),
):
    from app.services.providers import get_llm_client, resolve_provider_for_model

    model = body.model or settings.DEFAULT_MODEL
    if not model:
        raise HTTPException(status_code=400, detail="No model specified and no DEFAULT_MODEL configured.")

    provider_id = resolve_provider_for_model(model)
    client = get_llm_client(provider_id)

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": body.messages,
    }
    if body.temperature is not None:
        kwargs["temperature"] = body.temperature
    if body.max_tokens is not None:
        kwargs["max_tokens"] = body.max_tokens
    if body.extra:
        kwargs.update(body.extra)

    correlation_id = uuid.uuid4()

    # Identify caller from auth for logging
    caller = "unknown"
    if isinstance(auth, ApiKeyAuth):
        caller = auth.name or f"key:{auth.key_id}"
    elif hasattr(auth, "username"):
        caller = auth.username

    logger.info(
        "LLM completions: model=%s provider=%s caller=%s cid=%s",
        model, provider_id or "default", caller, correlation_id,
    )

    t0 = time.monotonic()
    try:
        resp = await client.chat.completions.create(**kwargs)
    except Exception as exc:
        logger.warning(
            "LLM completions failed: model=%s caller=%s cid=%s error=%s",
            model, caller, correlation_id, exc,
        )
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}") from exc
    duration_ms = int((time.monotonic() - t0) * 1000)

    choice = resp.choices[0] if resp.choices else None
    content = choice.message.content if choice and choice.message else ""
    finish_reason = getattr(choice, "finish_reason", None) if choice else None

    if not content:
        logger.warning(
            "LLM completions empty content: model=%s finish_reason=%s choices=%d cid=%s",
            model, finish_reason, len(resp.choices) if resp.choices else 0, correlation_id,
        )

    usage = None
    usage_data: dict[str, Any] = {
        "model": resp.model or model,
        "provider_id": provider_id,
        "source": "llm_completions_api",
        "caller": caller,
    }
    if resp.usage:
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens or 0,
            "completion_tokens": resp.usage.completion_tokens or 0,
            "total_tokens": resp.usage.total_tokens or 0,
        }
        usage_data.update(usage)
        # Extract response_cost if provider (e.g. LiteLLM) attached it
        try:
            hidden = getattr(resp, "_hidden_params", None) or {}
            if not hidden and hasattr(resp, "model_extra"):
                hidden = (resp.model_extra or {}).get("_hidden_params", {})
            if hidden.get("response_cost") is not None:
                usage_data["response_cost"] = hidden["response_cost"]
        except Exception:
            pass

    logger.info(
        "LLM completions done: model=%s tokens=%s duration=%dms cid=%s",
        usage_data["model"],
        usage_data.get("total_tokens", "n/a"),
        duration_ms,
        correlation_id,
    )

    # Record usage as TraceEvent (fire-and-forget)
    from app.agent.recording import _record_trace_event
    safe_create_task(_record_trace_event(
        correlation_id=correlation_id,
        session_id=None,
        bot_id=None,
        client_id=caller,
        event_type="token_usage",
        event_name="llm_completions_api",
        data=usage_data,
        duration_ms=duration_ms,
    ))

    # Record TPM usage for rate limiting
    if usage and provider_id:
        from app.services.providers import record_usage
        record_usage(provider_id, usage["total_tokens"])

    return CompletionResponse(
        content=content or "",
        model=resp.model or model,
        usage=usage,
    )
