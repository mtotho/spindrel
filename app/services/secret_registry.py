"""Secret registry: collects known secrets and redacts them from text.

Module-level singleton — call `rebuild()` after secrets change (providers, integrations, etc.).
`redact(text)` replaces any known secret with `[REDACTED]`.
`detect_patterns(text)` finds common secret-like patterns via regex.
`check_user_input(text)` combines exact + pattern detection for pre-send warnings.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# Minimum secret length — skip short values to avoid false positives
MIN_SECRET_LENGTH = 6

# Compiled regex for matching known secrets (rebuilt on each rebuild())
_pattern: re.Pattern | None = None
# Set of known secret values (for check_user_input exact matching)
_known_secrets: set[str] = set()
# Whether the registry has been built at least once
_built = False


# ---------------------------------------------------------------------------
# Pattern regexes for common secret formats (heuristic detection)
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("OpenAI API key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("OpenAI project key", re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}")),
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("GitHub token", re.compile(r"gh[pso]_[A-Za-z0-9]{20,}")),
    ("GitHub fine-grained token", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("Slack token", re.compile(r"xox[bpas]-[A-Za-z0-9-]+")),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Generic token prefix", re.compile(r"token_[A-Za-z0-9]{16,}")),
    ("JWT", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+")),
    ("Private key header", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("Connection string", re.compile(
        r"(?:postgres(?:ql)?|mysql|mongodb|redis|amqp|mssql)"
        r"(?:\+\w+)?://[^\s]{10,}"
    )),
    ("Password assignment", re.compile(
        r"""(?:password|passwd|pwd|secret|token|api_key|apikey)"""
        r"""[\s]*[=:]\s*['"][^\s'"]{8,}['"]""",
        re.IGNORECASE,
    )),
]


async def _collect_secrets() -> set[str]:
    """Gather known secret values from all sources."""
    secrets: set[str] = set()

    def _add(val: str | None) -> None:
        if val and len(val) >= MIN_SECRET_LENGTH:
            secrets.add(val)

    # 1. Settings (config.py)
    _add(settings.API_KEY)
    _add(settings.ADMIN_API_KEY)
    _add(settings.LITELLM_API_KEY)
    _add(settings.ENCRYPTION_KEY)
    _add(settings.JWT_SECRET)
    _add(settings.GOOGLE_CLIENT_SECRET)
    _add(settings.DATABASE_URL)

    # 2. Provider registry — api_key + management_key
    try:
        from app.services.providers import _registry as provider_registry
        for row in provider_registry.values():
            _add(row.api_key)
            if row.config and isinstance(row.config, dict):
                _add(row.config.get("management_key"))
    except Exception:
        logger.debug("Could not collect provider secrets", exc_info=True)

    # 3. Integration settings — secret keys only
    try:
        from app.services.integration_settings import _cache as int_cache, _secret_keys
        for key_tuple, is_secret in _secret_keys.items():
            if is_secret:
                val = int_cache.get(key_tuple)
                _add(val)
    except Exception:
        logger.debug("Could not collect integration secrets", exc_info=True)

    # 4. MCP servers — api_key
    try:
        from app.tools.mcp import _servers as mcp_servers
        for srv in mcp_servers.values():
            _add(srv.api_key)
    except Exception:
        logger.debug("Could not collect MCP secrets", exc_info=True)

    # 5. API keys (scoped bot keys) — query DB for stored key values
    try:
        from app.db.engine import async_session
        from app.db.models import ApiKey
        from sqlalchemy import select
        async with async_session() as db:
            rows = (await db.execute(
                select(ApiKey.key_value).where(
                    ApiKey.key_value.isnot(None),
                    ApiKey.is_active == True,  # noqa: E712
                )
            )).scalars().all()
        for val in rows:
            _add(val)
    except Exception:
        logger.debug("Could not collect API key secrets", exc_info=True)

    # 6. Secret values vault (Phase 2)
    try:
        from app.services.secret_values import get_env_dict
        for val in get_env_dict().values():
            _add(val)
    except Exception:
        logger.debug("Could not collect secret values", exc_info=True)

    return secrets


def _build_pattern(secrets: set[str]) -> re.Pattern | None:
    """Build a regex alternation from secrets, sorted longest-first."""
    if not secrets:
        return None
    # Sort longest first so longer secrets are matched before shorter substrings
    sorted_secrets = sorted(secrets, key=len, reverse=True)
    escaped = [re.escape(s) for s in sorted_secrets]
    return re.compile("|".join(escaped))


async def rebuild() -> None:
    """Rebuild the secret registry from all sources."""
    global _pattern, _known_secrets, _built

    if not is_enabled():
        _pattern = None
        _known_secrets = set()
        _built = True
        return

    secrets = await _collect_secrets()
    _known_secrets = secrets
    _pattern = _build_pattern(secrets)
    _built = True

    logger.info("Secret registry rebuilt: %d secret(s) registered", len(secrets))


def redact(text: str) -> str:
    """Replace any known secret in text with [REDACTED]. No-op if disabled or no secrets."""
    if not is_enabled() or _pattern is None:
        return text
    return _pattern.sub("[REDACTED]", text)


def detect_patterns(text: str) -> list[dict[str, Any]]:
    """Regex heuristic matching for common secret formats.

    Returns [{type, match (truncated), start, end}].
    """
    results: list[dict[str, Any]] = []
    seen_spans: set[tuple[int, int]] = set()

    for label, pat in _SECRET_PATTERNS:
        for m in pat.finditer(text):
            span = (m.start(), m.end())
            if span in seen_spans:
                continue
            seen_spans.add(span)
            matched = m.group()
            # Truncate the match for safety — don't reveal the full secret
            if len(matched) > 12:
                truncated = matched[:6] + "..." + matched[-3:]
            else:
                truncated = matched[:4] + "..."
            results.append({
                "type": label,
                "match": truncated,
                "start": m.start(),
                "end": m.end(),
            })

    return results


def check_user_input(text: str) -> dict[str, Any] | None:
    """Check user input for known secrets and secret-like patterns.

    Returns {exact_matches: int, pattern_matches: [...]} or None if clean.
    Does NOT reveal which specific known secret matched (prevents oracle attacks).
    """
    exact_count = 0
    if _known_secrets:
        for secret in _known_secrets:
            if secret in text:
                exact_count += 1

    pattern_matches = detect_patterns(text)

    if exact_count == 0 and not pattern_matches:
        return None

    return {
        "exact_matches": exact_count,
        "pattern_matches": pattern_matches,
    }


def is_enabled() -> bool:
    """Check if secret redaction is enabled."""
    return getattr(settings, "SECRET_REDACTION_ENABLED", True)
