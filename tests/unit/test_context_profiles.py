from __future__ import annotations

from types import SimpleNamespace

from app.agent.context_profiles import (
    get_context_profile,
    resolve_chat_live_history_policy,
    resolve_context_profile,
    resolve_native_context_policy,
    trim_messages_to_token_budget,
    trim_messages_to_recent_turns,
)


def _session(mode: str) -> SimpleNamespace:
    return SimpleNamespace(metadata_={"plan_mode": mode})


def test_resolve_context_profile_maps_plan_modes():
    assert resolve_context_profile(session=_session("planning")).name == "planning"
    assert resolve_context_profile(session=_session("executing")).name == "executing"
    assert resolve_context_profile(session=_session("blocked")).name == "executing"
    assert resolve_context_profile(session=_session("done")).name == "executing"


def test_resolve_context_profile_maps_origins():
    assert resolve_context_profile(origin="heartbeat").name == "heartbeat"
    assert resolve_context_profile(origin="task").name == "task_recent"
    assert resolve_context_profile(origin="subagent").name == "task_none"
    assert resolve_context_profile(origin="hygiene").name == "task_none"
    assert resolve_context_profile(origin="chat").name == "chat_standard"


def test_native_context_policy_defaults_to_standard():
    assert resolve_native_context_policy() == "standard"
    profile = resolve_context_profile(origin="chat")
    assert profile.name == "chat_standard"
    assert profile.live_history_strategy == "token_fit"
    assert profile.live_history_budget_ratio == 0.45
    assert profile.allow_channel_index_segments is False
    assert profile.allow_channel_workspace is False
    assert profile.allow_workspace_rag is True
    assert profile.allow_skill_index is True
    assert profile.section_index_verbosity_default == "standard"


def test_native_context_policy_channel_override():
    channel = SimpleNamespace(config={"native_context_policy": "rich"})
    assert resolve_native_context_policy(channel=channel) == "rich"
    assert resolve_context_profile(origin="chat", channel=channel).name == "chat_rich"


def test_native_context_policy_manual_uses_standard_profile_with_manual_budget():
    channel = SimpleNamespace(config={
        "native_context_policy": "manual",
        "native_context_live_history_ratio": 0.33,
        "native_context_min_recent_turns": 4,
    })
    profile = resolve_context_profile(origin="chat", channel=channel)
    assert resolve_native_context_policy(channel=channel) == "manual"
    assert profile.name == "chat_standard"
    assert resolve_chat_live_history_policy(profile, channel=channel) == (0.33, 4)


def test_native_context_policy_global_default(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "NATIVE_CONTEXT_POLICY_DEFAULT", "standard")
    assert resolve_context_profile(origin="chat").name == "chat_standard"


def test_task_none_overrides_keep_iterations():
    """Hygiene / subagent runs sweep many channels per turn — the profile
    must keep more tool-result iterations than the short-chat default."""
    assert get_context_profile("task_none").keep_iterations_override == 8


def test_chat_profile_inherits_global_keep_iterations():
    """Chat profile uses a compact native-loop observation window."""
    assert get_context_profile("chat_lean").keep_iterations_override == 2


def test_trim_messages_to_recent_turns_preserves_system_prefix():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
    ]

    trimmed = trim_messages_to_recent_turns(messages, 2)

    assert trimmed == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
    ]


def test_trim_messages_to_recent_turns_zero_keeps_only_system():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
    ]

    assert trim_messages_to_recent_turns(messages, 0) == [
        {"role": "system", "content": "system"},
    ]


def test_trim_messages_to_token_budget_keeps_many_short_turns():
    messages = [{"role": "system", "content": "system"}]
    for i in range(12):
        messages.extend([
            {"role": "user", "content": f"u{i}"},
            {"role": "assistant", "content": f"a{i}"},
        ])

    trimmed = trim_messages_to_token_budget(messages, max_tokens=1000, min_recent_turns=2)

    assert trimmed == messages


def test_trim_messages_to_token_budget_trims_oldest_complete_turns():
    messages = [{"role": "system", "content": "system"}]
    for i in range(6):
        messages.extend([
            {"role": "user", "content": f"user {i} " + ("x" * 100)},
            {"role": "assistant", "content": f"assistant {i} " + ("y" * 100)},
        ])

    trimmed = trim_messages_to_token_budget(messages, max_tokens=80, min_recent_turns=2)
    contents = [m["content"] for m in trimmed if m["role"] in {"user", "assistant"}]

    assert contents[0].startswith("user 4")
    assert contents[-1].startswith("assistant 5")
    assert all(not content.startswith("user 0") for content in contents)


def test_restricted_profiles_expose_context_profile_note_as_optional_injection():
    assert "context_profile_note" not in get_context_profile("chat_lean").optional_static_injections
    assert "context_profile_note" not in get_context_profile("chat_standard").optional_static_injections
    assert "context_profile_note" not in get_context_profile("chat_rich").optional_static_injections
    assert "context_profile_note" in get_context_profile("planning").optional_static_injections
    assert "context_profile_note" in get_context_profile("executing").optional_static_injections
    assert "context_profile_note" in get_context_profile("task_recent").optional_static_injections
    assert "context_profile_note" in get_context_profile("task_none").optional_static_injections
    assert "context_profile_note" in get_context_profile("heartbeat").optional_static_injections


def test_bot_knowledge_base_profile_admission_is_explicit():
    assert get_context_profile("chat_lean").allow_bot_knowledge_base is False
    assert get_context_profile("chat_standard").allow_bot_knowledge_base is True
    assert get_context_profile("chat_rich").allow_bot_knowledge_base is True
    assert get_context_profile("executing").allow_bot_knowledge_base is True
    assert get_context_profile("planning").allow_bot_knowledge_base is False
    assert get_context_profile("task_recent").allow_bot_knowledge_base is False
    assert get_context_profile("task_none").allow_bot_knowledge_base is False
    assert get_context_profile("heartbeat").allow_bot_knowledge_base is False
    assert "bot_knowledge_base" not in get_context_profile("chat_lean").optional_static_injections
    assert "bot_knowledge_base" in get_context_profile("chat_standard").optional_static_injections
    assert "bot_knowledge_base" in get_context_profile("chat_rich").optional_static_injections
    assert "bot_knowledge_base" in get_context_profile("executing").optional_static_injections


def test_heartbeat_profile_suppresses_ambient_skill_index():
    assert get_context_profile("chat_lean").allow_skill_index is False
    assert get_context_profile("chat_standard").allow_skill_index is True
    assert get_context_profile("chat_rich").allow_skill_index is True
    assert get_context_profile("executing").allow_skill_index is True
    assert get_context_profile("heartbeat").allow_skill_index is False


def test_profile_policy_matrix_for_restricted_origins():
    expected = {
        "chat_lean": (None, False, False, False),
        "chat_standard": (None, False, True, True),
        "chat_rich": (None, False, True, True),
        "planning": (2, True, True, False),
        "executing": (4, True, True, True),
        "task_recent": (4, True, True, False),
        "task_none": (0, False, False, False),
        "heartbeat": (0, False, False, False),
    }

    for name, (
        live_history_turns,
        allow_tool_index,
        allow_skill_index,
        allow_workspace_rag,
    ) in expected.items():
        profile = get_context_profile(name)
        assert profile.live_history_turns == live_history_turns
        assert profile.allow_tool_index is allow_tool_index
        assert profile.allow_skill_index is allow_skill_index
        assert profile.allow_workspace_rag is allow_workspace_rag
