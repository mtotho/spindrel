from __future__ import annotations

from types import SimpleNamespace

from app.agent.context_profiles import get_context_profile, resolve_context_profile, trim_messages_to_recent_turns


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
    assert resolve_context_profile(origin="chat").name == "chat"


def test_task_none_overrides_keep_iterations():
    """Hygiene / subagent runs sweep many channels per turn — the profile
    must keep more tool-result iterations than the short-chat default."""
    assert get_context_profile("task_none").keep_iterations_override == 8


def test_chat_profile_inherits_global_keep_iterations():
    """Chat profile must NOT override — it uses the global setting (2) so
    normal turns stay compact."""
    assert get_context_profile("chat").keep_iterations_override is None


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
    assert "context_profile_note" not in get_context_profile("chat").optional_static_injections
    assert "context_profile_note" in get_context_profile("planning").optional_static_injections
    assert "context_profile_note" in get_context_profile("executing").optional_static_injections
    assert "context_profile_note" in get_context_profile("task_recent").optional_static_injections
    assert "context_profile_note" in get_context_profile("task_none").optional_static_injections
    assert "context_profile_note" in get_context_profile("heartbeat").optional_static_injections


def test_bot_knowledge_base_profile_admission_is_explicit():
    assert get_context_profile("chat").allow_bot_knowledge_base is True
    assert get_context_profile("executing").allow_bot_knowledge_base is True
    assert get_context_profile("planning").allow_bot_knowledge_base is False
    assert get_context_profile("task_recent").allow_bot_knowledge_base is False
    assert get_context_profile("task_none").allow_bot_knowledge_base is False
    assert get_context_profile("heartbeat").allow_bot_knowledge_base is False
    assert "bot_knowledge_base" in get_context_profile("chat").optional_static_injections
    assert "bot_knowledge_base" in get_context_profile("executing").optional_static_injections
