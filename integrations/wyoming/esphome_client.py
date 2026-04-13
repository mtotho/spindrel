"""ESPHome voice client — connects to ESP32 devices running ESPHome firmware.

Uses aioesphomeapi to connect to devices (like the M5Stack ATOM Echo),
subscribe for voice assistant events, and run the STT → Spindrel → TTS
pipeline using the same Whisper/Piper services as Wyoming satellites.

The ESPHome device is the TCP server (listens on port 6053 by default).
Spindrel connects OUT to the device — same direction as Wyoming satellites.

Audio uses UDP mode (not API/protobuf mode) — the device streams mic audio
to us via UDP, and we send TTS audio back the same way. This avoids an
ESPHome 2026.3.3 bug where API audio mode leaves `this->socket_` null,
causing STREAMING_RESPONSE to never feed audio to the speaker.
"""
from __future__ import annotations

import array
import asyncio
import logging
import socket
from dataclasses import dataclass

import re

from aioesphomeapi import APIClient, LogLevel, VoiceAssistantEventType

from integrations.wyoming.agent_client import AgentClient
from integrations.wyoming.esphome_device_registry import ESPHomeDeviceConfig
from integrations.wyoming.pipeline import AudioBuffer, transcribe_audio, synthesize_speech

from wyoming.audio import AudioChunk, AudioStart

logger = logging.getLogger(__name__)

# Piper default output rate vs what the ATOM Echo expects
_PIPER_SAMPLE_RATE = 22050
_DEVICE_SAMPLE_RATE = 16000

# UDP audio chunk size — matches ESPHome's expectation
_UDP_AUDIO_CHUNK_BYTES = 1024  # 512 samples * 2 bytes


@dataclass
class ESPHomeConnectionConfig:
    """Config for one ESPHome device connection."""

    device_name: str
    host: str
    port: int
    password: str
    device_config: ESPHomeDeviceConfig
    whisper_uri: str
    piper_uri: str
    default_voice: str | None
    agent: AgentClient


class _UDPAudioServer(asyncio.DatagramProtocol):
    """Minimal UDP server for receiving mic audio and sending TTS audio.

    ESPHome sends mic audio as raw 16-bit PCM UDP packets. We learn the
    device's address from the first incoming packet and use it to send
    TTS audio back.
    """

    def __init__(self) -> None:
        self.transport: asyncio.DatagramTransport | None = None
        self.device_addr: tuple[str, int] | None = None
        self.audio_buffer: AudioBuffer | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        # Learn device address from first mic packet
        if self.device_addr is None:
            self.device_addr = addr
            logger.debug("UDP: learned device address %s:%d", addr[0], addr[1])
        if self.audio_buffer is not None:
            self.audio_buffer.add_chunk(data)

    def send_audio(self, data: bytes) -> None:
        """Send TTS audio chunk to the device via UDP."""
        if self.transport and self.device_addr:
            self.transport.sendto(data, self.device_addr)

    def close(self) -> None:
        if self.transport:
            self.transport.close()
            self.transport = None


