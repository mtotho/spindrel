"""Unit tests for app.agent.tags — regex and resolve_tags."""
import re
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.tags import ResolvedTag, _TAG_RE, _match_skill_short_name, resolve_tags


# ---------------------------------------------------------------------------
# _TAG_RE regex tests
# ---------------------------------------------------------------------------

class TestTagRegex:
    def _find_all(self, text: str) -> list[str]:
        return [m.group(0) for m in _TAG_RE.finditer(text)]

    def test_simple_name(self):
        assert self._find_all("@mybot") == ["@mybot"]

    def test_skill_prefix(self):
        assert self._find_all("@skill:arch_linux") == ["@skill:arch_linux"]

    def test_knowledge_prefix(self):
        assert self._find_all("@knowledge:docs") == ["@knowledge:docs"]

    def test_tool_prefix(self):
        assert self._find_all("@tool:web_search") == ["@tool:web_search"]

    def test_tool_pack_prefix(self):
        assert self._find_all("@tool-pack:dev_tools") == ["@tool-pack:dev_tools"]

    def test_rejects_slack_mention(self):
        assert self._find_all("<@U12345>") == []

    def test_rejects_email(self):
        assert self._find_all("user@domain.com") == []

    def test_name_starts_with_letter(self):
        assert self._find_all("@abc") == ["@abc"]

    def test_name_starts_with_underscore(self):
        assert self._find_all("@_private") == ["@_private"]

    def test_allows_hyphens_dots_digits(self):
        assert self._find_all("@my-bot.v2") == ["@my-bot.v2"]

    def test_multiple_tags(self):
        tags = self._find_all("Hey @bot1 and @skill:helper please help")
        assert "@bot1" in tags
        assert "@skill:helper" in tags

    def test_digit_start_rejected(self):
        # Name must start with letter/underscore, not digit
        assert self._find_all("@123abc") == []

    def test_path_style_name(self):
        assert self._find_all("@integrations/marp_slides/marp_slides") == ["@integrations/marp_slides/marp_slides"]

    def test_skill_prefix_with_path(self):
        assert self._find_all("@skill:integrations/marp_slides/marp_slides") == ["@skill:integrations/marp_slides/marp_slides"]

    def test_path_in_sentence(self):
        tags = self._find_all("use @integrations/marp_slides/marp_slides for the presentation")
        assert tags == ["@integrations/marp_slides/marp_slides"]


# ---------------------------------------------------------------------------
# _match_skill_short_name
# ---------------------------------------------------------------------------

class TestMatchSkillShortName:
    def test_matches_final_segment(self):
        skills = {"integrations/marp_slides/marp_slides", "arch_linux"}
        assert _match_skill_short_name("marp_slides", skills) == "integrations/marp_slides/marp_slides"

    def test_no_match(self):
        skills = {"integrations/marp_slides/marp_slides", "arch_linux"}
        assert _match_skill_short_name("cooking", skills) is None

    def test_exact_match_not_duplicated(self):
        skills = {"arch_linux", "packages/foo/arch_linux"}
        # Ambiguous — two skills end with "arch_linux"
        assert _match_skill_short_name("arch_linux", skills) is None

    def test_plain_skill_matched(self):
        skills = {"cooking", "integrations/marp_slides/marp_slides"}
        assert _match_skill_short_name("cooking", skills) == "cooking"


# ---------------------------------------------------------------------------
# resolve_tags
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestResolveTags:
    async def test_empty_message(self):
        result = await resolve_tags("no tags here", [], [], [], "mybot", "client1")
        assert result == []

    async def test_forced_skill(self):
        result = await resolve_tags(
            "@skill:arch_linux", [], [], [], "mybot", "client1"
        )
        assert len(result) == 1
        assert result[0].tag_type == "skill"
        assert result[0].name == "arch_linux"

    async def test_forced_knowledge(self):
        result = await resolve_tags(
            "@knowledge:docs", [], [], [], "mybot", "client1"
        )
        assert len(result) == 1
        assert result[0].tag_type == "knowledge"
        assert result[0].name == "docs"

    async def test_forced_tool(self):
        result = await resolve_tags(
            "@tool:web_search", [], [], [], "mybot", "client1"
        )
        assert len(result) == 1
        assert result[0].tag_type == "tool"
        assert result[0].name == "web_search"

    async def test_unforced_skill_match(self):
        result = await resolve_tags(
            "@arch_linux", ["arch_linux"], [], [], "mybot", "client1"
        )
        assert len(result) == 1
        assert result[0].tag_type == "skill"

    async def test_unforced_tool_match(self):
        result = await resolve_tags(
            "@web_search", [], ["web_search"], [], "mybot", "client1"
        )
        assert len(result) == 1
        assert result[0].tag_type == "tool"

    async def test_unforced_client_tool_match(self):
        result = await resolve_tags(
            "@shell_exec", [], [], ["shell_exec"], "mybot", "client1"
        )
        assert len(result) == 1
        assert result[0].tag_type == "tool"

    async def test_unforced_bot_match(self):
        # _bot_registry is imported lazily inside resolve_tags from app.agent.bots
        with patch("app.agent.bots._registry", {"other_bot": object()}):
            result = await resolve_tags(
                "@other_bot", [], [], [], "mybot", "client1"
            )
            assert len(result) == 1
            assert result[0].tag_type == "bot"

    @patch("app.agent.bots._registry", {"mybot": object()})
    async def test_bot_tag_skips_self(self):
        result = await resolve_tags(
            "@mybot", [], [], [], "mybot", "client1"
        )
        # mybot is current bot, should not resolve as bot tag
        # Falls through to knowledge lookup
        assert all(t.tag_type != "bot" for t in result)

    async def test_short_name_resolves_to_full_path(self):
        result = await resolve_tags(
            "@marp_slides",
            ["integrations/marp_slides/marp_slides", "arch_linux"], [], [], "mybot", "client1"
        )
        assert len(result) == 1
        assert result[0].tag_type == "skill"
        assert result[0].name == "integrations/marp_slides/marp_slides"

    async def test_full_path_resolves(self):
        result = await resolve_tags(
            "@integrations/marp_slides/marp_slides",
            ["integrations/marp_slides/marp_slides"], [], [], "mybot", "client1"
        )
        assert len(result) == 1
        assert result[0].tag_type == "skill"
        assert result[0].name == "integrations/marp_slides/marp_slides"

    async def test_forced_skill_with_path(self):
        result = await resolve_tags(
            "@skill:integrations/marp_slides/marp_slides",
            [], [], [], "mybot", "client1"
        )
        assert len(result) == 1
        assert result[0].tag_type == "skill"
        assert result[0].name == "integrations/marp_slides/marp_slides"

    async def test_deduplicates(self):
        result = await resolve_tags(
            "@skill:foo and @skill:foo again",
            [], [], [], "mybot", "client1"
        )
        assert len(result) == 1
