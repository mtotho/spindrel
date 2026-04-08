"""Provider registry: manages LLM provider configs and returns per-provider AsyncOpenAI clients."""
import asyncio
import logging
import time
from collections import deque
from pathlib import Path

from openai import AsyncOpenAI
from sqlalchemy import select

from app.config import settings
from app.db.engine import async_session
from app.db.models import ProviderConfig as ProviderConfigRow, ProviderModel

logger = logging.getLogger(__name__)

_registry: dict[str, ProviderConfigRow] = {}
_client_cache: dict[str | None, AsyncOpenAI] = {}
# TPM windows: per provider_id, deque of (monotonic_timestamp, token_count)
_tpm_windows: dict[str, deque] = {}
# model info cache: provider_id (or None for .env) → {model_name: {max_tokens, input_cost_per_1m, output_cost_per_1m}}
_model_info_cache: dict[str | None, dict[str, dict]] = {}
# Cached set of model_ids flagged as no_system_messages in provider_models table
_no_sys_msg_models: set[str] = set()
# Cached set of model_ids flagged as supports_tools=False in provider_models table
_no_tools_models: set[str] = set()
# Cached set of model_ids flagged as supports_vision=False in provider_models table
_no_vision_models: set[str] = set()
# Cached set of model_ids belonging to plan-billed providers
_plan_billed_models: set[str] = set()
# Reverse index: model_id → provider_id (built from provider_models table)
_model_to_provider: dict[str, str] = {}
# Volatile reverse index: populated from live model listings (fallback for models not in DB)
_live_model_to_provider: dict[str, str] = {}


async def seed_provider_from_file(path: Path = Path("provider-seed.yaml")) -> None:
    """On first boot, create a provider from the setup wizard's seed file.

    The seed file is written by ``scripts/setup.py`` and contains a single
    provider config (id, provider_type, display_name, base_url, api_key).
    Once consumed the file is deleted so the seed is one-shot.
    """
    if not path.exists():
        return

    import yaml

    data = yaml.safe_load(path.read_text())
    if not data or not data.get("provider_type"):
        logger.warning("Ignoring malformed provider seed file: %s", path)
        return

    async with async_session() as db:
        existing = await db.get(ProviderConfigRow, data["id"])
        if existing:
            logger.info("Provider '%s' already exists, skipping seed", data["id"])
            path.unlink(missing_ok=True)
            return

        from app.services.encryption import encrypt

        api_key = data.get("api_key", "")

        provider = ProviderConfigRow(
            id=data["id"],
            provider_type=data["provider_type"],
            display_name=data.get("display_name", data["id"]),
            base_url=data.get("base_url"),
            api_key=encrypt(api_key) if api_key else None,
            is_enabled=True,
        )
        db.add(provider)
        await db.commit()
        logger.info("Seeded provider '%s' (%s) from %s", data["id"], data["provider_type"], path)

    path.unlink(missing_ok=True)


def _make_client(provider: ProviderConfigRow) -> AsyncOpenAI:
    from app.services.provider_drivers import get_driver

    return get_driver(provider.provider_type).make_client(provider)


def _fallback_client() -> AsyncOpenAI:
    """Create a client from .env settings (legacy / no-DB-provider fallback)."""
    return AsyncOpenAI(
        base_url=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY or "dummy",
        timeout=settings.LLM_TIMEOUT,
        max_retries=0,
    )


def _litellm_mgmt_key(provider: ProviderConfigRow | None) -> str:
    """Return the management key for a LiteLLM provider (or .env fallback key)."""
    from app.services.provider_drivers.litellm_driver import _litellm_mgmt_key as _mgmt_key

    return _mgmt_key(provider)


async def _warm_model_info_cache() -> None:
    """Fetch model info from all litellm providers (and .env fallback) into _model_info_cache."""
    from app.services.provider_drivers.litellm_driver import _fetch_litellm_model_info

    targets: list[tuple[str | None, str, str]] = []  # (provider_id, base_url, key)

    # .env fallback
    if settings.LLM_BASE_URL:
        targets.append((None, settings.LLM_BASE_URL, _litellm_mgmt_key(None)))

    # DB litellm providers
    for row in _registry.values():
        if row.provider_type == "litellm":
            base = row.base_url or settings.LLM_BASE_URL
            if base:
                targets.append((row.id, base, _litellm_mgmt_key(row)))

    for provider_id, base_url, key in targets:
        info_map = await _fetch_litellm_model_info(base_url, key)
        _model_info_cache[provider_id] = info_map
        logger.info(
            "Cached model info for provider %s: %d models", provider_id or ".env", len(info_map)
        )


