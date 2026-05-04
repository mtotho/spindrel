from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from app.services.knowledge_capture import (
    KnowledgeCandidate,
    extract_knowledge_candidates,
    run_knowledge_capture_for_persisted_turn,
    should_run_knowledge_capture,
    write_pending_user_knowledge_candidates,
)


def _bot(**overrides):
    data = {
        "id": "bot-1",
        "user_id": "user-1",
        "shared_workspace_id": "ws-1",
        "knowledge_capture_enabled": True,
        "integration_config": {},
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_capture_skip_rules_require_opt_in_and_owner():
    decision = should_run_knowledge_capture(
        bot=_bot(knowledge_capture_enabled=False, integration_config={}),
        channel=SimpleNamespace(config={}),
        message_metadata={"sender_type": "human"},
        run_origin="chat",
        assistant_content="This is a substantive answer with enough content to consider for capture.",
    )
    assert decision.reason == "bot_capture_disabled"

    decision = should_run_knowledge_capture(
        bot=_bot(user_id=None),
        channel=SimpleNamespace(config={}),
        message_metadata={"sender_type": "human"},
        run_origin="chat",
        assistant_content="This is a substantive answer with enough content to consider for capture.",
    )
    assert decision.reason == "ownerless_bot"


def test_capture_skip_rules_respect_channel_off_background_and_ack():
    assert should_run_knowledge_capture(
        bot=_bot(),
        channel=SimpleNamespace(config={"knowledge_capture": "off"}),
        message_metadata={"sender_type": "human"},
        run_origin="chat",
        assistant_content="This is a substantive answer with enough content to consider for capture.",
    ).reason == "channel_capture_disabled"

    assert should_run_knowledge_capture(
        bot=_bot(),
        channel=SimpleNamespace(config={}),
        message_metadata={"sender_type": "human", "context_visibility": "background"},
        run_origin="chat",
        assistant_content="This is a substantive answer with enough content to consider for capture.",
    ).reason == "background_context"

    assert should_run_knowledge_capture(
        bot=_bot(),
        channel=SimpleNamespace(config={}),
        message_metadata={"sender_type": "human"},
        run_origin="chat",
        assistant_content="Done.",
    ).reason == "tool_ack"


def test_capture_allows_enabled_human_chat_turn():
    decision = should_run_knowledge_capture(
        bot=_bot(),
        channel=SimpleNamespace(config={}),
        message_metadata={"sender_type": "human"},
        run_origin="chat",
        assistant_content="This answer contains a meaningful durable preference about how the user wants reports formatted.",
    )
    assert decision.should_run is True


@pytest.mark.asyncio
async def test_extract_knowledge_candidates_parses_json(monkeypatch):
    calls: list[dict] = []

    class FakeCompletions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            message = SimpleNamespace(content='{"candidates":[{"type":"preference","title":"Report style","body":"# Report style\\n\\nUse concise bullets.","extra":{"format":"bullets"},"confidence":1.2}]}')
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeClient:
        chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("app.services.providers.get_llm_client", lambda _provider_id: FakeClient())
    monkeypatch.setattr("app.services.providers.resolve_effective_provider", lambda *_args: "provider-1")

    candidates = await extract_knowledge_candidates(
        bot=SimpleNamespace(model="gpt-test", model_provider_id=None),
        channel=SimpleNamespace(model_override=None, model_provider_id_override=None),
        user_message=SimpleNamespace(id="user-msg", content="Please remember I like concise reports."),
        assistant_message=SimpleNamespace(id="assistant-msg", content="I will use concise bullet reports for future summaries."),
    )

    assert candidates == [
        KnowledgeCandidate(
            type="preference",
            title="Report style",
            body="# Report style\n\nUse concise bullets.\n",
            extra={"format": "bullets"},
            confidence=1.0,
            source_message_id="assistant-msg",
        )
    ]
    assert calls[0]["model"] == "gpt-test"


@pytest.mark.asyncio
async def test_extract_knowledge_candidates_uses_configured_capture_model(monkeypatch):
    calls: list[dict] = []
    provider_ids: list[str | None] = []

    class FakeCompletions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            message = SimpleNamespace(content='{"candidates":[{"title":"Durable fact","body":"# Durable fact\\n\\nKeep this.","confidence":0.5}]}')
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeClient:
        chat = SimpleNamespace(completions=FakeCompletions())

    def fake_client(provider_id):
        provider_ids.append(provider_id)
        return FakeClient()

    monkeypatch.setattr("app.services.providers.get_llm_client", fake_client)
    monkeypatch.setattr("app.services.providers.resolve_effective_provider", lambda *_args: "chat-provider")

    candidates = await extract_knowledge_candidates(
        bot=SimpleNamespace(
            model="chat-model",
            model_provider_id="chat-provider",
            integration_config={
                "knowledge_capture_model": "capture-model",
                "knowledge_capture_model_provider_id": "capture-provider",
            },
        ),
        channel=SimpleNamespace(model_override=None, model_provider_id_override=None),
        user_message=SimpleNamespace(id="user-msg", content="Remember this."),
        assistant_message=SimpleNamespace(id="assistant-msg", content="A durable answer."),
    )

    assert len(candidates) == 1
    assert calls[0]["model"] == "capture-model"
    assert provider_ids == ["capture-provider"]


@pytest.mark.asyncio
async def test_extract_knowledge_candidates_returns_empty_on_bad_json(monkeypatch):
    class FakeCompletions:
        async def create(self, **_kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))])

    class FakeClient:
        chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("app.services.providers.get_llm_client", lambda _provider_id: FakeClient())
    monkeypatch.setattr("app.services.providers.resolve_effective_provider", lambda *_args: "provider-1")

    candidates = await extract_knowledge_candidates(
        bot=SimpleNamespace(model="gpt-test", model_provider_id=None),
        channel=SimpleNamespace(model_override=None, model_provider_id_override=None),
        user_message=SimpleNamespace(id="user-msg", content="Remember this."),
        assistant_message=SimpleNamespace(id="assistant-msg", content="A durable answer."),
    )

    assert candidates == []


