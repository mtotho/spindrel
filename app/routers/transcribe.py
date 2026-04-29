import logging
import tempfile

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request

from app.dependencies import require_scopes
from app.services.audio_input import AudioInputError, validate_encoded_audio_file
from app.stt import transcribe as stt_transcribe

logger = logging.getLogger(__name__)

router = APIRouter()

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 4  # float32

# Content types treated as raw float32 PCM (legacy Python CLI client format)
RAW_FLOAT32_TYPES = {"application/octet-stream", ""}

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
    try:
        audio = validate_encoded_audio_file(body, content_type)
    except AudioInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("POST /transcribe  audio file (%s, %d bytes)", audio.media_type, len(audio.data))

    with tempfile.NamedTemporaryFile(suffix=audio.suffix, delete=True) as tmp:
        tmp.write(audio.data)
        tmp.flush()
        return stt_transcribe(tmp.name)


@router.post("/transcribe")
async def transcribe(
    request: Request,
    _auth=Depends(require_scopes("chat")),
):
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty audio data")

    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()

    # Fire before_transcription hook — integrations can override STT
    from app.agent.hooks import fire_hook_with_override, HookContext
    _override = await fire_hook_with_override("before_transcription", HookContext(
        extra={
            "audio_format": content_type or "application/octet-stream",
            "audio_size_bytes": len(body),
            "source": "api",
        },
    ))
    if isinstance(_override, str) and _override.strip():
        text = _override
    else:
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
