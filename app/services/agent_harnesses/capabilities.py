"""Helpers for projecting runtime capability details consistently."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.agent_harnesses.base import HarnessModelOption, RuntimeCapabilities


@dataclass(frozen=True)
class RuntimeModelSurface:
    """Runtime model metadata prepared for API and slash-picker surfaces."""

    caps: RuntimeCapabilities
    available_models: tuple[str, ...]
    model_options: tuple[HarnessModelOption, ...]
    effort_values: tuple[str, ...]
    default_model: str | None = None
    default_effort: str | None = None


def _ordered_unique(values) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return tuple(out)


async def resolve_runtime_model_surface(runtime: Any) -> RuntimeModelSurface:
    """Return the live model/effort projection for a harness runtime.

    The runtime capability object is static and can include broad fallback
    values. If the adapter exposes live ``list_model_options()``, those options
    are the authoritative picker surface and the compatibility ``effort_values``
    projection should be derived from them.
    """

    caps = runtime.capabilities()
    available_models: tuple[str, ...] = ()
    live_model_options: tuple[HarnessModelOption, ...] = ()
    if hasattr(runtime, "list_model_options"):
        try:
            live_model_options = tuple(await runtime.list_model_options())
            available_models = tuple(opt.id for opt in live_model_options)
        except Exception:
            live_model_options = ()
    if hasattr(runtime, "list_models") and not available_models:
        try:
            available_models = tuple(await runtime.list_models())
        except Exception:
            available_models = tuple(caps.supported_models)

    source_model_options = live_model_options or tuple(getattr(caps, "model_options", ()) or ())
    if not source_model_options:
        source_model_options = tuple(
            HarnessModelOption(
                id=model,
                label=None,
                effort_values=tuple(caps.effort_values),
                default_effort=None,
            )
            for model in (available_models or tuple(caps.supported_models))
        )

    live_efforts = _ordered_unique(
        effort
        for option in source_model_options
        for effort in tuple(option.effort_values or ())
    )
    return RuntimeModelSurface(
        caps=caps,
        available_models=available_models,
        model_options=source_model_options,
        effort_values=live_efforts or tuple(caps.effort_values),
        default_model=source_model_options[0].id if source_model_options else None,
        default_effort=source_model_options[0].default_effort if source_model_options else None,
    )


async def resolve_runtime_effective_defaults(runtime: Any) -> tuple[str | None, str | None]:
    """Return the runtime's configured default model/effort when available."""

    if hasattr(runtime, "default_model_settings"):
        try:
            defaults = await runtime.default_model_settings()
            if isinstance(defaults, tuple) and len(defaults) >= 2:
                model = defaults[0] if isinstance(defaults[0], str) and defaults[0].strip() else None
                effort = defaults[1] if isinstance(defaults[1], str) and defaults[1].strip() else None
                if model or effort:
                    return model, effort
        except Exception:
            pass
    surface = await resolve_runtime_model_surface(runtime)
    return surface.default_model, surface.default_effort
