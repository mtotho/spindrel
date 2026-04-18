"""Factories for app.db.models.ProviderConfig and ProviderModel."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.db.models import ProviderConfig, ProviderModel


def build_provider_config(**overrides) -> ProviderConfig:
    suffix = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=f"prov-{suffix}",
        provider_type="openai-compatible",
        display_name=f"Provider {suffix}",
        api_key=None,
        base_url="https://api.example.test",
        is_enabled=True,
        tpm_limit=None,
        rpm_limit=None,
        config={},
        billing_type="usage",
        plan_cost=None,
        plan_period=None,
        created_at=now,
        updated_at=now,
    )
    return ProviderConfig(**{**defaults, **overrides})


def build_provider_model(provider_id: str, **overrides) -> ProviderModel:
    suffix = uuid.uuid4().hex[:6]
    defaults = dict(
        provider_id=provider_id,
        model_id=f"model-{suffix}",
        display_name=f"Model {suffix}",
        max_tokens=8192,
        input_cost_per_1m="0.50",
        output_cost_per_1m="1.50",
        no_system_messages=False,
        supports_tools=True,
        supports_vision=True,
    )
    return ProviderModel(**{**defaults, **overrides})
