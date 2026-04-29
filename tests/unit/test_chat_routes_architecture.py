"""Architecture guards for chat route enqueue orchestration."""

from __future__ import annotations

import ast
import inspect
import textwrap


def test_enqueue_chat_turn_stays_stage_only() -> None:
    import app.routers.chat._routes as routes

    source = textwrap.dedent(inspect.getsource(routes._enqueue_chat_turn))
    tree = ast.parse(source)
    fn = tree.body[0]

    assert isinstance(fn, ast.AsyncFunctionDef)
    assert fn.end_lineno - fn.lineno + 1 <= 80
    for helper in (
        "_prepare_chat_input",
        "_maybe_enqueue_sub_session_chat",
        "_resolve_normal_chat_run",
        "_maybe_short_circuit_normal_chat",
        "_prepare_attachment_records",
        "_start_or_queue_normal_turn",
        "_mark_attention_item_responded",
    ):
        assert helper in source
    referenced_names = {
        node.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Name)
    }
    for forbidden in (
        "decode_base64_audio",
        "_create_attachments_from_metadata",
        "start_turn",
        "SessionBusyError",
        "TaskModel",
        "MessageModel",
        "store_passive_message",
        "_channel_throttled",
        "_settings",
    ):
        assert forbidden not in referenced_names
