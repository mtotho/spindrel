"""Unit tests for resolve_bot_id in app.agent.bots."""
import pytest

from app.agent import bots
from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig, resolve_bot_id


def _bot(id: str, name: str) -> BotConfig:
    return BotConfig(
        id=id, name=name, model="gpt-4", system_prompt="test",
        memory=MemoryConfig(), knowledge=KnowledgeConfig(),
    )


@pytest.fixture(autouse=True)
def _clean_registry():
    backup = bots._registry.copy()
    yield
    bots._registry.clear()
    bots._registry.update(backup)


class TestResolveBotId:
    def test_exact_id(self):
        bot = _bot("google_bot", "Google Bot")
        bots._registry["google_bot"] = bot
        assert resolve_bot_id("google_bot") is bot

    def test_case_insensitive_id(self):
        bot = _bot("Google_Bot", "Google Bot")
        bots._registry["Google_Bot"] = bot
        assert resolve_bot_id("google_bot") is bot

    def test_exact_name(self):
        bot = _bot("gb", "Google Bot")
        bots._registry["gb"] = bot
        assert resolve_bot_id("Google Bot") is bot

    def test_substring_of_id(self):
        bot = _bot("google_bot", "My Bot")
        bots._registry["google_bot"] = bot
        assert resolve_bot_id("google") is bot

    def test_substring_of_name(self):
        bot = _bot("gb", "Let Me Google That For You")
        bots._registry["gb"] = bot
        assert resolve_bot_id("google") is bot

    def test_word_overlap(self):
        bot = _bot("search", "Let Me Google That")
        bots._registry["search"] = bot
        assert resolve_bot_id("let me google") is bot

    def test_none_for_no_match(self):
        bots._registry["some_bot"] = _bot("some_bot", "Some Bot")
        assert resolve_bot_id("zzz_nonexistent_zzz") is None

    def test_none_for_empty_registry(self):
        bots._registry.clear()
        assert resolve_bot_id("anything") is None

    def test_none_for_empty_hint(self):
        bots._registry["a"] = _bot("a", "A")
        assert resolve_bot_id("") is None
