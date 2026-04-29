"""Validation helpers for user-supplied audio input."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass

MAX_ENCODED_AUDIO_BYTES = 25 * 1024 * 1024


class AudioInputError(ValueError):
    """Raised when submitted audio cannot be accepted safely."""


@dataclass(frozen=True)
class AudioFormat:
    format: str
    suffix: str
    media_type: str


@dataclass(frozen=True)
class EncodedAudio:
    data: bytes
    format: str
    suffix: str
    media_type: str


_FORMAT_ALIASES: dict[str, AudioFormat] = {
    "m4a": AudioFormat("m4a", ".m4a", "audio/mp4"),
    "mp4": AudioFormat("mp4", ".mp4", "audio/mp4"),
    "aac": AudioFormat("aac", ".aac", "audio/aac"),
    "mp3": AudioFormat("mp3", ".mp3", "audio/mpeg"),
    "mpeg": AudioFormat("mp3", ".mp3", "audio/mpeg"),
    "ogg": AudioFormat("ogg", ".ogg", "audio/ogg"),
    "oga": AudioFormat("ogg", ".ogg", "audio/ogg"),
    "opus": AudioFormat("ogg", ".ogg", "audio/ogg"),
    "webm": AudioFormat("webm", ".webm", "audio/webm"),
    "wav": AudioFormat("wav", ".wav", "audio/wav"),
    "wave": AudioFormat("wav", ".wav", "audio/wav"),
    "x-wav": AudioFormat("wav", ".wav", "audio/wav"),
    "flac": AudioFormat("flac", ".flac", "audio/flac"),
    "3gp": AudioFormat("3gp", ".3gp", "audio/3gpp"),
    "3gpp": AudioFormat("3gp", ".3gp", "audio/3gpp"),
    "amr": AudioFormat("amr", ".amr", "audio/amr"),
}

_MEDIA_TYPE_ALIASES: dict[str, AudioFormat] = {
    "audio/mp4": _FORMAT_ALIASES["m4a"],
    "audio/m4a": _FORMAT_ALIASES["m4a"],
    "audio/aac": _FORMAT_ALIASES["aac"],
    "audio/mpeg": _FORMAT_ALIASES["mp3"],
    "audio/mp3": _FORMAT_ALIASES["mp3"],
    "audio/ogg": _FORMAT_ALIASES["ogg"],
    "audio/opus": _FORMAT_ALIASES["opus"],
    "audio/webm": _FORMAT_ALIASES["webm"],
    "audio/wav": _FORMAT_ALIASES["wav"],
    "audio/x-wav": _FORMAT_ALIASES["wav"],
    "audio/wave": _FORMAT_ALIASES["wav"],
    "audio/flac": _FORMAT_ALIASES["flac"],
    "audio/3gpp": _FORMAT_ALIASES["3gp"],
    "audio/amr": _FORMAT_ALIASES["amr"],
}


def normalize_audio_format(audio_format: str | None) -> AudioFormat:
    """Normalize a browser/API audio format into a safe temp-file suffix."""

    value = (audio_format or "m4a").split(";")[0].strip().lower()
    if not value:
        value = "m4a"
    if value.startswith("."):
        value = value[1:]

    if value.startswith("audio/"):
        fmt = _MEDIA_TYPE_ALIASES.get(value)
        if fmt is None:
            raise AudioInputError(f"Unsupported audio content type: {audio_format}")
        return fmt

    fmt = _FORMAT_ALIASES.get(value)
    if fmt is None:
        raise AudioInputError(f"Unsupported audio format: {audio_format}")
    return fmt


def _validate_size(data: bytes, *, max_bytes: int) -> None:
    if not data:
        raise AudioInputError("Empty audio data")
    if len(data) > max_bytes:
        raise AudioInputError(f"Audio too large (max {max_bytes} bytes)")


def decode_base64_audio(
    audio_b64: str,
    audio_format: str | None,
    *,
    max_bytes: int = MAX_ENCODED_AUDIO_BYTES,
) -> EncodedAudio:
    fmt = normalize_audio_format(audio_format)
    try:
        data = base64.b64decode(audio_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AudioInputError("Invalid base64 audio data") from exc
    _validate_size(data, max_bytes=max_bytes)
    return EncodedAudio(
        data=data,
        format=fmt.format,
        suffix=fmt.suffix,
        media_type=fmt.media_type,
    )


def validate_encoded_audio_file(
    data: bytes,
    content_type: str,
    *,
    max_bytes: int = MAX_ENCODED_AUDIO_BYTES,
) -> EncodedAudio:
    content = (content_type or "").split(";")[0].strip().lower()
    if "/" in content and not content.startswith("audio/"):
        raise AudioInputError(f"Unsupported audio content type: {content_type}")
    fmt = normalize_audio_format(content_type)
    _validate_size(data, max_bytes=max_bytes)
    return EncodedAudio(
        data=data,
        format=fmt.format,
        suffix=fmt.suffix,
        media_type=fmt.media_type,
    )
