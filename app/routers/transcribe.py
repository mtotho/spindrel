import logging
import tempfile

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request

from app.dependencies import verify_auth_or_user
from app.stt import transcribe as stt_transcribe

logger = logging.getLogger(__name__)

router = APIRouter()

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 4  # float32

# Content types treated as raw float32 PCM (legacy Python CLI client format)
RAW_FLOAT32_TYPES = {"application/octet-stream", ""}

# Extensions for common audio MIME types (used for temp file so ffmpeg can detect format)
MIME_EXTENSIONS = {
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/webm": ".webm",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/3gpp": ".3gp",
    "audio/amr": ".amr",
    "audio/flac": ".flac",
}


def _transcribe_raw_float32(body: bytes) -> str:
    """Original path: raw float32 PCM at 16kHz mono."""
    if len(body) % BYTES_PER_SAMPLE != 0:
        raise HTTPException(
            status_code=400,
            detail=f"Audio data length must be a multiple of {BYTES_PER_SAMPLE} (float32)",
        )

    audio = np.frombuffer(body, dtype=np.float32)
    duration = len(audio) / SAMPLE_RATE
    logger.info("POST /transcribe  raw float32 %.1fs (%d samples)", duration, len(audio))

    if duration < 0.1:
        raise HTTPException(status_code=400, detail="Audio too short")
    if duration > 60:
        raise HTTPException(status_code=400, detail="Audio too long (max 60s)")

    return stt_transcribe(audio)


def _transcribe_audio_file(body: bytes, content_type: str) -> str:
    """Decode an audio file via ffmpeg (faster-whisper handles this) and transcribe."""
    ext = MIME_EXTENSIONS.get(content_type, ".m4a")
    logger.info("POST /transcribe  audio file (%s, %d bytes)", content_type, len(body))

    with tempfile.NamedTemporaryFile(suffix=ext, delete=True) as tmp:
        tmp.write(body)
        tmp.flush()
        return stt_transcribe(tmp.name)


@router.post("/transcribe")
async def transcribe(
    request: Request,
    _auth: str = Depends(verify_auth_or_user),
):
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty audio data")

    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()

    try:
        if content_type in RAW_FLOAT32_TYPES:
            text = _transcribe_raw_float32(body)
        else:
            text = _transcribe_audio_file(body, content_type)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Transcription failed")
        raise HTTPException(status_code=500, detail=f"Transcription error: {e}")

    logger.info("Transcribed: %r", text[:100] if text else "(empty)")
    return {"text": text}