@pytest.mark.asyncio
async def test_write_pending_candidates_uses_user_knowledge_surface(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge_capture.shared_workspace_service.ensure_host_dirs",
        lambda workspace_id: str(tmp_path / "shared" / workspace_id),
    )

    docs = await write_pending_user_knowledge_candidates(
        bot=_bot(),
        session_id="session-1",
        source_message_id="message-1",
        candidates=[KnowledgeCandidate(title="Favorite Format", body="# Favorite Format\n\nUse concise bullets.", confidence=0.8)],
    )

    assert len(docs) == 1
    assert docs[0]["status"] == "pending_review"
    assert docs[0]["session_binding"] == {"mode": "inline", "session_id": "session-1"}
    path = tmp_path / "shared" / "ws-1" / "users" / "user-1" / "knowledge-base" / "notes" / "favorite-format.md"
    assert path.is_file()
    assert "source_message_id: message-1" in path.read_text()


@pytest.mark.asyncio
async def test_run_capture_for_persisted_turn_publishes_after_write(monkeypatch):
    channel_id = uuid.uuid4()
    user_message_id = uuid.uuid4()
    assistant_message_id = uuid.uuid4()
    session_id = uuid.uuid4()
    channel = SimpleNamespace(id=channel_id, config={})
    user_message = SimpleNamespace(id=user_message_id, metadata_={"sender_type": "human"}, content="Remember this.")
    assistant_message = SimpleNamespace(
        id=assistant_message_id,
        content="This is a durable preference that is long enough to pass the acknowledgement skip rule.",
    )

    class FakeDB:
        rolled_back = False

        async def get(self, _model, ident):
            return {
                channel_id: channel,
                user_message_id: user_message,
                assistant_message_id: assistant_message,
            }.get(ident)

        async def rollback(self):
            self.rolled_back = True

    async def fake_extract(**_kwargs):
        assert fake_db.rolled_back is True
        return [KnowledgeCandidate(title="Preference", body="# Preference\n\nUse bullets.", confidence=0.9)]

    async def fake_write(**_kwargs):
        return [{
            "entry_id": "entry-1",
            "type": "note",
            "title": "Preference",
            "frontmatter": {"confidence": 0.9},
        }]

    async def fake_reindex(**_kwargs):
        return {}

    published = []
    monkeypatch.setattr("app.services.knowledge_capture.extract_knowledge_candidates", fake_extract)
    monkeypatch.setattr("app.services.knowledge_capture.write_pending_user_knowledge_candidates", fake_write)
    monkeypatch.setattr("app.services.knowledge_capture.reindex_user_knowledge_documents", fake_reindex)
    monkeypatch.setattr("app.services.outbox_publish.publish_to_bus", lambda _channel_id, event: published.append(event) or 1)

    fake_db = FakeDB()
    docs = await run_knowledge_capture_for_persisted_turn(
        fake_db,
        bot=_bot(),
        session_id=session_id,
        channel_id=channel_id,
        first_user_message_id=user_message_id,
        last_assistant_message_id=assistant_message_id,
        run_origin="chat",
    )

    assert docs[0]["entry_id"] == "entry-1"
    assert published[0].kind.value == "knowledge_captured"
    assert published[0].payload.source_message_id == str(assistant_message_id)


@pytest.mark.asyncio
async def test_run_capture_for_persisted_turn_skips_ownerless_before_extract(monkeypatch):
    channel_id = uuid.uuid4()
    user_message_id = uuid.uuid4()
    assistant_message_id = uuid.uuid4()

    class FakeDB:
        async def get(self, _model, ident):
            if ident == channel_id:
                return SimpleNamespace(id=channel_id, config={})
            if ident == user_message_id:
                return SimpleNamespace(id=user_message_id, metadata_={"sender_type": "human"}, content="Remember this.")
            if ident == assistant_message_id:
                return SimpleNamespace(id=assistant_message_id, content="Long enough durable answer for capture eligibility.")
            return None

    async def fail_extract(**_kwargs):
        raise AssertionError("extractor should not run")

    monkeypatch.setattr("app.services.knowledge_capture.extract_knowledge_candidates", fail_extract)

    docs = await run_knowledge_capture_for_persisted_turn(
        FakeDB(),
        bot=_bot(user_id=None),
        session_id=uuid.uuid4(),
        channel_id=channel_id,
        first_user_message_id=user_message_id,
        last_assistant_message_id=assistant_message_id,
        run_origin="chat",
    )

    assert docs == []
