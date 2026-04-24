import json

from app.services.tool_presentation import derive_tool_presentation


def test_get_skill_presentation_is_transcript_read_skill():
    surface, summary = derive_tool_presentation(
        tool_name="get_skill",
        arguments={"skill_id": "widgets"},
        result=json.dumps({"id": "widgets", "name": "Widgets", "content": "# Widgets\nUse this skill."}, ensure_ascii=False),
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
        "preview_text": "# Widgets",
    }


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
