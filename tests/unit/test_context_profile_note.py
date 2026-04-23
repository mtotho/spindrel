from __future__ import annotations

from app.agent.context_assembly import _build_context_profile_note
from app.agent.context_profiles import get_context_profile


def test_chat_profile_has_no_runtime_note():
    assert _build_context_profile_note(
        context_profile=get_context_profile("chat"),
        inject_decisions={},
    ) is None


def test_planning_profile_note_explains_restricted_context():
    note = _build_context_profile_note(
        context_profile=get_context_profile("planning"),
        inject_decisions={
            "channel_workspace": "skipped_by_profile",
            "channel_index_segments": "skipped_by_profile",
            "workspace_rag": "skipped_by_profile",
            "bot_knowledge_base": "skipped_by_profile",
        },
    )

    assert note is not None
    assert "Current context profile: planning." in note
    assert "last 2 user-started turn(s)" in note
    assert "Recent daily logs" in note
    assert "not preloaded in this profile" in note


def test_executing_profile_note_reflects_admitted_workspace_context():
    note = _build_context_profile_note(
        context_profile=get_context_profile("executing"),
        inject_decisions={
            "channel_workspace": "admitted",
            "channel_index_segments": "admitted",
            "workspace_rag": "skipped_empty",
            "bot_knowledge_base": "skipped_empty",
        },
    )

    assert note is not None
    assert "Current context profile: executing." in note
    assert "last 4 user-started turn(s)" in note
    assert "Some workspace and knowledge context is already present in this run." in note


def test_heartbeat_profile_note_calls_out_disabled_replay():
    note = _build_context_profile_note(
        context_profile=get_context_profile("heartbeat"),
        inject_decisions={
            "channel_workspace": "skipped_by_profile",
            "channel_index_segments": "skipped_by_profile",
            "workspace_rag": "skipped_by_profile",
            "bot_knowledge_base": "skipped_by_profile",
        },
    )

    assert note is not None
    assert "Current context profile: heartbeat." in note
    assert "Live replay is disabled for this run." in note
    assert "fetch or search it explicitly" in note