async def load_providers() -> None:
    """Load all enabled providers from DB into the in-memory registry. Clears client cache."""
    global _registry, _client_cache, _tpm_windows, _model_info_cache, _no_sys_msg_models, _no_tools_models, _plan_billed_models, _model_to_provider, _live_model_to_provider
    _registry = {}
    _client_cache = {}
    _tpm_windows = {}
    _model_info_cache = {}
    _no_sys_msg_models = set()
    _no_tools_models = set()
    _no_vision_models = set()
    _plan_billed_models = set()
    _model_to_provider = {}
    _live_model_to_provider = {}

    async with async_session() as db:
        rows = (
            await db.execute(
                select(ProviderConfigRow).where(ProviderConfigRow.is_enabled == True)  # noqa: E712
            )
        ).scalars().all()

        # Load model IDs flagged as no_system_messages
        flagged = (
            await db.execute(
                select(ProviderModel.model_id).where(
                    ProviderModel.no_system_messages == True  # noqa: E712
                )
            )
        ).scalars().all()
        _no_sys_msg_models = set(flagged)

        # Load model IDs flagged as not supporting tools
        no_tools = (
            await db.execute(
                select(ProviderModel.model_id).where(
                    ProviderModel.supports_tools == False  # noqa: E712
                )
            )
        ).scalars().all()
        _no_tools_models = set(no_tools)

        # Load model IDs flagged as not supporting vision
        no_vision = (
            await db.execute(
                select(ProviderModel.model_id).where(
                    ProviderModel.supports_vision == False  # noqa: E712
                )
            )
        ).scalars().all()
        _no_vision_models = set(no_vision)

        # Load model IDs belonging to plan-billed providers
        plan_provider_ids = [r.id for r in rows if r.billing_type == "plan"]
        if plan_provider_ids:
            plan_models = (
                await db.execute(
                    select(ProviderModel.model_id).where(
                        ProviderModel.provider_id.in_(plan_provider_ids)
                    )
                )
            ).scalars().all()
            _plan_billed_models = set(plan_models)

        # Build reverse index: model_id → provider_id
        # Also seed _model_info_cache with max_tokens from ProviderModel DB rows
        # so get_model_context_window() works for ANY provider, not just litellm.
        all_pm = (
            await db.execute(
                select(ProviderModel.model_id, ProviderModel.provider_id, ProviderModel.max_tokens)
            )
        ).all()
        for model_id, provider_id, max_tokens in all_pm:
            # First provider wins; if a model appears on multiple providers,
            # user should pass provider_id explicitly (or use channel/bot config).
            if model_id not in _model_to_provider:
                _model_to_provider[model_id] = provider_id
            if max_tokens:
                if provider_id not in _model_info_cache:
                    _model_info_cache[provider_id] = {}
                _model_info_cache[provider_id].setdefault(
                    model_id, {},
                ).setdefault("max_tokens", max_tokens)

    from app.services.encryption import decrypt

    for row in rows:
        # Decrypt secrets so in-memory registry holds usable values
        if row.api_key:
            row.api_key = decrypt(row.api_key)
        if row.config and row.config.get("management_key"):
            config = dict(row.config)
            config["management_key"] = decrypt(config["management_key"])
            row.config = config
        _registry[row.id] = row
        logger.info("Loaded provider: %s (%s)", row.id, row.provider_type)

    if not _registry:
        logger.info("No DB providers configured — using .env LiteLLM fallback for all LLM calls")
    else:
        logger.info("Loaded %d provider(s) from DB", len(_registry))

    if _no_sys_msg_models:
        logger.info("Models with no_system_messages flag: %s", _no_sys_msg_models)
    if _no_tools_models:
        logger.info("Models with supports_tools=false flag: %s", _no_tools_models)
    if _no_vision_models:
        logger.info("Models with supports_vision=false flag: %s", _no_vision_models)
    if _plan_billed_models:
        logger.info("Models on plan-billed providers: %s", _plan_billed_models)

    # Pre-warm model info cache for all litellm providers + .env fallback
    await _warm_model_info_cache()

    # Rebuild secret registry so new provider keys are tracked
    try:
        from app.services.secret_registry import rebuild as _rebuild_secrets
        asyncio.create_task(_rebuild_secrets())
    except Exception:
        pass


