"""Favicon proxy — fetches a domain's favicon and serves it same-origin.

Interactive HTML widgets render under CSP ``connect-src 'self'`` + ``img-src
data: blob: 'self'``, so external favicon URLs (Google's s2 service, the
site's own ``/favicon.ico``) don't load. This endpoint fetches once,
returns the PNG bytes with a one-day ``Cache-Control``, and keeps an
in-process LRU so repeat widget renders don't hit the upstream each time.

Primary consumer: the ``web_search`` HTML widget (one request per result).
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections import OrderedDict

import httpx
from fastapi import APIRouter, HTTPException, Query, Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/favicon", tags=["favicon"])

_CACHE: "OrderedDict[str, tuple[bytes, str]]" = OrderedDict()
_CACHE_MAX = 256
_CACHE_LOCK = asyncio.Lock()

_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?)+$", re.I)


def _valid_domain(domain: str) -> bool:
    if not domain or len(domain) > 253:
        return False
    return bool(_DOMAIN_RE.match(domain))


async def _fetch_favicon(domain: str) -> tuple[bytes, str]:
    url = f"https://www.google.com/s2/favicons?sz=64&domain={domain}"
    async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "image/png").split(";")[0].strip()
        if not content_type.startswith("image/"):
            content_type = "image/png"
        return resp.content, content_type


@router.get("")
async def get_favicon(domain: str = Query(..., min_length=3, max_length=253)):
    """Fetch and cache a domain's favicon. Returns PNG bytes (or whatever
    the upstream provides). Unknown/bad domains → 400; upstream failure → 404."""
    domain = domain.strip().lower()
    if not _valid_domain(domain):
        raise HTTPException(400, "Invalid domain")

    async with _CACHE_LOCK:
        hit = _CACHE.get(domain)
        if hit is not None:
            _CACHE.move_to_end(domain)

    if hit is None:
        try:
            data, ct = await _fetch_favicon(domain)
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.debug("favicon fetch failed for %s: %s", domain, exc)
            raise HTTPException(404, "Favicon not available")
        async with _CACHE_LOCK:
            _CACHE[domain] = (data, ct)
            _CACHE.move_to_end(domain)
            while len(_CACHE) > _CACHE_MAX:
                _CACHE.popitem(last=False)
        hit = (data, ct)

    data, ct = hit
    return Response(
        content=data,
        media_type=ct,
        headers={"Cache-Control": "public, max-age=86400"},
    )
