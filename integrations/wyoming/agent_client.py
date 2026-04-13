"""HTTP client for communicating with the agent server."""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class AgentClient:
    """Async HTTP client for the Spindrel agent server."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._http = httpx.AsyncClient(timeout=30.0)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def ensure_channel(self, client_id: str, bot_id: str) -> dict | None:
        """Ensure a Channel row exists for this client_id. Returns channel dict."""
        try:
            r = await self._http.post(
                f"{self.base_url}/api/v1/channels",
                json={"client_id": client_id, "bot_id": bot_id},
                headers=self._headers(),
                timeout=5.0,
            )
            r.raise_for_status()
            return r.json()
        except Exception:
            logger.exception("Failed to ensure channel for %s", client_id)
            return None

    async def submit_chat(
        self,
        *,
        message: str,
        bot_id: str,
        client_id: str,
        session_id: str | None = None,
        dispatch_type: str = "wyoming",
        dispatch_config: dict | None = None,
        msg_metadata: dict | None = None,
    ) -> dict:
        """POST /chat -> 202 {session_id, channel_id, turn_id}."""
        payload: dict = {
            "message": message,
            "bot_id": bot_id,
            "client_id": client_id,
            "dispatch_type": dispatch_type,
        }
        if session_id:
            payload["session_id"] = session_id
        if dispatch_config:
            payload["dispatch_config"] = dispatch_config
        if msg_metadata:
            payload["msg_metadata"] = msg_metadata
        r = await self._http.post(
            f"{self.base_url}/chat",
            json=payload,
            headers=self._headers(),
            timeout=120,
        )
        r.raise_for_status()
        return r.json()

    async def stream_response(self, stream_id: str) -> str:
        """Subscribe to SSE /stream/{stream_id} and return final response text.

        Consumes the full SSE stream, collecting text tokens until the
        turn ends. Returns the concatenated response.
        """
        final_text = ""
        url = f"{self.base_url}/stream/{stream_id}"
        try:
            async with self._http.stream(
                "GET", url, headers=self._headers(), timeout=300.0,
            ) as resp:
                resp.raise_for_status()
                buffer = ""
                async for chunk in resp.aiter_text():
                    buffer += chunk
                    while "\n\n" in buffer:
                        event_str, buffer = buffer.split("\n\n", 1)
                        final_text = self._parse_sse_event(event_str, final_text)
        except Exception:
            logger.exception("Error streaming response for %s", stream_id)
        return final_text

    def _parse_sse_event(self, event_str: str, accumulated: str) -> str:
        """Parse a single SSE event and return updated accumulated text."""
        import json

        data_line = ""
        for line in event_str.split("\n"):
            if line.startswith("data: "):
                data_line = line[6:]

        if not data_line:
            return accumulated

        try:
            data = json.loads(data_line)
        except json.JSONDecodeError:
            return accumulated

        event_type = data.get("type", "")

        if event_type == "token":
            accumulated += data.get("token", "")
        elif event_type == "final_response":
            return data.get("text", accumulated)
        elif event_type == "message":
            text = data.get("text", "")
            if text:
                return text

        return accumulated

    async def wait_for_response(
        self,
        session_id: str,
        *,
        after: "datetime | None" = None,
        timeout: float = 120,
    ) -> str:
        """Poll session messages until an assistant response appears.

        If ``after`` is provided, only accepts messages created after that
        timestamp — prevents returning stale responses from previous turns.
        """
        import asyncio
        from datetime import datetime

        deadline = asyncio.get_event_loop().time() + timeout
        url = f"{self.base_url}/sessions/{session_id}/messages?limit=10"
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(1)
            try:
                r = await self._http.get(url, headers=self._headers(), timeout=10.0)
                r.raise_for_status()
                data = r.json()
                messages = data.get("messages", data) if isinstance(data, dict) else data
                # Walk newest-first looking for an assistant response
                for msg in reversed(messages):
                    if msg.get("role") != "assistant":
                        continue
                    content = msg.get("content", "")
                    if not content or content == "[Cancelled by user]":
                        continue
                    if after:
                        created = msg.get("created_at", "")
                        if created:
                            msg_time = datetime.fromisoformat(created)
                            if msg_time.tzinfo is None:
                                from datetime import timezone
                                msg_time = msg_time.replace(tzinfo=timezone.utc)
                            if msg_time < after:
                                continue
                    logger.info("Got response: %s", content[:100])
                    return content
            except Exception:
                logger.debug("Poll failed, retrying", exc_info=True)
        logger.warning("Timed out waiting for response in session %s", session_id)
        return ""

    async def report_device_status(self, devices: list[dict]) -> None:
        """POST device status to the admin API."""
        try:
            r = await self._http.post(
                f"{self.base_url}/api/v1/admin/integrations/wyoming/device-status",
                json={"devices": devices},
                headers=self._headers(),
                timeout=5.0,
            )
            r.raise_for_status()
        except Exception:
            logger.debug("Failed to report device status", exc_info=True)

    async def get_channel_config(self) -> dict:
        """GET /integrations/wyoming/config -- fetch device->channel mappings."""
        try:
            r = await self._http.get(
                f"{self.base_url}/integrations/wyoming/config",
                headers=self._headers(),
                timeout=5.0,
            )
            r.raise_for_status()
            return r.json()
        except Exception:
            logger.exception("Failed to fetch Wyoming config")
            return {}

    async def close(self):
        await self._http.aclose()
