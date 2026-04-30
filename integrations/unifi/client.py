"""Client for the official local UniFi Network Integration API."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from integrations.unifi.config import settings

logger = logging.getLogger(__name__)

SENSITIVE_KEY_PARTS = {
    "api_key",
    "apikey",
    "auth",
    "credential",
    "key",
    "pass",
    "password",
    "psk",
    "secret",
    "token",
}


class UniFiConfigurationError(RuntimeError):
    """Raised when required UniFi settings are missing."""


class UniFiConnectionError(RuntimeError):
    """Raised when Spindrel cannot connect to UniFi."""

    def __init__(self, message: str, *, attempts: list[dict[str, Any]] | None = None):
        self.attempts = attempts or []
        super().__init__(message)


class UniFiApiError(RuntimeError):
    """Raised for UniFi API status errors."""

    def __init__(self, method: str, path: str, status_code: int, detail: str = ""):
        self.method = method
        self.path = path
        self.status_code = status_code
        self.detail = detail
        suffix = f": {detail}" if detail else ""
        super().__init__(f"{method} {path}: HTTP {status_code}{suffix}")


@dataclass(frozen=True)
class UniFiClientConfig:
    base_url: str
    api_key: str
    site_id: str = ""
    verify_ssl: bool = True
    api_base_path: str = "/proxy/network/integration/v1"
    connect_timeout_s: float = 10.0
    request_timeout_s: float = 30.0


def normalize_unifi_base_url(raw_url: str) -> str:
    value = (raw_url or "").strip()
    if not value:
        raise UniFiConfigurationError("UNIFI_URL is not configured")
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        raise UniFiConfigurationError("UNIFI_URL must use http or https")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def normalize_unifi_api_path(path: str) -> str:
    value = (path or "/proxy/network/integration/v1").strip()
    if not value.startswith("/"):
        value = f"/{value}"
    return value.rstrip("/")


def unifi_api_path_candidates(path: str) -> list[str]:
    primary = normalize_unifi_api_path(path)
    candidates = [primary]
    fallbacks = ["/proxy/network/integration/v1", "/integration/v1", "/v1"]
    for item in fallbacks:
        normalized = normalize_unifi_api_path(item)
        if normalized not in candidates:
            candidates.append(normalized)
    return candidates


def unifi_client_from_settings() -> "UniFiClient":
    api_key = settings.UNIFI_API_KEY
    if not api_key:
        raise UniFiConfigurationError("UNIFI_API_KEY is not configured")
    return UniFiClient(UniFiClientConfig(
        base_url=settings.UNIFI_URL,
        api_key=api_key,
        site_id=settings.UNIFI_SITE_ID,
        verify_ssl=settings.UNIFI_VERIFY_SSL,
        api_base_path=settings.UNIFI_API_BASE_PATH,
        connect_timeout_s=settings.UNIFI_CONNECT_TIMEOUT_S,
        request_timeout_s=settings.UNIFI_REQUEST_TIMEOUT_S,
    ))


def redact_unifi_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in SENSITIVE_KEY_PARTS):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = redact_unifi_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_unifi_payload(item) for item in value]
    return value


class UniFiClient:
    def __init__(self, config: UniFiClientConfig):
        self.config = config
        self.base_url = normalize_unifi_base_url(config.base_url)
        self.api_base_paths = unifi_api_path_candidates(config.api_base_path)
        self.api_base_path = self.api_base_paths[0]
        self.site_id = config.site_id.strip()
        self.connection_attempts: list[dict[str, Any]] = []
        timeout = httpx.Timeout(
            config.request_timeout_s,
            connect=config.connect_timeout_s,
        )
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-API-KEY": config.api_key},
            timeout=timeout,
            verify=config.verify_ssl,
        )

    async def __aenter__(self) -> "UniFiClient":
        last_exc: Exception | None = None
        for path in self.api_base_paths:
            try:
                self.api_base_path = path
                await self.get("/sites")
                self.connection_attempts.append({
                    "base_url": self.base_url,
                    "api_base_path": path,
                    "status": "connected",
                })
                logger.info("Connected to UniFi Network API at %s%s", self.base_url, path)
                return self
            except Exception as exc:
                last_exc = exc
                self.connection_attempts.append({
                    "base_url": self.base_url,
                    "api_base_path": path,
                    "status": "failed",
                    "error": str(exc),
                    "exception_type": type(exc).__name__,
                })
                logger.warning("UniFi API base path failed: %s%s (%s)", self.base_url, path, exc)
        raise UniFiConnectionError(
            f"Failed to connect to UniFi Network API at {self.base_url}{self.api_base_paths[0]}",
            attempts=self.connection_attempts,
        ) from last_exc

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    def connection_summary(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "api_base_path": self.api_base_path,
            "site_id": self.site_id,
            "verify_ssl": self.config.verify_ssl,
            "attempted_endpoints": self.connection_attempts,
        }

    def url_for(self, path: str) -> str:
        clean = path if path.startswith("/") else f"/{path}"
        return f"{self.api_base_path}{clean}"

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        api_path = self.url_for(path)
        response = await self._client.get(api_path, params=params)
        if response.status_code >= 400:
            detail = response.text[:240]
            raise UniFiApiError("GET", api_path, response.status_code, detail)
        if not response.content:
            return None
        return redact_unifi_payload(response.json())

    async def get_first(self, paths: list[str], params: dict[str, Any] | None = None) -> Any:
        last_exc: Exception | None = None
        for path in paths:
            try:
                return await self.get(path, params=params)
            except UniFiApiError as exc:
                if exc.status_code not in {400, 404, 405}:
                    raise
                last_exc = exc
        if last_exc:
            raise last_exc
        raise UniFiApiError("GET", paths[0] if paths else "", 404, "No candidate endpoint")

    async def list_paginated(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        limit: int = 200,
        max_items: int = 1000,
    ) -> list[Any]:
        items: list[Any] = []
        offset = 0
        while len(items) < max_items:
            page_params = dict(params or {})
            page_params.setdefault("limit", min(limit, max_items - len(items)))
            page_params.setdefault("offset", offset)
            payload = await self.get(path, params=page_params)
            page = unifi_extract_items(payload)
            items.extend(page)
            total = unifi_extract_total(payload)
            if not page or (total is not None and len(items) >= total):
                break
            if len(page) < int(page_params["limit"]):
                break
            offset += len(page)
        return items[:max_items]

    async def sites(self) -> list[Any]:
        return unifi_extract_items(await self.get("/sites"))

    async def selected_site_id(self) -> str:
        if self.site_id:
            return self.site_id
        sites = await self.sites()
        for site in sites:
            if isinstance(site, dict):
                value = site.get("id") or site.get("siteId") or site.get("_id") or site.get("name")
                if value:
                    self.site_id = str(value)
                    return self.site_id
        raise UniFiApiError("GET", self.url_for("/sites"), 404, "No UniFi site was returned")


def unifi_extract_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("data", "items", "results", "sites", "devices", "clients", "networks", "wifis", "wifi"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def unifi_extract_total(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    for key in ("totalCount", "total_count", "total", "count"):
        value = payload.get(key)
        if isinstance(value, int):
            return value
    return None
