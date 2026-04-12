"""Wyoming voice assistant server.

Runs as a standalone process (spawned by the integration process manager).
Listens for Wyoming satellite connections on TCP, handles the full voice
pipeline per connection:

  satellite audio -> Whisper STT -> Spindrel dispatch -> bot response -> Piper TTS -> satellite

Each satellite connection is handled by a SpindrelHandler instance.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from typing import Any

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.info import Describe, Info, AsrProgram, AsrModel, TtsProgram, TtsModel, HandleProgram, HandleModel
from wyoming.server import AsyncEventHandler, AsyncServer

from integrations.wyoming.agent_client import AgentClient
from integrations.wyoming.pipeline import AudioBuffer, run_voice_pipeline

logger = logging.getLogger(__name__)

# Active connections tracked for potential future use (device registry, etc.)
_active_connections: dict[str, "SpindrelHandler"] = {}


class SpindrelHandler(AsyncEventHandler):
    """Handles a single Wyoming satellite connection.

    Collects audio after wake word detection, runs the full voice pipeline,
    and sends synthesized audio back to the satellite.
    """

    def __init__(
        self,
        *args: Any,
        agent: AgentClient,
        whisper_uri: str,
        piper_uri: str,
        device_config: dict,
        default_voice: str,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        self.agent = agent
        self.whisper_uri = whisper_uri
        self.piper_uri = piper_uri
        self.device_config = device_config
        self.default_voice = default_voice
        self.connection_id = str(uuid.uuid4())
        self.audio_buffer = AudioBuffer()
        self.is_recording = False

        _active_connections[self.connection_id] = self
        logger.info("New satellite connection: %s", self.connection_id)

    async def handle_event(self, event: Event) -> bool:
        """Process a Wyoming event from the satellite."""

        if Describe.is_type(event.type):
            await self._handle_describe()
            return True

        if AudioStart.is_type(event.type):
            return await self._handle_audio_start(event)

        if AudioChunk.is_type(event.type):
            return await self._handle_audio_chunk(event)

        if AudioStop.is_type(event.type):
            return await self._handle_audio_stop()

        logger.debug("Unhandled event type: %s", event.type)
        return True

    async def _handle_describe(self):
        """Respond to a Describe request with our service info."""
        info = Info(
            handle=[
                HandleProgram(
                    name="spindrel",
                    description="Spindrel voice assistant",
                    installed=True,
                    models=[
                        HandleModel(
                            name="default",
                            description="Default conversation handler",
                            installed=True,
                        )
                    ],
                )
            ],
        )
        await self.write_event(info.event())

    async def _handle_audio_start(self, event: Event) -> bool:
        """Start recording audio from the satellite."""
        audio_start = AudioStart.from_event(event)
        self.audio_buffer = AudioBuffer(
            rate=audio_start.rate,
            width=audio_start.width,
            channels=audio_start.channels,
        )
        self.is_recording = True
        logger.debug("Recording started (rate=%d, width=%d, channels=%d)",
                      audio_start.rate, audio_start.width, audio_start.channels)
        return True

    async def _handle_audio_chunk(self, event: Event) -> bool:
        """Buffer an audio chunk."""
        if not self.is_recording:
            return True
        chunk = AudioChunk.from_event(event)
        self.audio_buffer.add_chunk(chunk.audio)
        return True

    async def _handle_audio_stop(self) -> bool:
        """Recording finished -- run the full voice pipeline."""
        self.is_recording = False
        duration = self.audio_buffer.duration_seconds
        logger.info("Recording stopped (%.1fs of audio)", duration)

        if duration < 0.3:
            logger.info("Audio too short (%.1fs), ignoring", duration)
            return True

        # Resolve which bot/channel this device should dispatch to
        bot_id, client_id, session_id, voice = self._resolve_channel()
        if not bot_id or not client_id:
            logger.error("No channel binding for this device")
            return True

        # Run the full pipeline
        response_events = await run_voice_pipeline(
            audio_buffer=self.audio_buffer,
            whisper_uri=self.whisper_uri,
            piper_uri=self.piper_uri,
            agent=self.agent,
            bot_id=bot_id,
            client_id=client_id,
            session_id=session_id,
            voice=voice or self.default_voice,
        )

        # Send audio back to satellite
        for evt in response_events:
            await self.write_event(evt)

        return True

    def _resolve_channel(self) -> tuple[str | None, str | None, str | None, str | None]:
        """Resolve device -> (bot_id, client_id, session_id, voice).

        Uses the device_config mapping fetched from the agent server.
        Falls back to the first configured device if no specific match.
        """
        devices = self.device_config.get("devices", {})

        # Try to match by connection info (future: use satellite name/id)
        # For now, use the default/first device
        if not devices:
            logger.warning("No devices configured")
            return None, None, None, None

        # Use the first device as default (single-device MVP)
        device_id = next(iter(devices))
        device = devices[device_id]
        bot_id = device.get("bot_id")
        client_id = f"wyoming:{device_id}"
        session_id = device.get("session_id")
        voice = device.get("voice")

        return bot_id, client_id, session_id, voice

    async def disconnect(self) -> None:
        """Clean up on satellite disconnect."""
        _active_connections.pop(self.connection_id, None)
        logger.info("Satellite disconnected: %s", self.connection_id)


async def main():
    """Entry point for the Wyoming server process."""
    parser = argparse.ArgumentParser(description="Spindrel Wyoming Voice Server")
    parser.add_argument("--host", default=None, help="Listen host")
    parser.add_argument("--port", type=int, default=None, help="Listen port")
    parser.add_argument("--whisper-uri", default=None, help="Whisper STT URI")
    parser.add_argument("--piper-uri", default=None, help="Piper TTS URI")
    parser.add_argument("--voice", default=None, help="Default voice model")
    args = parser.parse_args()

    # Import config (uses DB settings or env vars)
    from integrations.wyoming.config import (
        LISTEN_HOST, LISTEN_PORT, WHISPER_URI, PIPER_URI,
        DEFAULT_VOICE, API_KEY, AGENT_BASE_URL,
    )

    host = args.host or LISTEN_HOST
    port = args.port or LISTEN_PORT
    whisper_uri = args.whisper_uri or WHISPER_URI
    piper_uri = args.piper_uri or PIPER_URI
    default_voice = args.voice or DEFAULT_VOICE

    agent = AgentClient(AGENT_BASE_URL, API_KEY)

    # Fetch device config from agent server
    device_config = await agent.get_channel_config()
    logger.info("Loaded device config: %d devices", len(device_config.get("devices", {})))

    # Periodically refresh device config
    async def refresh_config():
        nonlocal device_config
        while True:
            await asyncio.sleep(30)
            try:
                device_config = await agent.get_channel_config()
            except Exception:
                logger.debug("Config refresh failed, keeping existing")

    refresh_task = asyncio.create_task(refresh_config())

    uri = f"tcp://{host}:{port}"
    logger.info("Starting Wyoming server on %s", uri)
    logger.info("  Whisper: %s", whisper_uri)
    logger.info("  Piper:   %s", piper_uri)
    logger.info("  Voice:   %s", default_voice)

    server = AsyncServer.from_uri(uri)

    try:
        await server.run(
            partial_handler=lambda *a, **kw: SpindrelHandler(
                *a,
                agent=agent,
                whisper_uri=whisper_uri,
                piper_uri=piper_uri,
                device_config=device_config,
                default_voice=default_voice,
                **kw,
            ),
        )
    finally:
        refresh_task.cancel()
        await agent.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    asyncio.run(main())