async def has_encrypted_secrets() -> bool:
    """Check if any provider rows in the DB contain encrypted values (enc: prefix).

    This queries raw DB values before decryption — used at startup to detect
    undecryptable secrets when ENCRYPTION_KEY is not set.
    """
    from app.services.encryption import ENCRYPTED_PREFIX

    async with async_session() as db:
        rows = (
            await db.execute(
                select(ProviderConfigRow.api_key, ProviderConfigRow.config)
                .where(ProviderConfigRow.is_enabled == True)  # noqa: E712
            )
        ).all()
    for api_key, config in rows:
        if api_key and api_key.startswith(ENCRYPTED_PREFIX):
            return True
        if isinstance(config, dict):
            mgmt_key = config.get("management_key", "")
            if mgmt_key and mgmt_key.startswith(ENCRYPTED_PREFIX):
                return True
    return False


def requires_system_message_folding(model: str) -> bool:
    """Check whether a model requires system messages to be folded into user messages.

    Resolution order:
    1. Explicit DB flag (provider_models.no_system_messages) — checked via cached set.
    2. Heuristic fallback: provider family prefix matches known no-system-message providers.
    """
    if model in _no_sys_msg_models:
        return True
    from app.agent.model_params import _HEURISTIC_NO_SYS_MSG_FAMILIES, get_provider_family
    return get_provider_family(model) in _HEURISTIC_NO_SYS_MSG_FAMILIES


def model_supports_tools(model: str) -> bool:
    """Check whether a model supports function calling / tools.

    Resolution order:
    1. Explicit DB flag (provider_models.supports_tools=False) — checked via cached set.
    2. Heuristic fallback: exact model ID or substring pattern match.
    """
    if model in _no_tools_models:
        return False
    from app.agent.model_params import _HEURISTIC_NO_TOOLS_MODELS, _HEURISTIC_NO_TOOLS_PATTERNS
    if model in _HEURISTIC_NO_TOOLS_MODELS:
        return False
    model_lower = model.lower()
    for pattern in _HEURISTIC_NO_TOOLS_PATTERNS:
        if pattern in model_lower:
            return False
    return True


def model_supports_vision(model: str) -> bool:
    """Check whether a model supports image/vision content.

    Defaults to True. Set to False in the DB (provider_models.supports_vision)
    or auto-learned at runtime when the API rejects image_url content.
    """
    return model not in _no_vision_models


async def mark_model_no_vision(model: str) -> None:
    """Persist supports_vision=False for *model* and update the runtime cache.

    Called automatically when the API rejects image_url content for a model.
    """
    global _no_vision_models
    if model in _no_vision_models:
        return
    _no_vision_models = _no_vision_models | {model}
    logger.warning("Auto-learned: model %s does not support vision — persisting flag", model)
    try:
        from sqlalchemy import update
        async with async_session() as db:
            result = await db.execute(
                update(ProviderModel)
                .where(ProviderModel.model_id == model)
                .values(supports_vision=False)
            )
            await db.commit()
            if result.rowcount == 0:
                logger.info("No ProviderModel row for %s — flag cached in-memory only", model)
    except Exception:
        logger.exception("Failed to persist supports_vision=false for %s", model)


def get_provider(provider_id: str) -> ProviderConfigRow | None:
    return _registry.get(provider_id)


def list_providers() -> list[ProviderConfigRow]:
    return list(_registry.values())


def get_default_provider() -> ProviderConfigRow | None:
    """First enabled provider in registry (any type), or None."""
    for row in _registry.values():
        if row.is_enabled:
            return row
    return None


def resolve_provider_for_model(model: str) -> str | None:
    """Look up the provider_id that owns *model* via the reverse index.

    Checks the DB-backed index first, then the volatile index (populated
    from live model listings).  Only returns providers whose driver declares
    chat_completions=True.

    Returns None if the model isn't in any provider's model list (caller
    should fall back to the .env default client).
    """
    from app.services.provider_drivers import get_driver

    # Try DB index, then volatile live-listing index
    provider_id = _model_to_provider.get(model) or _live_model_to_provider.get(model)
    if provider_id is None:
        return None
    provider = _registry.get(provider_id)
    if provider is None:
        return None
    driver = get_driver(provider.provider_type)
    if not driver.capabilities().chat_completions:
        return None
    return provider_id


