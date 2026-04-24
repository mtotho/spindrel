"""Background refresh of the provider catalog (model lists + pricing).

Drivers like LiteLLM, Ollama, and OpenAI-Subscription expose a live model list
that drifts as upstream providers ship new models. Today the admin UI is the
only path to pull that drift in (`POST /providers/{id}/sync-models`). This
module adds:

  - ``refresh_one_provider(provider_id)``  — single-provider refresh used by
    the new ``POST /providers/{id}/refresh-now`` endpoint and the post-test
    success hook.
  - ``refresh_all_providers()``            — iterate every enabled provider.
  - ``start_refresh_task()``               — daily background loop that calls
    ``refresh_all_providers`` once at boot and every 24h thereafter.

Each provider's last refresh timestamp + last error (if any) is written back
to ``ProviderConfig.config['last_refresh_ts']`` / ``['last_refresh_error']``
so the admin UI can surface staleness.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session
from app.db.models import ProviderConfig, ProviderModel

logger = logging.getLogger(__name__)

# 24 hours between full refreshes — providers rarely ship new models that
# fast, and hitting every catalog every minute is wasted API quota.
_REFRESH_INTERVAL_SECONDS = 24 * 60 * 60

_refresh_task: asyncio.Task | None = None


async def refresh_one_provider(
    provider_id: str, *, db: AsyncSession | None = None
) -> dict:
    """Pull driver catalog + pricing for one provider, upsert ProviderModel rows.

    Returns ``{created, updated, total, error}``. Records the result on
    ``ProviderConfig.config['last_refresh_ts']`` / ``['last_refresh_error']``.
    """
    own_session = db is None
    session_ctx = async_session() if own_session else _NoopAsyncCM(db)
    async with session_ctx as session:  # type: ignore[union-attr]
        provider = await session.get(ProviderConfig, provider_id)
        if not provider:
            return {"error": "provider not found", "created": 0, "updated": 0, "total": 0}
        if not provider.is_enabled:
            return {"error": "provider disabled", "created": 0, "updated": 0, "total": 0}

        from app.services.provider_drivers import get_driver
        from app.services.providers import get_provider as _get_provider, load_providers

        driver = get_driver(provider.provider_type)
        caps = driver.capabilities()
        if not caps.list_models:
            return {"error": "driver has no list_models", "created": 0, "updated": 0, "total": 0}

        # Drivers expect the in-memory registry row (decrypted secrets), not the
        # ORM row from a fresh session. Hit the registry; fall back to a one-shot
        # load_providers() if missing.
        registry_row = _get_provider(provider_id)
        if registry_row is None:
            await load_providers()
            registry_row = _get_provider(provider_id)
        if registry_row is None:
            return {"error": "provider not in registry", "created": 0, "updated": 0, "total": 0}

        try:
            enriched = await driver.list_models_enriched(registry_row)
        except Exception as exc:
            logger.warning("Catalog refresh failed for %s: %s", provider_id, exc)
            await _record_refresh(session, provider, error=str(exc)[:200])
            return {"error": str(exc)[:200], "created": 0, "updated": 0, "total": 0}

        if not enriched:
            await _record_refresh(session, provider, error=None)
            return {"created": 0, "updated": 0, "total": 0, "error": None}

        existing = (
            await session.execute(
                select(ProviderModel).where(ProviderModel.provider_id == provider_id)
            )
        ).scalars().all()
        existing_map = {m.model_id: m for m in existing}

        created = 0
        updated = 0
        for m in enriched:
            mid = m.get("id")
            if not mid:
                continue
            if mid in existing_map:
                row = existing_map[mid]
                changed = False
                if m.get("display") and not row.display_name:
                    row.display_name = m["display"]
                    changed = True
                for field in ("input_cost_per_1m", "output_cost_per_1m", "max_tokens"):
                    val = m.get(field)
                    if val is not None and getattr(row, field) != val:
                        setattr(row, field, val)
                        changed = True
                if changed:
                    updated += 1
            else:
                row = ProviderModel(
                    provider_id=provider_id,
                    model_id=mid,
                    display_name=m.get("display"),
                    input_cost_per_1m=m.get("input_cost_per_1m"),
                    output_cost_per_1m=m.get("output_cost_per_1m"),
                    max_tokens=m.get("max_tokens"),
                )
                session.add(row)
                created += 1

        if created or updated:
            await session.commit()

        await _record_refresh(session, provider, error=None)

        # Reload in-memory caches so accessor functions pick up new rows.
        await load_providers()

        return {
            "created": created,
            "updated": updated,
            "total": len(enriched),
            "error": None,
        }


async def refresh_all_providers() -> list[dict]:
    """Refresh every enabled provider's catalog in sequence.

    Sequential rather than parallel — driver calls are slow but cheap, and
    parallel calls would overwhelm small upstreams (Ollama, self-hosted
    LiteLLM proxies). One result dict per provider, including per-provider
    errors.
    """
    results: list[dict] = []
    async with async_session() as session:
        rows = (
            await session.execute(
                select(ProviderConfig).where(ProviderConfig.is_enabled == True)  # noqa: E712
            )
        ).scalars().all()
        provider_ids = [r.id for r in rows]

    for pid in provider_ids:
        result = await refresh_one_provider(pid)
        result["provider_id"] = pid
        results.append(result)
    return results


async def _record_refresh(
    session: AsyncSession, provider: ProviderConfig, *, error: str | None
) -> None:
    cfg = dict(provider.config or {})
    cfg["last_refresh_ts"] = datetime.now(timezone.utc).isoformat()
    if error:
        cfg["last_refresh_error"] = error
    else:
        cfg.pop("last_refresh_error", None)
    provider.config = cfg
    await session.commit()


async def _refresh_loop() -> None:
    """Daily background refresh loop. Runs once at boot, then every 24h."""
    while True:
        try:
            results = await refresh_all_providers()
            ok = sum(1 for r in results if not r.get("error"))
            logger.info(
                "Provider catalog refresh: %d/%d providers ok",
                ok, len(results),
            )
        except Exception:
            logger.exception("Provider catalog refresh loop iteration failed")
        await asyncio.sleep(_REFRESH_INTERVAL_SECONDS)


def start_refresh_task() -> None:
    """Idempotent: start the background catalog refresh loop if not running."""
    global _refresh_task
    if _refresh_task is None or _refresh_task.done():
        _refresh_task = asyncio.create_task(_refresh_loop())


class _NoopAsyncCM:
    """Tiny async context manager that yields a session without managing its lifecycle.

    Used when ``refresh_one_provider`` is called from an existing session
    (e.g. a router that already opened one). Commit/rollback stays with the
    caller; we just touch the rows.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *args) -> None:
        return None
