"""Voice/audio helpers for the CLI (transcribe, TTS, wake word, bot audio)."""
import base64
import io
import struct
import threading

import numpy as np

from agent_client.audio import (
    listen_for_wakeword,
    speak,
    stop_speaking,
    transcribe as local_transcribe,
)
from agent_client.client import AgentClient


def transcribe(audio, client: AgentClient, ctx: dict) -> str | None:
    """Transcribe audio, trying server-side first then falling back to local."""
    try:
        audio_bytes = audio.flatten().astype(np.float32).tobytes()
        text = client.transcribe(audio_bytes)
        if text is not None:
            return text
    except Exception:
        pass

    return local_transcribe(audio, ctx["whisper_model"])


def audio_to_base64(audio) -> str:
    """Convert a numpy audio array to base64-encoded WAV for native audio input."""
    samples = audio.flatten().astype(np.float32)
    pcm = (samples * 32767).astype(np.int16)
    buf = io.BytesIO()
    num_samples = len(pcm)
    data_size = num_samples * 2
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16))
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(pcm.tobytes())
    return base64.b64encode(buf.getvalue()).decode("ascii")


def speak_interruptible(response_text: str, ctx: dict) -> bool:
    """Speak response in a background thread while listening for wake word.

    Returns True if the wake word interrupted TTS playback.
    """
    tts_done = threading.Event()

    def _tts_worker():
        speak(response_text, ctx["piper_model"], ctx["piper_model_dir"], ctx.get("tts_speed", 1.0))
        tts_done.set()

    thread = threading.Thread(target=_tts_worker, daemon=True)
    thread.start()

    detected = listen_for_wakeword(ctx["wake_words"], stop_event=tts_done)
    stop_speaking()
    thread.join(timeout=2)
    return detected is not None


def apply_bot_audio(client: AgentClient, ctx: dict) -> None:
    """Fetch audio config for current bot from server (e.g. audio_input=native)."""
    try:
        bots = client.list_bots()
        for b in bots:
            if b["id"] == ctx["bot_id"]:
                ctx["audio_native"] = b.get("audio_input") == "native" or ctx["_default_audio_native"]
                return
    except Exception:
        pass
    ctx["audio_native"] = ctx["_default_audio_native"]
