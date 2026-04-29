from app.services.agent_harnesses.tool_results import build_text_tool_result


def test_text_tool_result_can_describe_native_file_write():
    envelope, summary = build_text_tool_result(
        tool_name="Write",
        tool_call_id="tu_write",
        body="<html></html>\n",
        label="Wrote index.html",
        summary_kind="write",
        subject_type="file",
        path="index.html",
        preview_text=None,
    )

    assert envelope["content_type"] == "text/plain"
    assert envelope["body"] == "<html></html>"
    assert envelope["plain_body"] == "Wrote index.html"
    assert envelope["display_label"] == "index.html"
    assert envelope["tool_call_id"] == "tu_write"
    assert summary == {
        "kind": "write",
        "subject_type": "file",
        "label": "Wrote index.html",
        "path": "index.html",
    }


def test_text_tool_result_keeps_generic_preview_default():
    _, summary = build_text_tool_result(
        tool_name="Bash",
        body="stdout\n",
        label="Ran command",
    )

    assert summary == {
        "kind": "result",
        "subject_type": "generic",
        "label": "Ran command",
        "preview_text": "Ran command",
    }
