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
    return truenas_ws_url_candidates(raw_url)[0]


def truenas_ws_url_candidates(raw_url: str) -> list[str]:
    """Return preferred TrueNAS WebSocket endpoints for modern and legacy NAS versions."""
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
    if path == "/websocket":
        return [urlunsplit((scheme, parsed.netloc, path, "", ""))]
    if not path:
        path = "/api/current"
    elif path.endswith("/api/current") or "/api/v" in path:
        path = path
    elif path.endswith("/api"):
        path = f"{path}/current"
    else:
        path = f"{path}/api/current"

    primary = urlunsplit((scheme, parsed.netloc, path, "", ""))
    if parsed.path.rstrip("/") == "/api/current" or "/api/v" in parsed.path:
        return [primary]
    legacy = urlunsplit((scheme, parsed.netloc, "/websocket", "", ""))
    return [primary, legacy]


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
        self.urls = truenas_ws_url_candidates(config.base_url)
        self.url = self.urls[0]
        self.protocol = "jsonrpc"
        self._ids = itertools.count(1)
        self._ws: Any | None = None

    async def __aenter__(self) -> "TrueNASClient":
        last_exc: Exception | None = None
        for url in self.urls:
            try:
                await self.connect_url(url)
                return self
            except Exception as exc:
                last_exc = exc
                await self.close()
        raise TrueNASConnectionError(f"Failed to connect to TrueNAS at {self.urls[0]}") from last_exc

    async def connect_url(self, url: str) -> None:
        self.url = url
        self.protocol = "legacy" if url.endswith("/websocket") else "jsonrpc"
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
            if self.protocol == "legacy":
                await self.legacy_handshake()
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

        if self.protocol == "legacy":
            return await self.legacy_call(method, params or [])
        return await self.jsonrpc_call(method, params or [])

    async def jsonrpc_call(self, method: str, params: list[Any]) -> Any:
        if self._ws is None:
            raise TrueNASConnectionError("TrueNAS client is not connected")

        request_id = next(self._ids)
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        await self._ws.send(json.dumps(payload))

        while True:
            raw = await self.recv_text()
            response = json.loads(raw)
            if response.get("id") != request_id:
                continue
            if "error" in response:
                error = response.get("error")
                if not isinstance(error, dict):
                    error = {"message": str(error)}
                raise TrueNASApiError(method, error)
            return response.get("result")

    async def legacy_handshake(self) -> None:
        if self._ws is None:
            raise TrueNASConnectionError("TrueNAS client is not connected")
        await self._ws.send(json.dumps({
            "msg": "connect",
            "version": "1",
            "support": ["1"],
        }))
        while True:
            message = json.loads(await self.recv_text())
            msg = message.get("msg")
            if msg == "connected":
                return
            if msg == "failed":
                raise TrueNASConnectionError("TrueNAS legacy websocket handshake failed")

    async def legacy_call(self, method: str, params: list[Any]) -> Any:
        if self._ws is None:
            raise TrueNASConnectionError("TrueNAS client is not connected")

        request_id = str(next(self._ids))
        await self._ws.send(json.dumps({
            "msg": "method",
            "method": method,
            "params": params,
            "id": request_id,
        }))
        while True:
            message = json.loads(await self.recv_text())
            if message.get("id") != request_id:
                continue
            if message.get("msg") == "result":
                if "error" in message:
                    error = message.get("error")
                    if not isinstance(error, dict):
                        error = {"message": str(error)}
                    raise TrueNASApiError(method, error)
                return message.get("result")

    async def recv_text(self) -> str:
        if self._ws is None:
            raise TrueNASConnectionError("TrueNAS client is not connected")
        return await asyncio.wait_for(
            self._ws.recv(),
            timeout=self.config.request_timeout_s,
        )
