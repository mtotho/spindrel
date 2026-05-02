from __future__ import annotations

from types import SimpleNamespace

from app.agent.context_profiles import (
    get_context_profile,
    resolve_context_profile,
    resolve_native_context_policy,
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
    assert resolve_context_profile(origin="chat").name == "chat_lean"


def test_native_context_policy_defaults_to_lean():
    assert resolve_native_context_policy() == "lean"
    profile = resolve_context_profile(origin="chat")
    assert profile.name == "chat_lean"
    assert profile.live_history_turns == 4
    assert profile.allow_channel_index_segments is False
    assert profile.allow_channel_workspace is False
    assert profile.allow_workspace_rag is False
    assert profile.allow_skill_index is False
    assert profile.section_index_verbosity_default == "compact"


def test_native_context_policy_channel_override():
    channel = SimpleNamespace(config={"native_context_policy": "rich"})
    assert resolve_native_context_policy(channel=channel) == "rich"
    assert resolve_context_profile(origin="chat", channel=channel).name == "chat_rich"


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
        "chat_lean": (4, False, False, False),
        "chat_standard": (8, False, True, True),
        "chat_rich": (8, False, True, True),
        "planning": (2, True, True, False),
        "executing": (4, True, True, True),
        "task_recent": (None, True, True, False),
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
