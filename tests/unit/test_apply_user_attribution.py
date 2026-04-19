"""Tests for the attribution composer and ``_apply_user_attribution``.

Locks in the ingest contract: integrations emit clean content + metadata, and
the assembly layer composes the LLM-facing ``[Name]:`` / ``[Name (<@U…>)]:``
prefix. See ``docs/integrations/message-ingest-contract.md``.
"""
from app.agent.message_formatting import (
    compose_attribution_prefix,
    compose_thread_context_block,
)
from app.routers.chat._context import (
    _apply_user_attribution,
    _inject_thread_context_blocks,
)


class TestComposeAttributionPrefix:
    def test_name_only_when_no_mention_token(self):
        assert (
            compose_attribution_prefix({"sender_display_name": "Olivia"})
            == "[Olivia]:"
        )

    def test_includes_mention_token_when_provided(self):
        assert (
            compose_attribution_prefix({
                "sender_display_name": "Olivia",
                "mention_token": "<@U06STGBF4Q0>",
            })
            == "[Olivia (<@U06STGBF4Q0>)]:"
        )

    def test_empty_mention_token_falls_back_to_name_only(self):
        assert (
            compose_attribution_prefix({
                "sender_display_name": "Olivia",
                "mention_token": "",
            })
            == "[Olivia]:"
        )

    def test_none_meta_returns_none(self):
        assert compose_attribution_prefix(None) is None

    def test_missing_sender_display_name_returns_none(self):
        assert compose_attribution_prefix({"source": "slack"}) is None


class TestApplyUserAttribution:
    def test_prepends_name_only_prefix(self):
        msgs = [
            {"role": "user", "content": "hello",
             "_metadata": {"sender_display_name": "Alice", "sender_type": "human"}},
        ]
        _apply_user_attribution(msgs)
        assert msgs[0]["content"] == "[Alice]: hello"

    def test_prepends_mention_token_prefix_when_metadata_has_it(self):
        msgs = [
            {"role": "user", "content": "testing from slack",
             "_metadata": {
                 "source": "slack",
                 "sender_display_name": "Olivia",
                 "mention_token": "<@U06STGBF4Q0>",
             }},
        ]
        _apply_user_attribution(msgs)
        assert msgs[0]["content"] == "[Olivia (<@U06STGBF4Q0>)]: testing from slack"

    def test_idempotent_on_exact_prefix(self):
        msgs = [
            {"role": "user", "content": "[Alice]: hello",
             "_metadata": {"sender_display_name": "Alice"}},
        ]
        _apply_user_attribution(msgs)
        assert msgs[0]["content"] == "[Alice]: hello"

    def test_idempotent_with_mention_token_upgrade(self):
        """A legacy [Name]: prefix is NOT re-prefixed when mention_token is added later."""
        msgs = [
            {"role": "user", "content": "[Olivia]: hi",
             "_metadata": {
                 "sender_display_name": "Olivia",
                 "mention_token": "<@U06>",
             }},
        ]
        _apply_user_attribution(msgs)
        # Does not double-prefix — historic rows with the bare name-only
        # prefix stay as-is rather than getting a second header stacked on top.
        assert msgs[0]["content"] == "[Olivia]: hi"

    def test_skips_assistant_messages(self):
        msgs = [
            {"role": "assistant", "content": "sure",
             "_metadata": {"sender_display_name": "Alice"}},
        ]
        _apply_user_attribution(msgs)
        assert msgs[0]["content"] == "sure"

    def test_skips_multimodal_content(self):
        """Image attachments arrive as a list of content blocks — leave untouched."""
        msgs = [
            {"role": "user",
             "content": [{"type": "text", "text": "hi"}, {"type": "image_url", "url": "..."}],
             "_metadata": {"sender_display_name": "Alice"}},
        ]
        _apply_user_attribution(msgs)
        assert isinstance(msgs[0]["content"], list)

    def test_skips_when_no_sender_display_name(self):
        msgs = [
            {"role": "user", "content": "hello",
             "_metadata": {"source": "web"}},
        ]
        _apply_user_attribution(msgs)
        assert msgs[0]["content"] == "hello"

    def test_empty_message_list(self):
        msgs: list[dict] = []
        _apply_user_attribution(msgs)
        assert msgs == []


class TestComposeThreadContextBlock:
    def test_returns_block_verbatim_when_present(self):
        block = "[Thread context — prior messages]\n- Alice: hi"
        assert compose_thread_context_block({"thread_context": block}) == block

    def test_strips_surrounding_whitespace(self):
        assert (
            compose_thread_context_block({"thread_context": "\n\nsummary\n\n"})
            == "summary"
        )

    def test_returns_none_when_missing(self):
        assert compose_thread_context_block({}) is None
        assert compose_thread_context_block(None) is None

    def test_returns_none_when_empty_string(self):
        assert compose_thread_context_block({"thread_context": "   "}) is None


class TestInjectThreadContextBlocks:
    def test_inserts_system_block_before_user_turn(self):
        msgs = [
            {"role": "user", "content": "question",
             "_metadata": {
                 "sender_display_name": "Alice",
                 "thread_context": "[Thread context]\n- prior line",
             }},
        ]
        _inject_thread_context_blocks(msgs)
        assert len(msgs) == 2
        assert msgs[0] == {"role": "system", "content": "[Thread context]\n- prior line"}
        assert msgs[1]["role"] == "user"

    def test_does_nothing_when_no_thread_context(self):
        msgs = [
            {"role": "user", "content": "q",
             "_metadata": {"sender_display_name": "Alice"}},
        ]
        _inject_thread_context_blocks(msgs)
        assert len(msgs) == 1

    def test_handles_multiple_user_turns_independently(self):
        msgs = [
            {"role": "user", "content": "first",
             "_metadata": {"sender_display_name": "A",
                           "thread_context": "summary 1"}},
            {"role": "assistant", "content": "response"},
            {"role": "user", "content": "second",
             "_metadata": {"sender_display_name": "A",
                           "thread_context": "summary 2"}},
        ]
        _inject_thread_context_blocks(msgs)
        assert [m.get("role") for m in msgs] == [
            "system", "user", "assistant", "system", "user",
        ]
        assert msgs[0]["content"] == "summary 1"
        assert msgs[3]["content"] == "summary 2"

    def test_skips_assistant_messages(self):
        msgs = [
            {"role": "assistant", "content": "reply",
             "_metadata": {"thread_context": "ignored"}},
        ]
        _inject_thread_context_blocks(msgs)
        assert len(msgs) == 1
