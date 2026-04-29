import base64

import pytest

from app.services.audio_input import (
    AudioInputError,
    decode_base64_audio,
    normalize_audio_format,
    validate_encoded_audio_file,
)


def test_decode_base64_audio_accepts_browser_webm() -> None:
    payload = base64.b64encode(b"fake webm bytes").decode("ascii")

    audio = decode_base64_audio(payload, "audio/webm;codecs=opus")

    assert audio.data == b"fake webm bytes"
    assert audio.format == "webm"
    assert audio.suffix == ".webm"
    assert audio.media_type == "audio/webm"


def test_decode_base64_audio_rejects_invalid_base64() -> None:
    with pytest.raises(AudioInputError, match="Invalid base64 audio data"):
        decode_base64_audio("not base64!!", "webm")


def test_decode_base64_audio_rejects_unsupported_suffix() -> None:
    payload = base64.b64encode(b"audio").decode("ascii")

    with pytest.raises(AudioInputError, match="Unsupported audio format"):
        decode_base64_audio(payload, "../../wav")


def test_decode_base64_audio_rejects_oversize_payload() -> None:
    payload = base64.b64encode(b"x" * 9).decode("ascii")

    with pytest.raises(AudioInputError, match="Audio too large"):
        decode_base64_audio(payload, "wav", max_bytes=8)


def test_validate_encoded_audio_file_rejects_unknown_content_type() -> None:
    with pytest.raises(AudioInputError, match="Unsupported audio content type"):
        validate_encoded_audio_file(b"audio", "application/json")


def test_normalize_audio_format_defaults_to_m4a() -> None:
    fmt = normalize_audio_format(None)

    assert fmt.format == "m4a"
    assert fmt.suffix == ".m4a"
    assert fmt.media_type == "audio/mp4"
