import logging
import os
import tempfile
import wave
from abc import ABC, abstractmethod

import numpy as np
from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_provider: "SttProvider | None" = None
_provider_key: tuple[str, str, str, str] | None = None
_OPENAI_DEFAULT_TRANSCRIPTION_MODEL = "gpt-4o-mini-transcribe"


class SttProvider(ABC):
    @abstractmethod
    def transcribe(self, audio: "np.ndarray | str") -> str:
        """Transcribe audio. Accepts float32 numpy array or file path (decoded by ffmpeg)."""

    def warm_up(self) -> None:
        """Optional: pre-load models so first request is fast."""


class LocalWhisperProvider(SttProvider):
    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None

    def warm_up(self) -> None:
        self._load_model()

    def _load_model(self, device: str | None = None, compute_type: str | None = None):
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        dev = device or settings.WHISPER_DEVICE
        ct = compute_type or settings.WHISPER_COMPUTE_TYPE
        logger.info("Loading whisper model=%s device=%s compute=%s", self.model_name, dev, ct)
        try:
            self._model = WhisperModel(self.model_name, device=dev, compute_type=ct)
        except Exception:
            if dev != "cpu":
                logger.warning("Failed to load whisper with device=%s, falling back to CPU", dev)
                self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            else:
                raise
        logger.info("Whisper model loaded.")

    def transcribe(self, audio: "np.ndarray | str") -> str:
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


def _write_float32_wav(audio: np.ndarray) -> str:
    """Write 16kHz mono float32 audio to a temporary PCM16 WAV file."""
    clipped = np.clip(audio.astype(np.float32, copy=False), -1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype(np.int16)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()
    with wave.open(tmp_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(pcm16.tobytes())
    return tmp_path


class OpenAITranscriptionProvider(SttProvider):
    def __init__(self, model_name: str, provider_id: str):
        self.model_name = model_name
        self.provider_id = provider_id

    def _client(self) -> OpenAI:
        from app.services.provider_drivers.base import ProviderDriver
        from app.services.providers import get_provider as get_llm_provider

        provider = get_llm_provider(self.provider_id)
        if provider is None:
            raise RuntimeError(
                f"STT_MODEL_PROVIDER_ID={self.provider_id!r} is not a loaded provider"
            )
        if provider.provider_type not in {"openai", "openai-compatible"}:
            raise RuntimeError(
                "OpenAI transcription requires an OpenAI API or OpenAI-compatible provider. "
                "ChatGPT subscription providers cannot be used for transcription."
            )
        if not provider.api_key:
            raise RuntimeError(
                f"Provider {self.provider_id!r} has no API key for OpenAI transcription"
            )
        kwargs: dict = {
            "api_key": provider.api_key,
            "timeout": settings.LLM_TIMEOUT,
            "max_retries": 0,
        }
        if provider.base_url:
            kwargs["base_url"] = provider.base_url
        extra_headers = ProviderDriver._extra_headers(provider)
        if extra_headers:
            kwargs["default_headers"] = extra_headers
        return OpenAI(**kwargs)

    def transcribe(self, audio: "np.ndarray | str") -> str:
        temp_path: str | None = None
        path = audio
        if isinstance(audio, np.ndarray):
            temp_path = _write_float32_wav(audio)
            path = temp_path
        if not isinstance(path, str):
            raise TypeError("OpenAI transcription provider expects a file path or numpy audio")

        try:
            with open(path, "rb") as f:
                kwargs = {
                    "model": self.model_name,
                    "file": f,
                }
                if settings.WHISPER_LANGUAGE:
                    kwargs["language"] = settings.WHISPER_LANGUAGE
                result = self._client().audio.transcriptions.create(**kwargs)
            return (getattr(result, "text", "") or "").strip()
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass


def _settings_key() -> tuple[str, str, str, str]:
    provider_name = (settings.STT_PROVIDER or "").strip().lower()
    stt_model = (settings.STT_MODEL or "").strip()
    provider_id = (settings.STT_MODEL_PROVIDER_ID or "").strip()
    local_model = (settings.WHISPER_MODEL or "").strip()
    return provider_name, stt_model, provider_id, local_model


def get_provider() -> SttProvider:
    global _provider, _provider_key
    key = _settings_key()
    if _provider is None or _provider_key != key:
        provider_name, stt_model, provider_id, local_model = key
        if provider_name == "local":
            _provider = LocalWhisperProvider(local_model or "base.en")
        elif provider_name == "openai":
            if not provider_id:
                raise RuntimeError(
                    "STT_PROVIDER=openai requires STT_MODEL_PROVIDER_ID to choose the provider/API key"
                )
            _provider = OpenAITranscriptionProvider(
                stt_model or _OPENAI_DEFAULT_TRANSCRIPTION_MODEL,
                provider_id,
            )
        elif not provider_name:
            raise RuntimeError(
                "STT_PROVIDER is not configured; enable local STT or provide a before_transcription hook"
            )
        else:
            raise ValueError(f"Unknown STT_PROVIDER: {settings.STT_PROVIDER}")
        _provider_key = key
    return _provider


def transcribe(audio: "np.ndarray | str") -> str:
    return get_provider().transcribe(audio)


def warm_up() -> None:
    get_provider().warm_up()
