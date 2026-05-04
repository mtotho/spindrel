"""Model and effort selection for Project coding runs.

The Project layer owns durable run intent; task execution still consumes the
existing ``execution_config`` keys.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot as BotRow
from app.db.models import Channel
from app.services.agent_harnesses import HARNESS_REGISTRY
from app.services.agent_harnesses.capabilities import resolve_runtime_model_surface
from app.services.agent_harnesses.settings import MODEL_ID_MAX_LEN
from app.services.providers import resolve_provider_for_model
from app.services.run_presets import get_run_preset

PROJECT_RUN_MODEL_SELECTION_KEY = "model_selection"


@dataclass(frozen=True)
class ProjectRunModelSelection:
    model_override: str | None = None
    model_provider_id_override: str | None = None
    harness_effort: str | None = None

    def to_persisted(self) -> dict[str, str]:
        payload: dict[str, str] = {}
        if self.model_override:
            payload["model_override"] = self.model_override
        if self.model_provider_id_override:
            payload["model_provider_id_override"] = self.model_provider_id_override
        if self.harness_effort:
            payload["harness_effort"] = self.harness_effort
        return payload

    def to_execution_config(self) -> dict[str, str]:
        return self.to_persisted()

    @property
    def has_explicit_values(self) -> bool:
        return bool(self.model_override or self.model_provider_id_override or self.harness_effort)


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def project_run_model_selection_from_config(config: Any) -> ProjectRunModelSelection:
    raw = config if isinstance(config, dict) else {}
    return ProjectRunModelSelection(
        model_override=_clean_optional(raw.get("model_override")),
        model_provider_id_override=_clean_optional(raw.get("model_provider_id_override")),
        harness_effort=_clean_optional(raw.get("harness_effort")),
    )


def apply_project_run_model_selection(
    execution_config: dict[str, Any],
    selection: ProjectRunModelSelection,
) -> None:
    for key, value in selection.to_execution_config().items():
        execution_config[key] = value
    run_cfg = execution_config.get("project_coding_run")
    if isinstance(run_cfg, dict):
        run_cfg[PROJECT_RUN_MODEL_SELECTION_KEY] = selection.to_persisted()


def _validate_model_id(model: str | None) -> None:
    if model is not None and len(model) > MODEL_ID_MAX_LEN:
        raise ValueError(f"model id exceeds {MODEL_ID_MAX_LEN}-character limit")


async def normalize_project_run_model_selection(
    db: AsyncSession,
    channel: Channel,
    *,
    model_override: str | None = None,
    model_provider_id_override: str | None = None,
    harness_effort: str | None = None,
) -> ProjectRunModelSelection:
    model = _clean_optional(model_override)
    provider = _clean_optional(model_provider_id_override)
    effort = _clean_optional(harness_effort)
    _validate_model_id(model)
    if provider and not model:
        raise ValueError("model_provider_id_override requires model_override")

    bot = await db.get(BotRow, channel.bot_id) if channel.bot_id else None
    harness_runtime = bot.harness_runtime if bot is not None else None
    if harness_runtime:
        if provider:
            raise ValueError("model_provider_id_override is not used for harness Project runs")
        runtime = HARNESS_REGISTRY.get(harness_runtime)
        if runtime is None and (model or effort):
            raise ValueError(f"harness runtime {harness_runtime!r} is not registered")
        if runtime is not None:
            surface = await resolve_runtime_model_surface(runtime)
            if model and not surface.caps.model_is_freeform:
                accepted_models = {option.id for option in surface.model_options} | set(surface.available_models)
                if model not in accepted_models:
                    raise ValueError(
                        f"Unknown model {model!r}. {surface.caps.display_name} accepts: "
                        f"{', '.join(sorted(accepted_models))}"
                    )
            if effort:
                by_model = {option.id: tuple(option.effort_values or ()) for option in surface.model_options}
                accepted = by_model.get(model or "") or tuple(surface.effort_values)
                if not accepted:
                    raise ValueError(f"{surface.caps.display_name} does not expose a reasoning-effort knob")
                if effort not in accepted:
                    raise ValueError(
                        f"Unknown effort level {effort!r}. {surface.caps.display_name} accepts: "
                        f"{', '.join(accepted)}"
                    )
        return ProjectRunModelSelection(model_override=model, harness_effort=effort)

    if effort:
        raise ValueError("harness_effort is only available for harness-backed Project channels")
    return ProjectRunModelSelection(
        model_override=model,
        model_provider_id_override=provider,
    )


def project_run_model_selection_summary(
    *,
    execution_config: dict[str, Any] | None,
    run_config: dict[str, Any] | None,
    channel: Channel | None = None,
    bot: BotRow | None = None,
) -> dict[str, Any]:
    ecfg = execution_config if isinstance(execution_config, dict) else {}
    run_cfg = run_config if isinstance(run_config, dict) else {}
    explicit = project_run_model_selection_from_config(run_cfg.get(PROJECT_RUN_MODEL_SELECTION_KEY))
    model = explicit.model_override or ecfg.get("model_override")
    provider = explicit.model_provider_id_override or ecfg.get("model_provider_id_override")
    harness_effort = explicit.harness_effort
    preset_default_effort = None
    preset_id = ecfg.get("run_preset_id")
    preset = get_run_preset(str(preset_id)) if preset_id else None
    if preset and preset.task_defaults:
        preset_default_effort = preset.task_defaults.harness_effort
    effective_model = model or getattr(channel, "model_override", None) or getattr(bot, "model", None)
    effective_provider = (
        provider
        or getattr(channel, "model_provider_id_override", None)
        or (
            resolve_provider_for_model(str(effective_model))
            if effective_model
            else None
        )
        or getattr(bot, "model_provider_id", None)
    )
    return {
        "model_override": explicit.model_override,
        "model_provider_id_override": explicit.model_provider_id_override,
        "harness_effort": explicit.harness_effort,
        "effective_model": str(effective_model) if effective_model else None,
        "effective_model_provider_id": str(effective_provider) if effective_provider else None,
        "effective_harness_effort": harness_effort or ecfg.get("harness_effort") or preset_default_effort,
        "harness_runtime": getattr(bot, "harness_runtime", None),
        "explicit": explicit.has_explicit_values,
    }
