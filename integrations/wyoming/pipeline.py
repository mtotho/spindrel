"""Voice pipeline -- orchestrates STT -> dispatch -> response -> TTS.

This is the core logic that bridges Wyoming protocol events with the
Spindrel agent server. Each voice interaction runs through this pipeline:

1. Receive audio chunks from the satellite
2. Forward to Whisper (via Wyoming protocol) for transcription
3. Submit transcript to Spindrel channel via POST /chat
4. Wait for bot response via SSE stream
5. Send response text to Piper (via Wyoming protocol) for synthesis
6. Return synthesized audio to the satellite
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.asr import Transcript, Transcribe
from wyoming.client import AsyncClient as WyomingClient
from wyoming.event import Event
from wyoming.tts import Synthesize

from integrations.wyoming.agent_client import AgentClient

logger = logging.getLogger(__name__)


@dataclass
class AudioBuffer:
    """Collects audio chunks during a recording session."""
    rate: int = 16000
    width: int = 2
    channels: int = 1
    chunks: list[bytes] = field(default_factory=list)

    def add_chunk(self, audio: bytes):
        self.chunks.append(audio)

    def get_audio(self) -> bytes:
        return b"".join(self.chunks)

    def clear(self):
        self.chunks.clear()

    @property
    def duration_seconds(self) -> float:
        total_bytes = sum(len(c) for c in self.chunks)
        return total_bytes / (self.rate * self.width * self.channels)


async def transcribe_audio(
    whisper_uri: str,
    audio_buffer: AudioBuffer,
) -> str | None:
    """Send audio to Whisper STT and return transcript text.

    Connects to the Wyoming Whisper service, streams the buffered audio,
    and waits for a Transcript event back.
    """
    host, port = _parse_uri(whisper_uri)
    try:
        client = WyomingClient(host, port)
        await client.connect()

        # Send audio
        await client.write_event(
            AudioStart(
                rate=audio_buffer.rate,
                width=audio_buffer.width,
                channels=audio_buffer.channels,
            ).event()
        )

        audio_data = audio_buffer.get_audio()
        chunk_size = audio_buffer.rate * audio_buffer.width  # 1 second chunks
        for i in range(0, len(audio_data), chunk_size):
            chunk = audio_data[i:i + chunk_size]
            await client.write_event(
                AudioChunk(
                    rate=audio_buffer.rate,
                    width=audio_buffer.width,
                    channels=audio_buffer.channels,
                    audio=chunk,
                ).event()
            )

        await client.write_event(AudioStop().event())

        # Wait for transcript
        while True:
            event = await asyncio.wait_for(client.read_event(), timeout=30.0)
            if event is None:
                break
            if Transcript.is_type(event.type):
                transcript = Transcript.from_event(event)
                logger.info("Transcribed: %r", transcript.text)
                return transcript.text

        return None
    except asyncio.TimeoutError:
        logger.error("Whisper transcription timed out")
        return None
    except Exception:
        logger.exception("Whisper transcription failed")
        return None


async def synthesize_speech(
    piper_uri: str,
    text: str,
    voice: str | None = None,
) -> list[Event]:
    """Send text to Piper TTS and return audio events.

    Connects to the Wyoming Piper service, sends a Synthesize event,
    and collects the resulting AudioStart + AudioChunk(s) + AudioStop.
    """
    host, port = _parse_uri(piper_uri)
    events: list[Event] = []
    try:
        client = WyomingClient(host, port)
        await client.connect()

        synth = Synthesize(text=text, voice=voice)
        await client.write_event(synth.event())

        # Collect audio response
        while True:
            event = await asyncio.wait_for(client.read_event(), timeout=30.0)
            if event is None:
                break
            events.append(event)
            if AudioStop.is_type(event.type):
                break

        return events
    except asyncio.TimeoutError:
        logger.error("Piper synthesis timed out")
        return []
    except Exception:
        logger.exception("Piper synthesis failed")
        return []


async def run_voice_pipeline(
    *,
    audio_buffer: AudioBuffer,
    whisper_uri: str,
    piper_uri: str,
    agent: AgentClient,
    bot_id: str,
    client_id: str,
    session_id: str | None = None,
    voice: str | None = None,
) -> list[Event]:
    """Full voice pipeline: STT -> dispatch -> response -> TTS.

    Returns the list of audio events (AudioStart + AudioChunk(s) + AudioStop)
    to send back to the satellite. Returns empty list on failure.
    """
    # Step 1: Transcribe
    transcript = await transcribe_audio(whisper_uri, audio_buffer)
    if not transcript or not transcript.strip():
        logger.info("Empty transcript, skipping dispatch")
        return []

    logger.info("Pipeline: transcript=%r -> channel=%s", transcript, client_id)

    # Step 2: Dispatch to Spindrel
    try:
        result = await agent.submit_chat(
            message=transcript,
            bot_id=bot_id,
            client_id=client_id,
            session_id=session_id,
            dispatch_type="wyoming",
            dispatch_config={
                "type": "wyoming",
                "device_id": client_id.removeprefix("wyoming:"),
            },
        )
    except Exception:
        logger.exception("Failed to submit chat")
        return await _synthesize_error(piper_uri, "Sorry, I couldn't process that.", voice)

    # Step 3: Wait for response
    stream_id = result.get("stream_id")
    if not stream_id:
        logger.error("No stream_id in chat response: %s", result)
        return await _synthesize_error(piper_uri, "Sorry, something went wrong.", voice)

    response_text = await agent.stream_response(stream_id)
    if not response_text:
        logger.warning("Empty response from agent")
        return await _synthesize_error(piper_uri, "I don't have a response for that.", voice)

    logger.info("Pipeline: response=%r", response_text[:200])

    # Step 4: Synthesize speech
    return await synthesize_speech(piper_uri, response_text, voice)


async def _synthesize_error(
    piper_uri: str, message: str, voice: str | None,
) -> list[Event]:
    """Synthesize an error message for the user."""
    events = await synthesize_speech(piper_uri, message, voice)
    return events


def _parse_uri(uri: str) -> tuple[str, int]:
    """Parse a tcp://host:port URI into (host, port)."""
    uri = uri.removeprefix("tcp://")
    if ":" in uri:
        host, port_str = uri.rsplit(":", 1)
        return host, int(port_str)
    return uri, 10300
