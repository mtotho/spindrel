"""Provider registry: manages LLM provider configs and returns per-provider AsyncOpenAI clients."""
import logging
import time
from collections import deque

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


def _make_client(provider: ProviderConfigRow) -> AsyncOpenAI:
    ptype = provider.provider_type
    if ptype == "litellm":
        return AsyncOpenAI(
            base_url=provider.base_url or settings.LITELLM_BASE_URL,
            api_key=provider.api_key or settings.LITELLM_API_KEY or "dummy",
            timeout=settings.LLM_TIMEOUT,
            max_retries=0,
        )
    elif ptype in ("openai", "openai-compatible"):
        kw: dict = {"api_key": provider.api_key, "timeout": settings.LLM_TIMEOUT, "max_retries": 0}
        if provider.base_url:
            kw["base_url"] = provider.base_url
        return AsyncOpenAI(**kw)
    elif ptype in ("anthropic", "anthropic-compatible"):
        return AsyncOpenAI(
            base_url=provider.base_url or "https://api.anthropic.com/v1",
            api_key=provider.api_key,
            timeout=settings.LLM_TIMEOUT,
            max_retries=0,
            default_headers={"anthropic-version": "2023-06-01"},
        )
    else:
        raise ValueError(f"Unknown provider type: {ptype}")


def _fallback_client() -> AsyncOpenAI:
    """Create a client from .env settings (legacy / no-DB-provider fallback)."""
    return AsyncOpenAI(
        base_url=settings.LITELLM_BASE_URL,
        api_key=settings.LITELLM_API_KEY or "dummy",
        timeout=settings.LLM_TIMEOUT,
        max_retries=0,
    )


def _litellm_mgmt_key(provider: ProviderConfigRow | None) -> str:
    """Return the management key for a LiteLLM provider (or .env fallback key)."""
    if provider is not None:
        mgmt = (provider.config or {}).get("management_key")
        if mgmt:
            return mgmt
        return provider.api_key or settings.LITELLM_API_KEY or "dummy"
    return settings.LITELLM_API_KEY or "dummy"


async def _warm_model_info_cache() -> None:
    """Fetch model info from all litellm providers (and .env fallback) into _model_info_cache."""
    targets: list[tuple[str | None, str, str]] = []  # (provider_id, base_url, key)

    # .env fallback
    if settings.LITELLM_BASE_URL:
        targets.append((None, settings.LITELLM_BASE_URL, _litellm_mgmt_key(None)))

    # DB litellm providers
    for row in _registry.values():
        if row.provider_type == "litellm":
            base = row.base_url or settings.LITELLM_BASE_URL
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
    global _registry, _client_cache, _tpm_windows, _model_info_cache, _no_sys_msg_models, _no_tools_models
    _registry = {}
    _client_cache = {}
    _tpm_windows = {}
    _model_info_cache = {}
    _no_sys_msg_models = set()
    _no_tools_models = set()

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

    # Pre-warm model info cache for all litellm providers + .env fallback
    await _warm_model_info_cache()


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


def get_provider(provider_id: str) -> ProviderConfigRow | None:
    return _registry.get(provider_id)


def list_providers() -> list[ProviderConfigRow]:
    return list(_registry.values())


def get_default_provider() -> ProviderConfigRow | None:
    """First enabled litellm provider in registry, or None (use .env fallback)."""
    for row in _registry.values():
        if row.provider_type == "litellm":
            return row
    return None


def get_llm_client(provider_id: str | None = None) -> AsyncOpenAI:
    """Return a cached AsyncOpenAI-compatible client for the given provider_id.
    Falls back to .env LiteLLM settings when provider_id is None or unknown.
    """
    cache_key = provider_id
    if cache_key in _client_cache:
        return _client_cache[cache_key]

    if provider_id is None:
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


# Hardcoded model lists for providers that don't expose an API models endpoint
_ANTHROPIC_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "claude-opus-4-5",
    "claude-sonnet-4-5",
]


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
    provider = _registry.get(provider_id)
    if provider is None:
        return []

    ptype = provider.provider_type
    # anthropic (direct) returns hardcoded list; anthropic-compatible tries the API first
    if ptype == "anthropic":
        return list(_ANTHROPIC_MODELS)

    # litellm / openai / openai-compatible / anthropic-compatible: use the models API
    try:
        client = get_llm_client(provider_id)
        models = await client.models.list()
        api_models = sorted(m.id for m in models.data)
        if api_models:
            return api_models
    except Exception as exc:
        logger.warning("Failed to list models for provider %s: %s", provider_id, exc)

    # Fallback: DB-stored models
    db_models = await _get_db_models_for_provider(provider_id)
    if db_models:
        logger.info("Using %d DB-stored models for provider %s", len(db_models), provider_id)
        return [m["id"] for m in db_models]
    return []


def _fmt_cost(per_token: float | None) -> str | None:
    """Format per-token cost as a human-readable per-1M string, e.g. '$3.00'."""
    if per_token is None:
        return None
    per_1m = per_token * 1_000_000
    if per_1m >= 1:
        return f"${per_1m:.2f}"
    elif per_1m >= 0.01:
        return f"${per_1m:.3f}"
    else:
        return f"${per_1m:.4f}"


async def _fetch_litellm_model_info(base_url: str, api_key: str) -> dict[str, dict]:
    """Fetch /model/info from a LiteLLM proxy.
    Returns {model_name: {max_tokens, input_cost_per_1m, output_cost_per_1m, ...}}.
    """
    import httpx
    info_url = base_url.rstrip("/") + "/model/info"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key and api_key != "dummy" else {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.get(info_url, headers=headers)
            r.raise_for_status()
            data = r.json()
        result: dict[str, dict] = {}
        for entry in data.get("data", []):
            name = entry.get("model_name") or entry.get("id", "")
            info = entry.get("model_info") or {}
            if name:
                ctx = info.get("max_input_tokens") or info.get("max_tokens")
                inp = _fmt_cost(info.get("input_cost_per_token"))
                out = _fmt_cost(info.get("output_cost_per_token"))
                result[name] = {
                    "max_tokens": ctx,
                    "input_cost_per_1m": inp,
                    "output_cost_per_1m": out,
                }
        logger.debug("Fetched model info from %s: %d entries", info_url, len(result))
        return result
    except Exception as exc:
        logger.warning("Failed to fetch model info from %s: %s", info_url, exc)
        return {}


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
    Always includes .env LiteLLM fallback (provider_id=None) so bots can be reset to use it.
    """
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
    fallback_base_url = settings.LITELLM_BASE_URL
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
            pass

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
        ptype = provider.provider_type
        raw_models = await list_models_for_provider(provider.id)
        model_info_map: dict[str, dict] = {}

        # Check if models came from DB (API returned empty/failed)
        db_models = await _get_db_models_for_provider(provider.id)
        db_model_map = {m["id"]: m for m in db_models}
        api_succeeded = bool(raw_models) and not all(mid in db_model_map for mid in raw_models)

        if api_succeeded and ptype == "litellm":
            base = provider.base_url or settings.LITELLM_BASE_URL
            key = provider.api_key or settings.LITELLM_API_KEY or "dummy"
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

    # Always show .env LiteLLM if the URL is configured, even alongside other DB providers.
    if has_env_litellm:
        groups.append(fallback_group)
    return groups
