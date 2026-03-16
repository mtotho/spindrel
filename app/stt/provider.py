import logging
from abc import ABC, abstractmethod

import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

_provider: "SttProvider | None" = None


class SttProvider(ABC):
    @abstractmethod
    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe float32 16kHz mono audio and return text."""

    def warm_up(self) -> None:
        """Optional: pre-load models so first request is fast."""


class LocalWhisperProvider(SttProvider):
    def __init__(self):
        self._model = None

    def warm_up(self) -> None:
        self._load_model()

    def _load_model(self, device: str | None = None, compute_type: str | None = None):
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        dev = device or settings.WHISPER_DEVICE
        ct = compute_type or settings.WHISPER_COMPUTE_TYPE
        logger.info("Loading whisper model=%s device=%s compute=%s", settings.WHISPER_MODEL, dev, ct)
        try:
            self._model = WhisperModel(settings.WHISPER_MODEL, device=dev, compute_type=ct)
        except Exception:
            if dev != "cpu":
                logger.warning("Failed to load whisper with device=%s, falling back to CPU", dev)
                self._model = WhisperModel(settings.WHISPER_MODEL, device="cpu", compute_type="int8")
            else:
                raise
        logger.info("Whisper model loaded.")

    def transcribe(self, audio: np.ndarray) -> str:
        self._load_model()
        segments, info = self._model.transcribe(
            audio,
            beam_size=settings.WHISPER_BEAM_SIZE,
            language=settings.WHISPER_LANGUAGE,
        )
        try:
            return " ".join(seg.text.strip() for seg in segments).strip()
        except RuntimeError as e:
            if "libcublas" in str(e) or "cuda" in str(e).lower():
                logger.warning("CUDA runtime error during transcription, reloading with CPU: %s", e)
                self._model = None
                self._load_model(device="cpu", compute_type="int8")
                segments, _ = self._model.transcribe(
                    audio,
                    beam_size=settings.WHISPER_BEAM_SIZE,
                    language=settings.WHISPER_LANGUAGE,
                )
                return " ".join(seg.text.strip() for seg in segments).strip()
            raise


def get_provider() -> SttProvider:
    global _provider
    if _provider is None:
        if settings.STT_PROVIDER == "local":
            _provider = LocalWhisperProvider()
        else:
            raise ValueError(f"Unknown STT_PROVIDER: {settings.STT_PROVIDER}")
    return _provider


def transcribe(audio: np.ndarray) -> str:
    return get_provider().transcribe(audio)


def warm_up() -> None:
    get_provider().warm_up()
