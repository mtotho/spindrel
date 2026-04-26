"""Per-session harness settings — model, effort, runtime-specific knobs.

Stored under ``Session.metadata_['harness_settings']`` as a plain dict::

    {
        "model": "claude-sonnet-...",        # optional
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


def _sanitize_model(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("model id must be non-empty")
    if len(trimmed) > MODEL_ID_MAX_LEN:
        raise ValueError(
            f"model id exceeds {MODEL_ID_MAX_LEN}-character limit"
        )
    return trimmed


async def load_session_settings(
    db: AsyncSession, session_id: uuid.UUID
) -> HarnessSettings:
    """Read settings for a session. Missing session or missing key → defaults."""
    session = await db.get(Session, session_id)
    if session is None:
        return HarnessSettings()
    raw = (session.metadata_ or {}).get(HARNESS_SETTINGS_KEY) or {}
    return HarnessSettings(
        model=raw.get("model"),
        effort=raw.get("effort"),
        runtime_settings=dict(raw.get("runtime_settings") or {}),
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

    if "model" in patch:
        value = patch["model"]
        if value is None:
            current.pop("model", None)
        else:
            if not isinstance(value, str):
                raise ValueError("model must be a string or null")
            current["model"] = _sanitize_model(value)

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