def get_llm_client(provider_id: str | None = None) -> AsyncOpenAI:
    """Return a cached AsyncOpenAI-compatible client for the given provider_id.

    When *provider_id* is None, prefers the first enabled DB provider before
    falling back to .env settings.
    """
    cache_key = provider_id
    if cache_key in _client_cache:
        return _client_cache[cache_key]

    if provider_id is None:
        # Prefer DB provider over .env fallback
        default = get_default_provider()
        if default:
            client = _make_client(default)
            _client_cache[default.id] = client
        else:
            client = _fallback_client()
    else:
        provider = _registry.get(provider_id)
        if provider is None:
            logger.warning(
                "Provider '%s' not found in registry, falling back to .env settings",
                provider_id,
            )
            client = _fallback_client()
        else:
            client = _make_client(provider)

    _client_cache[cache_key] = client
    return client


def check_rate_limit(provider_id: str | None, estimated_tokens: int) -> int | None:
    """Check TPM limit for a provider. Returns seconds_to_wait if over budget, None if clear."""
    if provider_id is None:
        return None
    provider = _registry.get(provider_id)
    if provider is None or not provider.tpm_limit:
        return None

    now = time.monotonic()
    window = _tpm_windows.setdefault(provider_id, deque(maxlen=10000))
    # Evict entries older than 60s
    while window and window[0][0] < now - 60:
        window.popleft()

    current_tokens = sum(t for _, t in window)
    if current_tokens + estimated_tokens > provider.tpm_limit:
        if window:
            oldest_ts = window[0][0]
            wait = max(1, int(oldest_ts + 60 - now) + 1)
        else:
            wait = 1
        return wait
    return None


def record_usage(provider_id: str | None, total_tokens: int) -> None:
    """Record token usage after a successful LLM call (for rolling TPM window)."""
    if provider_id is None:
        return
    provider = _registry.get(provider_id)
    if provider is None or not provider.tpm_limit:
        return
    now = time.monotonic()
    _tpm_windows.setdefault(provider_id, deque(maxlen=10000)).append((now, total_tokens))


async def _get_db_models_for_provider(provider_id: str) -> list[dict]:
    """Query provider_models table and return enriched dicts."""
    async with async_session() as db:
        rows = (
            await db.execute(
                select(ProviderModel)
                .where(ProviderModel.provider_id == provider_id)
                .order_by(ProviderModel.model_id)
            )
        ).scalars().all()
    result = []
    for r in rows:
        parts = []
        if r.max_tokens:
            parts.append(f"{r.max_tokens // 1000}k")
        if r.input_cost_per_1m or r.output_cost_per_1m:
            parts.append(f"{r.input_cost_per_1m or '?'}/{r.output_cost_per_1m or '?'}")
        display = f"{r.model_id} ({', '.join(parts)})" if parts else r.model_id
        if r.display_name:
            display = r.display_name
        result.append({
            "id": r.model_id,
            "display": display,
            "max_tokens": r.max_tokens,
            "input_cost_per_1m": r.input_cost_per_1m,
            "output_cost_per_1m": r.output_cost_per_1m,
            "_from_db": True,
        })
    return result


async def list_models_for_provider(provider_id: str) -> list[str]:
    """Fetch available models for a specific provider. Falls back to DB models."""
    from app.services.provider_drivers import get_driver

    provider = _registry.get(provider_id)
    if provider is None:
        return []

    driver = get_driver(provider.provider_type)
    api_models = await driver.list_models(provider)
    if api_models:
        return api_models

    # Fallback: DB-stored models
    db_models = await _get_db_models_for_provider(provider_id)
    if db_models:
        logger.info("Using %d DB-stored models for provider %s", len(db_models), provider_id)
        return [m["id"] for m in db_models]
    return []


def get_cached_model_info(model_id: str, provider_id: str | None = None) -> dict | None:
    """Look up cached model info for a model. Checks provider_id cache first, then all caches."""
    if provider_id in _model_info_cache:
        info = _model_info_cache[provider_id].get(model_id)
        if info:
            return info
    # Search across all provider caches
    for cache in _model_info_cache.values():
        if model_id in cache:
            return cache[model_id]
    return None


