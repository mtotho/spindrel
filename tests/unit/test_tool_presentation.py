import json

from app.services.tool_presentation import derive_tool_presentation


def test_get_skill_presentation_is_transcript_read_skill():
    surface, summary = derive_tool_presentation(
        tool_name="get_skill",
        arguments={"skill_id": "widgets"},
        result=json.dumps(
            {
                "id": "widgets",
                "name": "Widgets",
                "description": "How to build, pin, and style dashboard widgets",
                "content": "# Widgets\nUse this skill.",
            },
            ensure_ascii=False,
        ),
        envelope={
            "content_type": "text/markdown",
            "plain_body": "# Widgets",
            "body": "# Widgets\nUse this skill.",
            "display": "inline",
        },
    )

    assert surface == "transcript"
    assert summary == {
        "kind": "read",
        "subject_type": "skill",
        "label": "Loaded skill",
        "target_id": "widgets",
        "target_label": "Widgets",
        "preview_text": "How to build, pin, and style dashboard widgets",
    }


def test_get_skill_presentation_skips_heading_when_no_description():
    # Auto-injected synthetic get_skill result with no description field —
    # preview should pick the first non-heading paragraph, not echo the name.
    surface, summary = derive_tool_presentation(
        tool_name="get_skill",
        arguments={"skill_id": "workspace_files"},
        result="# Workspace Files\n\nGuide for using the file tool vs exec_command.",
        envelope=None,
    )

    assert surface == "transcript"
    assert summary["target_label"] == "Workspace Files"
    assert summary.get("preview_text") == "Guide for using the file tool vs exec_command."


def test_get_skill_presentation_drops_preview_when_it_matches_label():
    # Envelope body is just "# Widgets" with no description — preview should
    # not duplicate target_label.
    surface, summary = derive_tool_presentation(
        tool_name="get_skill",
        arguments={"skill_id": "widgets"},
        result=json.dumps({"id": "widgets", "name": "Widgets", "content": "# Widgets"}, ensure_ascii=False),
        envelope={
            "content_type": "text/markdown",
            "plain_body": "# Widgets",
            "body": "# Widgets",
            "display": "inline",
        },
    )

    assert surface == "transcript"
    assert summary["target_label"] == "Widgets"
    assert "preview_text" not in summary


def test_get_skill_presentation_shows_already_loaded_result():
    surface, summary = derive_tool_presentation(
        tool_name="get_skill",
        arguments={"skill_id": "widgets"},
        result=json.dumps(
            {
                "id": "widgets",
                "name": "Widgets",
                "already_loaded": True,
                "message": "Skill already resident in context.",
            },
            ensure_ascii=False,
        ),
        envelope=None,
    )

    assert surface == "transcript"
    assert summary == {
        "kind": "result",
        "subject_type": "skill",
        "label": "Skill already loaded",
        "target_id": "widgets",
        "target_label": "Widgets",
        "preview_text": "Skill already resident in context.",
    }


def test_get_skill_presentation_extracts_name_from_raw_markdown_body():
    # Auto-injected synthetic get_skill() calls pass the skill body as raw
    # markdown (not JSON). Loader convention is ``# Name\n\nbody``, so the
    # presentation layer recovers the display name from the first heading.
    surface, summary = derive_tool_presentation(
        tool_name="get_skill",
        arguments={"skill_id": "workspace_files"},
        result="# Workspace Files\n\nGuide for using the file tool...",
        envelope=None,
    )

    assert surface == "transcript"
    assert summary["subject_type"] == "skill"
    assert summary["target_id"] == "workspace_files"
    assert summary["target_label"] == "Workspace Files"


def test_get_skill_presentation_falls_back_to_id_when_no_name_anywhere():
    surface, summary = derive_tool_presentation(
        tool_name="get_skill",
        arguments={"skill_id": "workspace_files"},
        result="plain body with no leading heading",
        envelope=None,
    )

    assert surface == "transcript"
    assert summary["target_id"] == "workspace_files"
    assert summary["target_label"] == "workspace_files"


def test_get_skill_list_presentation_shows_count():
    surface, summary = derive_tool_presentation(
        tool_name="get_skill_list",
        arguments={},
        result=json.dumps({"count": 42, "skills": []}, ensure_ascii=False),
        envelope=None,
    )

    assert surface == "transcript"
    assert summary == {
        "kind": "lookup",
        "subject_type": "skill",
        "label": "Listed skills",
        "preview_text": "42 skills",
    }


def test_get_skill_list_presentation_handles_single():
    surface, summary = derive_tool_presentation(
        tool_name="get_skill_list",
        arguments={},
        result=json.dumps({"count": 1, "skills": []}, ensure_ascii=False),
        envelope=None,
    )

    assert surface == "transcript"
    assert summary["preview_text"] == "1 skill"


