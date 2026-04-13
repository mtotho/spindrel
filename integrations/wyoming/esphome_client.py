"""ESPHome voice client — connects to ESP32 devices running ESPHome firmware.

Uses aioesphomeapi to connect to devices (like the M5Stack ATOM Echo),
subscribe for voice assistant events, and run the STT → Spindrel → TTS
pipeline using the same Whisper/Piper services as Wyoming satellites.

The ESPHome device is the TCP server (listens on port 6053 by default).
Spindrel connects OUT to the device — same direction as Wyoming satellites.
"""
from __future__ import annotations

import array
import asyncio
import logging
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
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None

    async def _run_loop(self) -> None:
        """Reconnect loop — keeps trying to connect to the device."""
        cfg = self._config
        while True:
            try:
                logger.info(
                    "Connecting to ESPHome device %s at %s:%d",
                    cfg.device_name, cfg.host, cfg.port,
                )
                await self._connect_and_run()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "ESPHome connection to %s failed, retrying in 5s",
                    cfg.device_name,
                )
            await self._disconnect()
            await asyncio.sleep(5)

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

        # Subscribe for voice assistant events.
        # handle_start is called when the device detects a wake word.
        # handle_stop is called when audio ends or device aborts.
        # handle_audio receives raw PCM chunks.
        unsub_voice = self._client.subscribe_voice_assistant(
            handle_start=self._handle_start,
            handle_stop=self._handle_stop,
            handle_audio=self._handle_audio,
        )

        try:
            # Block until disconnected. aioesphomeapi handles pings internally.
            while self._client is not None:
                await asyncio.sleep(1)
        finally:
            unsub_voice()
            unsub_logs()

    async def _handle_start(
        self,
        conversation_id: str,
        flags: int,
        audio_settings: object,
        wake_word_phrase: str | None,
    ) -> int | None:
        """Called when the device detects a wake word and wants to start a pipeline.

        Returns port number for UDP audio or 0 for API audio mode (protobuf).
        """
        logger.info(
            "Voice pipeline started on %s (conv=%s, flags=%d, wake=%s, audio=%s)",
            self._config.device_name,
            conversation_id, flags, wake_word_phrase, audio_settings,
        )
        self._audio_buffer = AudioBuffer(rate=_DEVICE_SAMPLE_RATE, width=2, channels=1)
        self._voice_active = True
        # Return 0 → API audio mode: mic audio arrives via protobuf messages
        # (not UDP), and we send TTS audio back via send_voice_assistant_audio.
        return 0

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

        # Send STT_VAD_END immediately — this overrides the device's
        # desired_state_ from IDLE to AWAITING_RESPONSE, preventing the
        # IDLE loop from killing the speaker before TTS audio plays.
        if self._client:
            self._client.send_voice_assistant_event(
                VoiceAssistantEventType.VOICE_ASSISTANT_STT_VAD_END, None
            )

        if buffer.duration_seconds < 0.3:
            logger.info("Audio too short (%.1fs) from %s, skipping", buffer.duration_seconds, self._config.device_name)
            if self._client:
                self._client.send_voice_assistant_event(
                    VoiceAssistantEventType.VOICE_ASSISTANT_RUN_END, None
                )
            return

        logger.info(
            "Processing %.1fs of audio from %s (abort=%s)",
            buffer.duration_seconds, self._config.device_name, abort,
        )

        # Run pipeline in a separate task so we don't block the connection
        self._pipeline_task = asyncio.create_task(
            self._run_voice_pipeline(buffer)
        )

    async def _handle_audio(self, data: bytes) -> None:
        """Called for each chunk of audio from the device."""
        if self._audio_buffer is not None:
            self._audio_buffer.add_chunk(data)

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

            result = await cfg.agent.submit_chat(
                message=transcript,
                bot_id=dc.bot_id,
                client_id=dc.client_id,
                dispatch_type="wyoming",
                dispatch_config={
                    "type": "esphome",
                    "device_id": cfg.device_name,
                },
            )

            session_id = result.get("session_id")
            turn_id = result.get("turn_id")
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

            logger.info("Chat submitted for %s: session=%s turn=%s", cfg.device_name, session_id, turn_id)

            # Poll for the bot's response (the /chat endpoint is async —
            # it returns 202 and the turn worker generates the response)
            response_text = await cfg.agent.wait_for_response(session_id)
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

            # TTS_END transitions device to STREAMING_RESPONSE state
            client.send_voice_assistant_event(
                VoiceAssistantEventType.VOICE_ASSISTANT_TTS_END,
                {"url": ""},  # empty = stream via API, not download
            )

            if pcm_16k:
                client.send_voice_assistant_event(
                    VoiceAssistantEventType.VOICE_ASSISTANT_TTS_STREAM_START, {}
                )

                # Give the device time to transition into STREAMING_RESPONSE
                # and start the write_speaker_() drain loop before we flood it.
                await asyncio.sleep(0.1)

                # Stream in fixed 512-sample (1024-byte) chunks at realtime
                # pacing. The device's speaker buffer is 16KB and drains at
                # 32KB/s (16kHz * 2 bytes). Each chunk is 1024 bytes = 32ms
                # of audio, so we sleep 32ms between chunks (1:1 realtime).
                samples_per_chunk = 512
                bytes_per_chunk = samples_per_chunk * 2  # 16-bit
                seconds_per_chunk = samples_per_chunk / _DEVICE_SAMPLE_RATE
                chunks_sent = 0

                for offset in range(0, len(pcm_16k), bytes_per_chunk):
                    chunk_data = pcm_16k[offset:offset + bytes_per_chunk]
                    client.send_voice_assistant_audio(chunk_data)
                    chunks_sent += 1
                    await asyncio.sleep(seconds_per_chunk)

                logger.info(
                    "Sent %d audio chunks (%d bytes) to %s",
                    chunks_sent, len(pcm_16k), cfg.device_name,
                )

                client.send_voice_assistant_event(
                    VoiceAssistantEventType.VOICE_ASSISTANT_TTS_STREAM_END, {}
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
