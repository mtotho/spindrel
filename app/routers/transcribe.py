import logging

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request

from app.dependencies import verify_auth
from app.stt import transcribe as stt_transcribe

logger = logging.getLogger(__name__)

router = APIRouter()

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 4  # float32


@router.post("/transcribe")
async def transcribe(
    request: Request,
    _auth: str = Depends(verify_auth),
):
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty audio data")

    if len(body) % BYTES_PER_SAMPLE != 0:
        raise HTTPException(
            status_code=400,
            detail=f"Audio data length must be a multiple of {BYTES_PER_SAMPLE} (float32)",
        )

    audio = np.frombuffer(body, dtype=np.float32)
    duration = len(audio) / SAMPLE_RATE
    logger.info("POST /transcribe  %.1fs audio (%d samples)", duration, len(audio))

    if duration < 0.1:
        raise HTTPException(status_code=400, detail="Audio too short")
    if duration > 60:
        raise HTTPException(status_code=400, detail="Audio too long (max 60s)")

    try:
        text = stt_transcribe(audio)
    except Exception as e:
        logger.exception("Transcription failed")
        raise HTTPException(status_code=500, detail=f"Transcription error: {e}")

    logger.info("Transcribed: %r", text[:100] if text else "(empty)")
    return {"text": text}
