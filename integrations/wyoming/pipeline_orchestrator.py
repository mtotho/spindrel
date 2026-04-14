"""Wyoming pipeline orchestrator.

Runs as a standalone process (spawned by the integration process manager).
Connects to registered Wyoming satellites as a CLIENT, orchestrates the
full voice pipeline per interaction:

  wake word detected → receive audio → Whisper STT → POST /chat →
  wait for response → Piper TTS → send audio back to satellite

Each satellite gets a persistent TCP connection. The orchestrator manages
reconnection on drop and periodically refreshes config to pick up new
satellite bindings.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.asr import Transcript
from wyoming.client import AsyncClient
from wyoming.event import Event
from wyoming.info import Describe, Info
from wyoming.pipeline import RunPipeline, PipelineStage
from wyoming.satellite import RunSatellite, StreamingStarted, StreamingStopped
from wyoming.tts import Synthesize

from integrations.wyoming.agent_client import AgentClient
from integrations.wyoming.pipeline import transcribe_audio, synthesize_speech, AudioBuffer
from integrations.wyoming.esphome_client import ESPHomeVoiceConnection, ESPHomeConnectionConfig
from integrations.wyoming.esphome_device_registry import ESPHomeDeviceRegistry

logger = logging.getLogger(__name__)

RECONNECT_DELAY_INITIAL = 5.0
RECONNECT_DELAY_MAX = 300.0  # 5 minutes
CONFIG_REFRESH_INTERVAL = 30.0


class SatelliteConnection:
    """Manages a persistent connection to a single Wyoming satellite."""

    def __init__(
        self,
        *,
        device_id: str,
        satellite_uri: str,
        bot_id: str,
        client_id: str,
        channel_id: str,
        whisper_uri: str,
        piper_uri: str,
        voice: str,
        agent: AgentClient,
    ):
        self.device_id = device_id
        self.satellite_uri = satellite_uri
        self.bot_id = bot_id
        self.client_id = client_id
        self.channel_id = channel_id
        self.whisper_uri = whisper_uri
        self.piper_uri = piper_uri
        self.voice = voice
        self.agent = agent
        self._client: AsyncClient | None = None
        self._running = False
        self._task: asyncio.Task | None = None
        self._connected = False
        self._last_error: str | None = None
        self._last_activity: str | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def status_info(self) -> dict:
        """Return device status dict for reporting."""
        if self._connected:
            status = "connected"
        elif self._running:
            status = "connecting"
        else:
            status = "disconnected"
        return {
            "device_id": self.device_id,
            "label": self.device_id,
            "protocol": "wyoming",
            "uri": self.satellite_uri,
            "status": "error" if self._last_error else status,
            "detail": self._last_error,
            "last_activity": self._last_activity,
        }

    async def start(self):
        """Start the satellite connection loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        """Stop the satellite connection."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):
        """Main loop: connect, run pipeline, reconnect on failure."""
        delay = RECONNECT_DELAY_INITIAL
        consecutive_failures = 0
        while self._running:
            try:
                await self._connect_and_run()
                # Successful connection resets backoff
                delay = RECONNECT_DELAY_INITIAL
                consecutive_failures = 0
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._connected = False
                self._last_error = str(exc)
                consecutive_failures += 1
                if consecutive_failures <= 1:
                    logger.warning("Satellite %s connection error: %s", self.device_id, exc)
                else:
                    logger.debug("Satellite %s still unreachable (%d attempts): %s", self.device_id, consecutive_failures, exc)

            if self._running:
                if consecutive_failures <= 1:
                    logger.info("Reconnecting to %s in %.0fs...", self.device_id, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, RECONNECT_DELAY_MAX)

    async def _connect_and_run(self):
        """Connect to satellite, send RunSatellite, process events."""
        from datetime import datetime, timezone

        logger.info("Connecting to satellite %s at %s", self.device_id, self.satellite_uri)

        self._client = AsyncClient.from_uri(self.satellite_uri)
        await self._client.connect()
        self._connected = True
        self._last_error = None
        self._last_activity = datetime.now(timezone.utc).isoformat()
        logger.info("Connected to satellite %s", self.device_id)

        # Service discovery
        await self._client.write_event(Describe().event())
        info_event = await asyncio.wait_for(self._client.read_event(), timeout=10.0)
        if info_event and Info.is_type(info_event.type):
            info = Info.from_event(info_event)
            # info.satellite may be a single Satellite object or a list
            sat = info.satellite
            if sat:
                name = sat.name if hasattr(sat, "name") else str(sat)
            else:
                name = "unknown"
            logger.info("Satellite %s identified as: %s", self.device_id, name)

        # Tell satellite to start
        await self._client.write_event(RunSatellite().event())
        logger.info("Satellite %s started, waiting for voice activity...", self.device_id)

        # Main event loop
        while self._running:
            event = await self._client.read_event()
            if event is None:
                self._connected = False
                logger.warning("Satellite %s disconnected", self.device_id)
                break

            if RunPipeline.is_type(event.type):
                pipeline = RunPipeline.from_event(event)
                self._last_activity = datetime.now(timezone.utc).isoformat()
                logger.info(
                    "Pipeline requested: %s → %s",
                    pipeline.start_stage.value, pipeline.end_stage.value,
                )
                await self._handle_pipeline(pipeline)

            elif StreamingStarted.is_type(event.type):
                logger.debug("Streaming started from %s", self.device_id)

            elif StreamingStopped.is_type(event.type):
                logger.debug("Streaming stopped from %s", self.device_id)

            else:
                logger.debug("Event from %s: %s", self.device_id, event.type)

    async def _handle_pipeline(self, pipeline: RunPipeline):
        """Handle a full voice interaction pipeline."""
        import struct

        assert self._client is not None

        # Collect audio from satellite until AudioStop or silence detected.
        # Many satellites (especially wyoming-satellite without --vad) stream
        # audio indefinitely — we need server-side silence detection to know
        # when the user stopped speaking.
        audio_buffer = AudioBuffer()
        collecting = False
        # Collect audio for a fixed window after wake word.  Energy-based
        # silence detection is unreliable on noisy hat mics (WM8960 etc.)
        # where the SNR is too low.  Instead we collect for up to
        # COLLECT_SECONDS and send whatever we got to Whisper — it handles
        # noisy audio well and ignores silence.
        COLLECT_SECONDS = 5
        collect_deadline = asyncio.get_event_loop().time() + COLLECT_SECONDS

        while True:
            remaining = collect_deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.info("Collection window closed (%ds)", COLLECT_SECONDS)
                break

            try:
                event = await asyncio.wait_for(
                    self._client.read_event(), timeout=min(remaining, 5.0),
                )
            except asyncio.TimeoutError:
                logger.info("Collection timeout, proceeding with audio")
                break

            if event is None:
                logger.warning("Connection lost during audio collection")
                return

            if AudioStart.is_type(event.type):
                audio_start = AudioStart.from_event(event)
                audio_buffer = AudioBuffer(
                    rate=audio_start.rate,
                    width=audio_start.width,
                    channels=audio_start.channels,
                )
                collecting = True

            elif AudioChunk.is_type(event.type):
                if not collecting:
                    collecting = True
                chunk = AudioChunk.from_event(event)
                audio_buffer.add_chunk(chunk.audio)

            elif AudioStop.is_type(event.type):
                break

            elif StreamingStopped.is_type(event.type):
                break

        duration = audio_buffer.duration_seconds
        logger.info("Collected %.1fs of audio from %s", duration, self.device_id)

        if duration < 0.3:
            logger.info("Audio too short, ignoring")
            await self._reset_satellite()
            return

        # Step 1: STT — transcribe via Whisper
        transcript = await transcribe_audio(self.whisper_uri, audio_buffer)
        if not transcript or not transcript.strip():
            logger.info("Empty transcript, skipping")
            await self._reset_satellite()
            return

        logger.info("Transcript from %s: %r", self.device_id, transcript)

        # NOTE: Do NOT send Transcript here — it causes the satellite to
        # resume wake-word listening immediately.  We send it AFTER TTS
        # playback so the satellite stays in playback mode and doesn't
        # false-trigger on its own speaker output.

        # Step 2: Dispatch to Spindrel channel
        try:
            result = await self.agent.submit_chat(
                message=transcript,
                bot_id=self.bot_id,
                client_id=self.client_id,
                dispatch_type="wyoming",
                dispatch_config={
                    "type": "wyoming",
                    "device_id": self.device_id,
                },
                msg_metadata={
                    "source": "wyoming",
                    "sender_type": "human",
                    "sender_id": f"wyoming:{self.device_id}",
                    "sender_display_name": self.device_id,
                },
            )
        except Exception:
            logger.exception("Failed to submit chat for %s", self.device_id)
            await self._speak_error("Sorry, I couldn't process that.")
            await self._reset_satellite()
            return

        # Step 3: Wait for bot response
        stream_id = result.get("stream_id")
        session_id = result.get("session_id")
        if stream_id:
            response_text = await self.agent.stream_response(stream_id)
        elif session_id:
            from datetime import datetime, timezone
            response_text = await self.agent.wait_for_response(
                session_id, after=datetime.now(timezone.utc),
            )
        else:
            logger.error("No stream_id or session_id in chat response: %s", result)
            await self._speak_error("Sorry, something went wrong.")
            await self._reset_satellite()
            return

        if not response_text:
            logger.warning("Empty response from agent")
            await self._speak_error("I don't have a response for that.")
            await self._reset_satellite()
            return

        logger.info("Response for %s: %r", self.device_id, response_text[:200])

        # Step 4: TTS — synthesize and send audio to satellite
        if pipeline.end_stage == PipelineStage.TTS:
            await self._speak(response_text)

        # Send transcript AFTER TTS so the satellite stays in playback mode
        # during speech and only resumes wake-word listening once done.
        await self._client.write_event(Transcript(text=transcript).event())

    async def _reset_satellite(self):
        """Send empty transcript so satellite returns to wake-word listening."""
        if self._client:
            await self._client.write_event(Transcript(text="").event())
            logger.debug("Sent reset to satellite")

    async def _speak(self, text: str):
        """Synthesize text and send audio to the satellite."""
        assert self._client is not None
        events = await synthesize_speech(self.piper_uri, text, self.voice)
        for event in events:
            await self._client.write_event(event)

    async def _speak_error(self, message: str):
        """Speak an error message to the satellite."""
        try:
            await self._speak(message)
        except Exception:
            logger.debug("Could not speak error to satellite")


async def main():
    """Entry point for the pipeline orchestrator process."""
    parser = argparse.ArgumentParser(description="Spindrel Wyoming Pipeline Orchestrator")
    parser.add_argument("--whisper-uri", default=None, help="Whisper STT URI")
    parser.add_argument("--piper-uri", default=None, help="Piper TTS URI")
    parser.add_argument("--voice", default=None, help="Default voice model")
    args = parser.parse_args()

    from integrations.wyoming.config import (
        WHISPER_URI, PIPER_URI, DEFAULT_VOICE, API_KEY, AGENT_BASE_URL,
        ESPHOME_API_PASSWORD,
    )

    whisper_uri = args.whisper_uri or WHISPER_URI
    piper_uri = args.piper_uri or PIPER_URI
    default_voice = args.voice or DEFAULT_VOICE

    agent = AgentClient(AGENT_BASE_URL, API_KEY)

    # Track active connections — Wyoming satellites and ESPHome devices
    wyoming_conns: dict[str, SatelliteConnection] = {}
    esphome_conns: dict[str, ESPHomeVoiceConnection] = {}
    esphome_registry = ESPHomeDeviceRegistry()

    async def refresh_and_manage():
        """Periodically refresh config and manage device connections."""
        while True:
            try:
                config = await agent.get_channel_config()
                devices = config.get("devices", {})

                # Split devices by protocol
                wyoming_devices: dict[str, dict] = {}
                esphome_devices: dict[str, dict] = {}
                for device_id, device in devices.items():
                    protocol = device.get("protocol", "wyoming")
                    if protocol == "esphome":
                        esphome_devices[device_id] = device
                    else:
                        wyoming_devices[device_id] = device

                # --- Wyoming satellite connections ---
                for device_id, device in wyoming_devices.items():
                    satellite_uri = device.get("satellite_uri")
                    if not satellite_uri:
                        continue
                    bot_id = device.get("bot_id")
                    if not bot_id:
                        continue
                    # Detect config changes (binding moved to different channel/bot)
                    existing = wyoming_conns.get(device_id)
                    if existing and existing.is_running:
                        if existing.bot_id == bot_id and existing.satellite_uri == satellite_uri:
                            continue
                        logger.info("Config changed for %s (bot/uri), reconnecting", device_id)
                        await existing.stop()
                        del wyoming_conns[device_id]

                    conn = SatelliteConnection(
                        device_id=device_id,
                        satellite_uri=satellite_uri,
                        bot_id=bot_id,
                        client_id=f"wyoming:{device_id}",
                        channel_id=device.get("channel_id", ""),
                        whisper_uri=whisper_uri,
                        piper_uri=piper_uri,
                        voice=device.get("voice") or default_voice,
                        agent=agent,
                    )
                    wyoming_conns[device_id] = conn
                    await conn.start()
                    logger.info("Started Wyoming connection to %s at %s", device_id, satellite_uri)

                for device_id in list(wyoming_conns.keys()):
                    if device_id not in wyoming_devices:
                        await wyoming_conns[device_id].stop()
                        del wyoming_conns[device_id]
                        logger.info("Stopped Wyoming connection to %s", device_id)

                # --- ESPHome device connections ---
                esphome_registry.update(esphome_devices)

                for device_id, device in esphome_devices.items():
                    satellite_uri = device.get("satellite_uri")
                    if not satellite_uri:
                        continue
                    bot_id = device.get("bot_id")
                    if not bot_id:
                        continue
                    # Detect config changes (binding moved to different channel/bot)
                    if device_id in esphome_conns:
                        old_cfg = esphome_conns[device_id]._config.device_config
                        if old_cfg.bot_id == bot_id and old_cfg.channel_id == device.get("channel_id", ""):
                            continue
                        logger.info("Config changed for ESPHome %s (bot/channel), reconnecting", device_id)
                        await esphome_conns[device_id].stop()
                        del esphome_conns[device_id]

                    host, port = _parse_esphome_uri(satellite_uri)
                    device_name = device.get("esphome_device_name") or device_id
                    device_config = esphome_registry.get(device_name)
                    if not device_config:
                        continue

                    econn = ESPHomeVoiceConnection(ESPHomeConnectionConfig(
                        device_name=device_name,
                        host=host,
                        port=port,
                        password=ESPHOME_API_PASSWORD,
                        device_config=device_config,
                        whisper_uri=whisper_uri,
                        piper_uri=piper_uri,
                        default_voice=default_voice,
                        agent=agent,
                    ))
                    esphome_conns[device_id] = econn
                    await econn.start()
                    logger.info("Started ESPHome connection to %s at %s:%d", device_name, host, port)

                for device_id in list(esphome_conns.keys()):
                    if device_id not in esphome_devices:
                        await esphome_conns[device_id].stop()
                        del esphome_conns[device_id]
                        logger.info("Stopped ESPHome connection to %s", device_id)

                # --- Report device status ---
                status_devices = []
                for conn in wyoming_conns.values():
                    status_devices.append(conn.status_info)
                for conn in esphome_conns.values():
                    status_devices.append(conn.status_info)
                if status_devices:
                    await agent.report_device_status(status_devices)

            except Exception:
                logger.debug("Config refresh failed", exc_info=True)

            await asyncio.sleep(CONFIG_REFRESH_INTERVAL)

    logger.info("Starting Wyoming pipeline orchestrator")
    logger.info("  Whisper: %s", whisper_uri)
    logger.info("  Piper:   %s", piper_uri)
    logger.info("  Voice:   %s", default_voice)

    try:
        await refresh_and_manage()
    except asyncio.CancelledError:
        pass
    finally:
        for conn in wyoming_conns.values():
            await conn.stop()
        for conn in esphome_conns.values():
            await conn.stop()
        await agent.close()


def _parse_uri(uri: str) -> tuple[str, int]:
    """Parse a tcp://host:port URI into (host, port)."""
    uri = uri.removeprefix("tcp://")
    if ":" in uri:
        host, port_str = uri.rsplit(":", 1)
        return host, int(port_str)
    return uri, 10700


def _parse_esphome_uri(uri: str) -> tuple[str, int]:
    """Parse a tcp://host:port URI for ESPHome devices (default port 6053)."""
    uri = uri.removeprefix("tcp://")
    if ":" in uri:
        host, port_str = uri.rsplit(":", 1)
        return host, int(port_str)
    return uri, 6053


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    asyncio.run(main())