async def get_available_models_grouped() -> list[dict]:
    """Return all models from all providers, grouped by provider.
    Each entry: {provider_id, provider_name, provider_type, models: [{id, display, max_tokens}]}
    Includes .env fallback only when no DB providers exist.
    """
    from app.services.provider_drivers.litellm_driver import _fetch_litellm_model_info

    groups = []

    def _enrich(mid: str, info: dict) -> dict:
        ctx = info.get("max_tokens")
        inp = info.get("input_cost_per_1m")
        out = info.get("output_cost_per_1m")
        parts = []
        if ctx:
            parts.append(f"{ctx // 1000}k")
        if inp or out:
            parts.append(f"{inp or '?'}/{out or '?'}")
        display = f"{mid} ({', '.join(parts)})" if parts else mid
        return {"id": mid, "display": display, "max_tokens": ctx,
                "input_cost_per_1m": inp, "output_cost_per_1m": out}

    # Build .env fallback group
    fallback_base_url = settings.LLM_BASE_URL
    fallback_models: list[dict] = []
    if fallback_base_url:
        try:
            client = _fallback_client()
            model_list = await client.models.list()
            raw_ids = sorted(m.id for m in model_list.data)
            # Use cached info if available, otherwise fetch
            if None not in _model_info_cache:
                _model_info_cache[None] = await _fetch_litellm_model_info(
                    fallback_base_url, _litellm_mgmt_key(None)
                )
            for mid in raw_ids:
                fallback_models.append(_enrich(mid, _model_info_cache[None].get(mid, {})))
        except Exception:
            logger.warning("Failed to list models from .env fallback (%s)", fallback_base_url, exc_info=True)

    fallback_group = {
        "provider_id": None,
        "provider_name": "LiteLLM (.env fallback)",
        "provider_type": "litellm",
        "models": fallback_models,
    }

    has_env_litellm = bool(fallback_base_url)
    if not _registry:
        groups.append(fallback_group)
        return groups

    for provider in _registry.values():
        try:
            ptype = provider.provider_type
            raw_models = await list_models_for_provider(provider.id)
            model_info_map: dict[str, dict] = {}

            # Check if models came from DB (API returned empty/failed)
            db_models = await _get_db_models_for_provider(provider.id)
            db_model_map = {m["id"]: m for m in db_models}
            api_succeeded = bool(raw_models) and not all(mid in db_model_map for mid in raw_models)

            if api_succeeded and ptype == "litellm":
                base = provider.base_url or settings.LLM_BASE_URL
                key = provider.api_key or settings.LLM_API_KEY or "dummy"
                if base:
                    model_info_map = await _fetch_litellm_model_info(base, key)
                    _model_info_cache[provider.id] = model_info_map  # cache for bots list badge

            enriched: list[dict] = []
            for mid in raw_models:
                if mid in db_model_map:
                    # Use DB enrichment directly (already formatted)
                    entry = db_model_map[mid]
                    enriched.append({
                        "id": entry["id"], "display": entry["display"],
                        "max_tokens": entry["max_tokens"],
                        "input_cost_per_1m": entry["input_cost_per_1m"],
                        "output_cost_per_1m": entry["output_cost_per_1m"],
                    })
                    # Populate model info cache so context estimate badges work
                    _model_info_cache.setdefault(provider.id, {})[mid] = {
                        "max_tokens": entry["max_tokens"],
                        "input_cost_per_1m": entry["input_cost_per_1m"],
                        "output_cost_per_1m": entry["output_cost_per_1m"],
                    }
                else:
                    enriched.append(_enrich(mid, model_info_map.get(mid, {})))
            groups.append({
                "provider_id": provider.id,
                "provider_name": provider.display_name,
                "provider_type": provider.provider_type,
                "models": enriched,
            })
        except Exception:
            logger.exception("Failed to list models for provider %s (%s)", provider.id, provider.provider_type)
            groups.append({
                "provider_id": provider.id,
                "provider_name": provider.display_name,
                "provider_type": provider.provider_type,
                "models": [],
            })

    # Update volatile model→provider index from live listing data.
    # This allows resolve_provider_for_model to find models that haven't
    # been synced to the provider_models DB table yet.
    global _live_model_to_provider
    new_idx: dict[str, str] = {}
    for g in groups:
        pid = g.get("provider_id")
        if pid is None:
            continue
        for m in g.get("models", []):
            mid = m.get("id", "")
            if mid and mid not in new_idx:
                new_idx[mid] = pid
    _live_model_to_provider = new_idx

    return groups
