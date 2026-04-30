"""Per-session harness settings — model, effort, runtime-specific knobs.

Stored under ``Session.metadata_['harness_settings']`` as a plain dict::

    {
        "model": "claude-sonnet-...",        # optional
        "mode_models": {                     # optional, v2 compatibility
            "default": "claude-sonnet-...",
            "plan": "claude-opus-..."
        },
        "effort": "medium",                   # optional
        "runtime_settings": {...}             # optional, opaque per-runtime
    }

The shape mirrors the Phase 3 ``harness_approval_mode`` pattern: settings
are scoped to a single session id, and each pane / scratch surface targets
its own session so multi-pane mode-changes don't clobber each other.

PATCH semantics: ``patch_session_settings`` accepts a partial dict
(typically ``body.dict(exclude_unset=True)`` from a Pydantic model). Missing
keys leave fields unchanged. JSON ``null`` clears a field.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import Session

HARNESS_SETTINGS_KEY = "harness_settings"

# Sanity bound on freeform model strings. Real model ids are short; anything
# longer is almost certainly a paste accident or hostile input.
MODEL_ID_MAX_LEN = 256


@dataclass(frozen=True)
class HarnessSettings:
    model: str | None = None
    effort: str | None = None
    runtime_settings: dict[str, Any] = field(default_factory=dict)
    mode_models: dict[str, str] = field(default_factory=dict)


def _sanitize_model(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("model id must be non-empty")
    if len(trimmed) > MODEL_ID_MAX_LEN:
        raise ValueError(
            f"model id exceeds {MODEL_ID_MAX_LEN}-character limit"
        )
    return trimmed


def _sanitize_mode_models(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    clean: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        normalized_key = key.strip()
        normalized_value = value.strip()
        if normalized_key and normalized_value:
            clean[normalized_key] = normalized_value
    return clean


def _settings_mode_key(session: Session) -> str:
    """Map the current session runtime mode to a harness-settings bucket.

    Native Codex/Claude planning has different model expectations than normal
    execution. Keep the persisted setting separate while preserving the old
    top-level ``model`` field as the default/chat bucket for compatibility.
    """
    try:
        from app.services.session_plan_mode import (
            PLAN_MODE_PLANNING,
            get_session_plan_mode,
        )

        return "plan" if get_session_plan_mode(session) == PLAN_MODE_PLANNING else "default"
    except Exception:
        return "default"


async def load_session_settings(
    db: AsyncSession, session_id: uuid.UUID
) -> HarnessSettings:
    """Read settings for a session. Missing session or missing key → defaults."""
    session = await db.get(Session, session_id)
    if session is None:
        return HarnessSettings()
    raw = (session.metadata_ or {}).get(HARNESS_SETTINGS_KEY) or {}
    mode_models = _sanitize_mode_models(raw.get("mode_models"))
    mode_key = _settings_mode_key(session)
    model = mode_models.get(mode_key)
    if model is None and mode_key == "default":
        legacy_model = raw.get("model")
        if isinstance(legacy_model, str) and legacy_model.strip():
            model = legacy_model.strip()
    return HarnessSettings(
        model=model,
        effort=raw.get("effort"),
        runtime_settings=dict(raw.get("runtime_settings") or {}),
        mode_models=mode_models,
    )


async def patch_session_settings(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    patch: dict[str, Any],
) -> HarnessSettings:
    """Partial update. ``patch`` keys: any subset of {model, effort, runtime_settings}.

    Missing key = no change. ``None`` value = clear that field. Otherwise the
    value is set. Empty effective settings remove the metadata key entirely.
    """
    session = await db.get(Session, session_id)
    if session is None:
        raise ValueError(f"session not found: {session_id}")

    meta = dict(session.metadata_ or {})
    current = dict(meta.get(HARNESS_SETTINGS_KEY) or {})
    mode_key = _settings_mode_key(session)
    mode_models = _sanitize_mode_models(current.get("mode_models"))

    if "model" in patch:
        value = patch["model"]
        if value is None:
            mode_models.pop(mode_key, None)
            if mode_key == "default":
                current.pop("model", None)
        else:
            if not isinstance(value, str):
                raise ValueError("model must be a string or null")
            clean_model = _sanitize_model(value)
            mode_models[mode_key] = clean_model
            if mode_key == "default":
                current["model"] = clean_model
    if mode_models:
        current["mode_models"] = mode_models
    else:
        current.pop("mode_models", None)

    if "effort" in patch:
        value = patch["effort"]
        if value is None:
            current.pop("effort", None)
        else:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("effort must be a non-empty string or null")
            current["effort"] = value.strip()

    if "runtime_settings" in patch:
        value = patch["runtime_settings"]
        if value is None:
            current.pop("runtime_settings", None)
        else:
            if not isinstance(value, dict):
                raise ValueError("runtime_settings must be an object or null")
            current["runtime_settings"] = value

    if current:
        meta[HARNESS_SETTINGS_KEY] = current
    else:
        meta.pop(HARNESS_SETTINGS_KEY, None)

    session.metadata_ = meta
    flag_modified(session, "metadata_")
    await db.commit()

    return await load_session_settings(db, session_id)