class ESPHomeVoiceConnection:
    """Manages a persistent connection to one ESPHome voice device.

    Mirrors the SatelliteConnection pattern from pipeline_orchestrator.py
    but uses aioesphomeapi instead of Wyoming protocol.
    """

    def __init__(self, config: ESPHomeConnectionConfig) -> None:
        self._config = config
        self._client: APIClient | None = None
        self._task: asyncio.Task | None = None
        self._audio_buffer: AudioBuffer | None = None
        self._pipeline_task: asyncio.Task | None = None
        self._voice_active = False
        self._udp_server: _UDPAudioServer | None = None
        self._udp_port: int = 0
        self._friendly_name: str = config.device_name
        self._connected = False
        self._last_error: str | None = None
        self._last_activity: str | None = None

    @property
    def status_info(self) -> dict:
        """Return device status dict for reporting."""
        cfg = self._config
        if self._connected:
            status = "connected"
        elif self._task and not self._task.done():
            status = "connecting"
        else:
            status = "disconnected"
        return {
            "device_id": cfg.device_name,
            "label": self._friendly_name,
            "protocol": "esphome",
            "uri": f"tcp://{cfg.host}:{cfg.port}",
            "status": "error" if self._last_error else status,
            "detail": self._last_error,
            "last_activity": self._last_activity,
        }

    async def start(self) -> None:
        """Start the connection loop (auto-reconnects)."""
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop the connection and cancel the loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._disconnect()

    async def _disconnect(self) -> None:
        if self._udp_server:
            self._udp_server.close()
            self._udp_server = None
            self._udp_port = 0
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None

    async def _run_loop(self) -> None:
        """Reconnect loop — keeps trying to connect to the device."""
        cfg = self._config
        delay = 5.0
        max_delay = 300.0
        consecutive_failures = 0
        while True:
            try:
                logger.info(
                    "Connecting to ESPHome device %s at %s:%d",
                    cfg.device_name, cfg.host, cfg.port,
                )
                await self._connect_and_run()
                delay = 5.0
                consecutive_failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._connected = False
                self._last_error = str(exc)
                consecutive_failures += 1
                if consecutive_failures <= 1:
                    logger.warning(
                        "ESPHome connection to %s failed: %s",
                        cfg.device_name, exc,
                    )
                else:
                    logger.debug(
                        "ESPHome %s still unreachable (%d attempts): %s",
                        cfg.device_name, consecutive_failures, exc,
                    )
            await self._disconnect()
            if consecutive_failures <= 1:
                logger.info("Reconnecting to %s in %.0fs...", cfg.device_name, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)

    async def _connect_and_run(self) -> None:
        """Connect to the device, subscribe for voice, and block until disconnect."""
        cfg = self._config
        self._client = APIClient(
            address=cfg.host,
            port=cfg.port,
            password=cfg.password or "",
            client_info="Spindrel",
        )
        await self._client.connect(login=True)
        device_info = await self._client.device_info()
        self._friendly_name = device_info.friendly_name or device_info.name or cfg.device_name
        self._connected = True
        self._last_error = None
        from datetime import datetime, timezone
        self._last_activity = datetime.now(timezone.utc).isoformat()
        logger.info(
            "Connected to ESPHome device: %s (model=%s)",
            device_info.name, device_info.model,
        )

        # Forward device logs so we can see firmware-side voice/speaker activity
        _ansi_re = re.compile(r"\x1b\[[0-9;]*m")
        dev_name = cfg.device_name

        def _on_device_log(msg: object) -> None:
            text = msg.message  # type: ignore[attr-defined]
            if isinstance(text, bytes):
                text = text.decode("utf-8", errors="replace")
            text = _ansi_re.sub("", text).strip()
            if text:
                logger.info("[%s firmware] %s", dev_name, text)

        unsub_logs = self._client.subscribe_logs(
            _on_device_log, log_level=LogLevel.LOG_LEVEL_VERY_VERBOSE,
        )

        # Start a UDP server for audio. OS picks a free port.
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            _UDPAudioServer,
            local_addr=("0.0.0.0", 0),
            family=socket.AF_INET,
        )
        self._udp_server = protocol  # type: ignore[assignment]
        self._udp_port = transport.get_extra_info("sockname")[1]
        logger.info(
            "UDP audio server listening on port %d for %s",
            self._udp_port, cfg.device_name,
        )

        # Subscribe for voice assistant events.
        # handle_start is called when the device detects a wake word.
        # handle_stop is called when audio ends or device aborts.
        # No handle_audio — we use UDP mode, not API audio mode.
        unsub_voice = self._client.subscribe_voice_assistant(
            handle_start=self._handle_start,
            handle_stop=self._handle_stop,
        )

        try:
            # Block until disconnected. aioesphomeapi handles pings internally.
            while self._client is not None:
                await asyncio.sleep(1)
        finally:
            unsub_voice()
            unsub_logs()
            if self._udp_server:
                self._udp_server.close()
                self._udp_server = None
                self._udp_port = 0

    async def _handle_start(
        self,
        conversation_id: str,
        flags: int,
        audio_settings: object,
        wake_word_phrase: str | None,
    ) -> int | None:
        """Called when the device wants to start a pipeline.

        Returns UDP port for audio streaming. The device sends mic audio
        to this port and reads TTS audio from the same UDP socket.
        """
        logger.info(
            "Voice pipeline started on %s (conv=%s, flags=%d, wake=%s, audio=%s)",
            self._config.device_name,
            conversation_id, flags, wake_word_phrase, audio_settings,
        )
        self._audio_buffer = AudioBuffer(rate=_DEVICE_SAMPLE_RATE, width=2, channels=1)
        self._voice_active = True

        # Wire the UDP server's buffer so incoming mic packets accumulate
        if self._udp_server:
            self._udp_server.audio_buffer = self._audio_buffer
            # Reset device address — it may have changed between runs
            self._udp_server.device_addr = None

        # Return the UDP port — device will stream mic audio here
        return self._udp_port

    async def _handle_stop(self, abort: bool) -> None:
        """Called when the device stops sending audio.

        For push-to-talk, both abort=True (button release sends
        VoiceAssistantRequest start=False) and abort=False (audio
        end=True) mean "process the collected audio". We only skip
        if there's no audio buffer or it's too short.

        Critical: the button release also triggers request_stop() on the
        device which sets desired_state_ = IDLE. We must send STT_VAD_END
        immediately so the device transitions to AWAITING_RESPONSE instead.
        Without this, the device goes IDLE and the speaker gets killed by
        the IDLE loop handler before TTS audio can play.
        """
        if not self._voice_active or not self._audio_buffer:
            logger.debug("Stop received on %s but no active session", self._config.device_name)
            return

        self._voice_active = False
        buffer = self._audio_buffer
        self._audio_buffer = None

        # Detach UDP buffer so late packets don't pollute
        if self._udp_server:
            self._udp_server.audio_buffer = None

        if buffer.duration_seconds < 0.3:
            logger.info("Audio too short (%.1fs) from %s, skipping", buffer.duration_seconds, self._config.device_name)
            # Do NOT send STT_VAD_END here — it transitions the device to
            # AWAITING_RESPONSE, and a subsequent RUN_END arrives during the
            # transition (STOP_MICROPHONE) where it's ignored, leaving the
            # device stuck in AWAITING_RESPONSE forever.
            # Let the device return to IDLE naturally via request_stop().
            return

        # Send STT_VAD_END — this overrides the device's desired_state_
        # from IDLE to AWAITING_RESPONSE, preventing the IDLE loop from
        # killing the speaker before TTS audio plays.
        if self._client:
            self._client.send_voice_assistant_event(
                VoiceAssistantEventType.VOICE_ASSISTANT_STT_VAD_END, None
            )

        logger.info(
            "Processing %.1fs of audio from %s (abort=%s)",
            buffer.duration_seconds, self._config.device_name, abort,
        )

        # Run pipeline in a separate task so we don't block the connection
        self._pipeline_task = asyncio.create_task(
            self._run_voice_pipeline(buffer)
        )

    async def _run_voice_pipeline(self, audio_buffer: AudioBuffer) -> None:
        """Run the full STT → Spindrel → TTS pipeline."""
        cfg = self._config
        dc = cfg.device_config
        client = self._client
        if not client:
            return

        try:
            # RUN_START signals the pipeline is active (matches HA behavior)
            client.send_voice_assistant_event(
                VoiceAssistantEventType.VOICE_ASSISTANT_RUN_START, None
            )

            # --- STT ---
            client.send_voice_assistant_event(
                VoiceAssistantEventType.VOICE_ASSISTANT_STT_START, None
            )

            transcript = await transcribe_audio(cfg.whisper_uri, audio_buffer)
            if not transcript or not transcript.strip():
                logger.info("Empty transcript from %s, ending pipeline", cfg.device_name)
                client.send_voice_assistant_event(
                    VoiceAssistantEventType.VOICE_ASSISTANT_ERROR,
                    {"code": "no_speech", "message": "No speech detected"},
                )
                client.send_voice_assistant_event(
                    VoiceAssistantEventType.VOICE_ASSISTANT_RUN_END, None
                )
                return

            logger.info("Transcript from %s: %r", cfg.device_name, transcript)
            client.send_voice_assistant_event(
                VoiceAssistantEventType.VOICE_ASSISTANT_STT_END,
                {"text": transcript},
            )

            # --- Intent / Chat ---
            client.send_voice_assistant_event(
                VoiceAssistantEventType.VOICE_ASSISTANT_INTENT_START, None
            )

            from datetime import datetime, timezone
            submit_time = datetime.now(timezone.utc)

            result = await cfg.agent.submit_chat(
                message=transcript,
                bot_id=dc.bot_id,
                client_id=dc.client_id,
                dispatch_type="wyoming",
                dispatch_config={
                    "type": "esphome",
                    "device_id": cfg.device_name,
                },
                msg_metadata={
                    "source": "wyoming",
                    "sender_type": "human",
                    "sender_id": f"esphome:{cfg.device_name}",
                    "sender_display_name": self._friendly_name,
                },
            )

            session_id = result.get("session_id")
            if not session_id:
                logger.error("No session_id in chat response for %s", cfg.device_name)
                client.send_voice_assistant_event(
                    VoiceAssistantEventType.VOICE_ASSISTANT_ERROR,
                    {"code": "no-session", "message": "Failed to start chat"},
                )
                client.send_voice_assistant_event(
                    VoiceAssistantEventType.VOICE_ASSISTANT_RUN_END, None
                )
                return

            logger.info("Chat submitted for %s: session=%s", cfg.device_name, session_id)

            # Poll for the bot's response, filtering by submission time
            # to avoid picking up stale responses from previous turns
            response_text = await cfg.agent.wait_for_response(
                session_id, after=submit_time,
            )
            if not response_text:
                logger.warning("Empty response from agent for %s", cfg.device_name)
                response_text = "I don't have a response for that."

            client.send_voice_assistant_event(
                VoiceAssistantEventType.VOICE_ASSISTANT_INTENT_END,
                {"intent_output": response_text},
            )

            # --- TTS ---
            # Event order matches Home Assistant's ESPHome voice pipeline:
            # TTS_START → synthesize → TTS_END(url="") → TTS_STREAM_START →
            # fixed-size audio chunks → TTS_STREAM_END → RUN_END
            client.send_voice_assistant_event(
                VoiceAssistantEventType.VOICE_ASSISTANT_TTS_START,
                {"text": response_text},
            )

            voice = dc.voice or cfg.default_voice
            audio_events = await synthesize_speech(cfg.piper_uri, response_text, voice)

            # Collect all audio and resample into one contiguous PCM buffer,
            # then re-chunk into fixed 512-sample (1024-byte) pieces — this
            # matches HA's _stream_tts_audio exactly.
            pcm_parts: list[bytes] = []
            src_rate: int | None = None
            for event in audio_events:
                if AudioStart.is_type(event.type):
                    astart = AudioStart.from_event(event)
                    src_rate = astart.rate
                elif AudioChunk.is_type(event.type):
                    chunk = AudioChunk.from_event(event)
                    if src_rate is None:
                        src_rate = chunk.rate
                    pcm_parts.append(chunk.audio)

            raw_pcm = b"".join(pcm_parts)
            effective_rate = src_rate or _PIPER_SAMPLE_RATE
            pcm_16k = _resample_if_needed(raw_pcm, effective_rate, _DEVICE_SAMPLE_RATE)

            logger.info(
                "TTS for %s: %d Piper events, %d bytes @ %dHz -> %d bytes @ %dHz",
                cfg.device_name, len(audio_events),
                len(raw_pcm), effective_rate,
                len(pcm_16k), _DEVICE_SAMPLE_RATE,
            )

            # Audio delivery via UDP:
            # 1. Send TTS_END with non-empty URL → device transitions to
            #    STREAMING_RESPONSE and opens its UDP socket for reading.
            # 2. Send audio chunks via UDP at realtime pace.
            #
            # TTS_END URL must be non-empty — ESPHome 2026.3 early-returns
            # on empty URL, skipping the state transition.
            #
            # We skip TTS_STREAM_START/END — ESPHome 2026.3 has a bug
            # where stream_ended_ persists across runs. The speaker-timeout
            # mechanism handles end-of-playback naturally.

            # Transition to STREAMING_RESPONSE first — device needs to be
            # in this state to read from the UDP socket.
            client.send_voice_assistant_event(
                VoiceAssistantEventType.VOICE_ASSISTANT_TTS_END,
                {"url": "synth://spindrel"},
            )

            if pcm_16k and self._udp_server:
                # Small delay to let the device enter STREAMING_RESPONSE
                # and set up its socket reader
                await asyncio.sleep(0.05)

                # Pace audio at 1.1x realtime using absolute time targets.
                # The device has a 16KB speaker buffer (~0.5s at 16kHz/16-bit).
                # We also cap how far ahead of realtime we can drift — if the
                # event loop stalls and then catches up, we'd otherwise burst
                # many chunks at once, overflowing the device buffer.
                seconds_per_chunk = _UDP_AUDIO_CHUNK_BYTES / 2 / _DEVICE_SAMPLE_RATE
                pace = seconds_per_chunk / 1.1  # 1.1x realtime
                # Max chunks we're allowed to be ahead of realtime playback.
                # 8 chunks × 32ms = 256ms — well within the 512ms device buffer.
                max_ahead_chunks = 8

                loop = asyncio.get_running_loop()
                start_time = loop.time()
                offset = 0
                chunks_sent = 0
                while offset < len(pcm_16k):
                    chunk_data = pcm_16k[offset:offset + _UDP_AUDIO_CHUNK_BYTES]
                    self._udp_server.send_audio(chunk_data)
                    offset += _UDP_AUDIO_CHUNK_BYTES
                    chunks_sent += 1

                    # How far ahead of realtime playback are we?
                    elapsed = loop.time() - start_time
                    realtime_chunks = elapsed / seconds_per_chunk
                    ahead = chunks_sent - realtime_chunks

                    if ahead >= max_ahead_chunks:
                        # We've burst too far ahead — wait until we're back
                        # within budget before sending more
                        wait_until = start_time + (chunks_sent - max_ahead_chunks + 1) * seconds_per_chunk
                        delay = wait_until - loop.time()
                        if delay > 0:
                            await asyncio.sleep(delay)
                    else:
                        # Normal pacing — sleep until our target send time
                        target = start_time + chunks_sent * pace
                        delay = target - loop.time()
                        if delay > 0:
                            await asyncio.sleep(delay)

                logger.info(
                    "Sent %d UDP audio chunks (%d bytes) to %s",
                    chunks_sent, len(pcm_16k), cfg.device_name,
                )

            client.send_voice_assistant_event(
                VoiceAssistantEventType.VOICE_ASSISTANT_RUN_END, None
            )

            logger.info(
                "Voice pipeline complete for %s: %r -> %r",
                cfg.device_name, transcript, response_text[:100],
            )

        except Exception:
            logger.exception("Voice pipeline error for %s", cfg.device_name)
            try:
                if client:
                    client.send_voice_assistant_event(
                        VoiceAssistantEventType.VOICE_ASSISTANT_ERROR,
                        {"code": "pipeline-error", "message": "Internal error"},
                    )
                    client.send_voice_assistant_event(
                        VoiceAssistantEventType.VOICE_ASSISTANT_RUN_END, None
                    )
            except Exception:
                pass


def _resample_if_needed(
    audio: bytes, src_rate: int, dst_rate: int,
) -> bytes:
    """Resample 16-bit mono PCM audio via linear interpolation.

    audioop was removed in Python 3.13, so we do simple linear resampling
    for the common case (Piper 22050Hz → device 16000Hz).
    """
    if src_rate == dst_rate:
        return audio
    # Decode 16-bit signed samples
    src = array.array("h")
    src.frombytes(audio)
    n_src = len(src)
    if n_src == 0:
        return audio
    ratio = src_rate / dst_rate
    n_dst = int(n_src / ratio)
    dst = array.array("h", [0] * n_dst)
    for i in range(n_dst):
        pos = i * ratio
        idx = int(pos)
        frac = pos - idx
        if idx + 1 < n_src:
            dst[i] = int(src[idx] * (1 - frac) + src[idx + 1] * frac)
        else:
            dst[i] = src[min(idx, n_src - 1)]
    return dst.tobytes()
