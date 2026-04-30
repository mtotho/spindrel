"""TrueNAS JSON-RPC over WebSocket client."""
from __future__ import annotations

import asyncio
import itertools
import json
import ssl
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import websockets

from integrations.truenas.config import settings


class TrueNASConfigurationError(RuntimeError):
    """Raised when required TrueNAS settings are missing."""


class TrueNASConnectionError(RuntimeError):
    """Raised when Spindrel cannot connect to TrueNAS."""


class TrueNASApiError(RuntimeError):
    """Raised for JSON-RPC error responses from TrueNAS."""

    def __init__(self, method: str, error: dict[str, Any]):
        self.method = method
        self.code = error.get("code")
        self.data = error.get("data")
        message = str(error.get("message") or "TrueNAS API error")
        super().__init__(f"{method}: {message}")


@dataclass(frozen=True)
class TrueNASClientConfig:
    base_url: str
    api_key: str
    verify_ssl: bool = True
    connect_timeout_s: float = 10.0
    request_timeout_s: float = 30.0


def normalize_truenas_ws_url(raw_url: str) -> str:
    """Normalize a UI/base URL to the TrueNAS JSON-RPC WebSocket endpoint."""
    value = (raw_url or "").strip()
    if not value:
        raise TrueNASConfigurationError("TRUENAS_URL is not configured")
    if "://" not in value:
        value = f"https://{value}"

    parsed = urlsplit(value)
    if parsed.scheme in {"http", "ws"}:
        scheme = "ws"
    elif parsed.scheme in {"https", "wss"}:
        scheme = "wss"
    else:
        raise TrueNASConfigurationError("TRUENAS_URL must use http, https, ws, or wss")

    path = parsed.path.rstrip("/")
    if not path:
        path = "/api/current"
    elif path.endswith("/api/current") or "/api/v" in path:
        path = path
    elif path.endswith("/api"):
        path = f"{path}/current"
    else:
        path = f"{path}/api/current"

    return urlunsplit((scheme, parsed.netloc, path, "", ""))


def truenas_client_from_settings() -> "TrueNASClient":
    api_key = settings.TRUENAS_API_KEY
    if not api_key:
        raise TrueNASConfigurationError("TRUENAS_API_KEY is not configured")
    return TrueNASClient(TrueNASClientConfig(
        base_url=settings.TRUENAS_URL,
        api_key=api_key,
        verify_ssl=settings.TRUENAS_VERIFY_SSL,
        connect_timeout_s=settings.TRUENAS_CONNECT_TIMEOUT_S,
        request_timeout_s=settings.TRUENAS_REQUEST_TIMEOUT_S,
    ))


class TrueNASClient:
    def __init__(self, config: TrueNASClientConfig):
        self.config = config
        self.url = normalize_truenas_ws_url(config.base_url)
        self._ids = itertools.count(1)
        self._ws: Any | None = None

    async def __aenter__(self) -> "TrueNASClient":
        ssl_context = None
        if self.url.startswith("wss://") and not self.config.verify_ssl:
            ssl_context = ssl._create_unverified_context()
        try:
            self._ws = await websockets.connect(
                self.url,
                open_timeout=self.config.connect_timeout_s,
                close_timeout=2,
                max_size=16 * 1024 * 1024,
                ssl=ssl_context,
            )
            logged_in = await self.call("auth.login_with_api_key", [self.config.api_key])
        except TrueNASApiError:
            await self.close()
            raise
        except Exception as exc:
            await self.close()
            raise TrueNASConnectionError(f"Failed to connect to TrueNAS at {self.url}") from exc
        if not logged_in:
            await self.close()
            raise TrueNASConnectionError("TrueNAS rejected the configured API key")
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._ws is None:
            return
        ws = self._ws
        self._ws = None
        await ws.close()

    async def call(self, method: str, params: list[Any] | None = None) -> Any:
        if self._ws is None:
            raise TrueNASConnectionError("TrueNAS client is not connected")

        request_id = next(self._ids)
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or [],
        }
        await self._ws.send(json.dumps(payload))

        while True:
            raw = await asyncio.wait_for(
                self._ws.recv(),
                timeout=self.config.request_timeout_s,
            )
            response = json.loads(raw)
            if response.get("id") != request_id:
                continue
            if "error" in response:
                error = response.get("error")
                if not isinstance(error, dict):
                    error = {"message": str(error)}
                raise TrueNASApiError(method, error)
            return response.get("result")