def test_prune_enrolled_skills_presentation_shows_counts():
    surface, summary = derive_tool_presentation(
        tool_name="prune_enrolled_skills",
        arguments={"skill_ids": ["foo", "bar", "baz"]},
        result=json.dumps(
            {"removed": 2, "archived": 1, "blocked": 0, "message": "Pruned 2 enrollment(s). archived 1 authored skill(s)."},
            ensure_ascii=False,
        ),
        envelope=None,
    )

    assert surface == "transcript"
    assert summary == {
        "kind": "write",
        "subject_type": "skill",
        "label": "Pruned skills",
        "preview_text": "unenrolled 2, archived 1",
    }


def test_prune_enrolled_skills_presentation_no_changes():
    surface, summary = derive_tool_presentation(
        tool_name="prune_enrolled_skills",
        arguments={"skill_ids": ["foo"]},
        result=json.dumps(
            {"removed": 0, "archived": 0, "blocked": 0, "message": "No matching enrollments to remove (1 requested)."},
            ensure_ascii=False,
        ),
        envelope=None,
    )

    assert surface == "transcript"
    assert summary["preview_text"] == "no changes"


def test_manage_bot_skill_create_presentation():
    surface, summary = derive_tool_presentation(
        tool_name="manage_bot_skill",
        arguments={"action": "create", "name": "arch-tips", "title": "Arch Linux Tips"},
        result=json.dumps(
            {"ok": True, "id": "bots/bot-1/arch-tips", "embedded": True, "message": "Skill created."},
            ensure_ascii=False,
        ),
        envelope=None,
    )

    assert surface == "transcript"
    assert summary == {
        "kind": "write",
        "subject_type": "skill",
        "label": "Created skill",
        "target_id": "bots/bot-1/arch-tips",
        "target_label": "Arch Linux Tips",
    }


def test_manage_bot_skill_list_presentation():
    surface, summary = derive_tool_presentation(
        tool_name="manage_bot_skill",
        arguments={"action": "list", "limit": 20},
        result=json.dumps(
            {"skills": [{"id": "x", "name": "X"}, {"id": "y", "name": "Y"}], "total": 5, "limit": 20, "offset": 0},
            ensure_ascii=False,
        ),
        envelope=None,
    )

    assert surface == "transcript"
    assert summary == {
        "kind": "lookup",
        "subject_type": "skill",
        "label": "Listed authored skills",
        "preview_text": "5 skills",
    }


def test_manage_bot_skill_get_single_presentation():
    surface, summary = derive_tool_presentation(
        tool_name="manage_bot_skill",
        arguments={"action": "get", "name": "arch-tips"},
        result=json.dumps(
            {"id": "bots/bot-1/arch-tips", "name": "Arch Linux Tips", "content": "body"},
            ensure_ascii=False,
        ),
        envelope=None,
    )

    assert surface == "transcript"
    assert summary == {
        "kind": "read",
        "subject_type": "skill",
        "label": "Loaded skill",
        "target_id": "bots/bot-1/arch-tips",
        "target_label": "Arch Linux Tips",
    }


def test_manage_bot_skill_get_batch_presentation():
    surface, summary = derive_tool_presentation(
        tool_name="manage_bot_skill",
        arguments={"action": "get", "names": ["a", "b", "c"]},
        result=json.dumps(
            {"skills": [{"id": "bots/bot-1/a"}, {"id": "bots/bot-1/b"}], "missing": ["c"]},
            ensure_ascii=False,
        ),
        envelope=None,
    )

    assert surface == "transcript"
    assert summary == {
        "kind": "read",
        "subject_type": "skill",
        "label": "Loaded 2 skill(s)",
        "preview_text": "1 missing",
    }


def test_manage_bot_skill_delete_presentation():
    surface, summary = derive_tool_presentation(
        tool_name="manage_bot_skill",
        arguments={"action": "delete", "name": "old-skill"},
        result=json.dumps(
            {"ok": True, "id": "bots/bot-1/old-skill", "message": "archived"},
            ensure_ascii=False,
        ),
        envelope=None,
    )

    assert surface == "transcript"
    assert summary == {
        "kind": "write",
        "subject_type": "skill",
        "label": "Archived skill",
        "target_id": "bots/bot-1/old-skill",
        "target_label": "bots/bot-1/old-skill",
    }


def test_manage_bot_skill_restore_presentation():
    surface, summary = derive_tool_presentation(
        tool_name="manage_bot_skill",
        arguments={"action": "restore", "name": "old-skill"},
        result=json.dumps(
            {"ok": True, "id": "bots/bot-1/old-skill", "message": "restored"},
            ensure_ascii=False,
        ),
        envelope=None,
    )

    assert surface == "transcript"
    assert summary["label"] == "Restored skill"
    assert summary["kind"] == "write"


