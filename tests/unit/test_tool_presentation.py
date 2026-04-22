import json

from app.services.tool_presentation import derive_tool_presentation


def test_get_skill_presentation_is_transcript_read_skill():
    surface, summary = derive_tool_presentation(
        tool_name="get_skill",
        arguments={"skill_id": "widgets"},
        result=json.dumps({"id": "widgets", "name": "Widgets", "content": "..."}, ensure_ascii=False),
        envelope=None,
    )

    assert surface == "transcript"
    assert summary == {
        "kind": "read",
        "subject_type": "skill",
        "label": "Loaded skill",
        "target_id": "widgets",
        "target_label": "widgets/INDEX.md",
    }


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

    assert surface == "transcript"
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
