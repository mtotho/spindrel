from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def _reset_stt_provider_cache():
    import app.stt.provider as stt_provider

    stt_provider._provider = None
    stt_provider._provider_key = None
    yield
    stt_provider._provider = None
    stt_provider._provider_key = None


def test_openai_stt_requires_provider_id(monkeypatch):
    import app.stt.provider as stt_provider

    monkeypatch.setattr(settings, "STT_PROVIDER", "openai")
    monkeypatch.setattr(settings, "STT_MODEL_PROVIDER_ID", "")

    with pytest.raises(RuntimeError, match="STT_MODEL_PROVIDER_ID"):
        stt_provider.get_provider()


def test_openai_stt_rejects_subscription_provider(monkeypatch, tmp_path):
    import app.stt.provider as stt_provider
    import app.services.providers as llm_providers

    monkeypatch.setattr(settings, "STT_PROVIDER", "openai")
    monkeypatch.setattr(settings, "STT_MODEL_PROVIDER_ID", "chatgpt-sub")
    monkeypatch.setattr(settings, "STT_MODEL", "gpt-4o-mini-transcribe")
    monkeypatch.setattr(
        llm_providers,
        "get_provider",
        lambda provider_id: SimpleNamespace(
            id=provider_id,
            provider_type="openai-subscription",
            api_key=None,
            base_url=None,
            config={},
        ),
    )

    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake wav")
    provider = stt_provider.get_provider()
    with pytest.raises(RuntimeError, match="ChatGPT subscription providers cannot be used"):
        provider.transcribe(str(audio_path))


def test_openai_stt_uses_provider_row_and_default_model(monkeypatch, tmp_path):
    import app.stt.provider as stt_provider
    import app.services.providers as llm_providers

    calls: list[dict] = []

    class FakeTranscriptions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(text="  hello voice  ")

    class FakeOpenAI:
        def __init__(self, **kwargs):
            calls.append({"client": kwargs})
            self.audio = SimpleNamespace(transcriptions=FakeTranscriptions())

    audio_path = tmp_path / "voice.webm"
    audio_path.write_bytes(b"fake webm")

    monkeypatch.setattr(settings, "STT_PROVIDER", "openai")
    monkeypatch.setattr(settings, "STT_MODEL_PROVIDER_ID", "openai-api")
    monkeypatch.setattr(settings, "STT_MODEL", "")
    monkeypatch.setattr(settings, "WHISPER_LANGUAGE", "en")
    monkeypatch.setattr(stt_provider, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(
        llm_providers,
        "get_provider",
        lambda provider_id: SimpleNamespace(
            id=provider_id,
            provider_type="openai",
            api_key="sk-test",
            base_url="https://api.openai.test/v1",
            config={"extra_headers": {"OpenAI-Organization": "org_test"}},
        ),
    )

    text = stt_provider.transcribe(str(audio_path))

    assert text == "hello voice"
    assert calls[0]["client"]["api_key"] == "sk-test"
    assert calls[0]["client"]["base_url"] == "https://api.openai.test/v1"
    assert calls[0]["client"]["default_headers"] == {"OpenAI-Organization": "org_test"}
    assert calls[1]["model"] == "gpt-4o-mini-transcribe"
    assert calls[1]["language"] == "en"
    assert calls[1]["file"].name == str(audio_path)