def test_manage_bot_skill_get_script_presentation():
    surface, summary = derive_tool_presentation(
        tool_name="manage_bot_skill",
        arguments={"action": "get_script", "name": "arch-tips", "script_name": "apply_patch"},
        result=json.dumps(
            {
                "ok": True,
                "id": "bots/bot-1/arch-tips",
                "script_name": "apply_patch",
                "script_description": "apply patch",
                "script_body": "print('hi')",
            },
            ensure_ascii=False,
        ),
        envelope=None,
    )

    assert surface == "transcript"
    assert summary["kind"] == "read"
    assert summary["label"] == "Loaded skill script"
    assert summary["target_id"] == "bots/bot-1/arch-tips"
    assert summary["preview_text"] == "apply_patch"


def test_manage_bot_skill_add_script_presentation():
    surface, summary = derive_tool_presentation(
        tool_name="manage_bot_skill",
        arguments={"action": "add_script", "name": "arch-tips", "script_name": "run_repair"},
        result=json.dumps({"ok": True, "id": "bots/bot-1/arch-tips"}, ensure_ascii=False),
        envelope=None,
    )

    assert surface == "transcript"
    assert summary["kind"] == "write"
    assert summary["label"] == "Added skill script"
    assert summary["preview_text"] == "run_repair"


def test_manage_bot_skill_error_presentation_uses_generic_error_branch():
    surface, summary = derive_tool_presentation(
        tool_name="manage_bot_skill",
        arguments={"action": "create"},
        result=json.dumps({"error": "name is required for create."}, ensure_ascii=False),
        envelope=None,
    )

    # Errors go through the generic error branch (before the dispatch).
    assert surface == "transcript"
    assert summary["kind"] == "error"
    assert summary["error"] == "name is required for create."


def test_file_edit_presentation_uses_diff_summary():
    diff_body = "\n".join([
        "--- a/index.html",
        "+++ b/index.html",
        "@@ -1,2 +1,2 @@",
        "-old line",
        "+new line",
        " same line",
    ])
    surface, summary = derive_tool_presentation(
        tool_name="file",
        arguments={"operation": "edit", "path": "index.html"},
        result=json.dumps(
            {
                "_envelope": {
                    "content_type": "application/vnd.spindrel.diff+text",
                    "body": diff_body,
                    "plain_body": "Edited index.html: +1 −1 lines (1 replacement)",
                    "display": "inline",
                }
            },
            ensure_ascii=False,
        ),
        envelope={
            "content_type": "application/vnd.spindrel.diff+text",
            "body": diff_body,
            "plain_body": "Edited index.html: +1 −1 lines (1 replacement)",
            "display": "inline",
        },
    )

    assert surface == "rich_result"
    assert summary == {
        "kind": "diff",
        "subject_type": "file",
        "label": "Edited index.html: +1 -1 lines (1 replacement)",
        "path": "index.html",
        "diff_stats": {"additions": 1, "deletions": 1},
    }


def test_widget_envelope_presentation_prefers_widget_surface():
    surface, summary = derive_tool_presentation(
        tool_name="emit_html_widget",
        arguments={"title": "Kitchen"},
        result=json.dumps({"ok": True}, ensure_ascii=False),
        envelope={
            "content_type": "application/vnd.spindrel.html+interactive",
            "display": "inline",
            "display_label": "Kitchen",
            "plain_body": "Kitchen widget",
        },
    )

    assert surface == "widget"
    assert summary == {
        "kind": "result",
        "subject_type": "widget",
        "label": "Widget available",
        "target_label": "Kitchen",
    }


def test_widget_error_presentation_preserves_widget_surface():
    surface, summary = derive_tool_presentation(
        tool_name="web_search",
        arguments={"q": "weather in Lambertville NJ today"},
        result=json.dumps({"error": "Cannot connect to SearXNG"}, ensure_ascii=False),
        envelope={
            "content_type": "application/vnd.spindrel.html+interactive",
            "display": "inline",
            "display_label": "Web search",
            "plain_body": "Web search",
        },
    )

    assert surface == "widget"
    assert summary == {
        "kind": "error",
        "subject_type": "widget",
        "label": "Widget unavailable",
        "target_label": "Web search",
        "error": "Cannot connect to SearXNG",
    }


def test_time_presentation_keeps_inline_preview_text():
    surface, summary = derive_tool_presentation(
        tool_name="get_current_local_time",
        arguments={},
        result="2026-04-22 14:05 EDT",
        envelope={
            "content_type": "text/plain",
            "plain_body": "2026-04-22 14:05 EDT",
            "body": "2026-04-22 14:05 EDT",
            "display": "badge",
        },
    )

    assert surface == "transcript"
    assert summary == {
        "kind": "result",
        "subject_type": "generic",
        "label": "Got current local time",
        "preview_text": "2026-04-22 14:05 EDT",
    }
