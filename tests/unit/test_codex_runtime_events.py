"""Notification → ChannelEventEmitter mapping for the Codex runtime.

Fixtures derived from the upstream codex app-server protocol README:
https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md
"""

from __future__ import annotations

from integrations.codex import schema
from integrations.codex.app_server import Notification
from integrations.codex.events import translate_notification


class _RecordingEmitter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def token(self, delta: str) -> None:
        self.calls.append(("token", {"delta": delta}))

    def thinking(self, delta: str) -> None:
        self.calls.append(("thinking", {"delta": delta}))

    def tool_start(self, **kwargs) -> None:
        self.calls.append(("tool_start", kwargs))

    def tool_result(self, **kwargs) -> None:
        self.calls.append(("tool_result", kwargs))


def _harness() -> tuple[_RecordingEmitter, dict, list[str], dict]:
    return _RecordingEmitter(), {}, [], {}


def test_agent_message_delta_streams_token():
    emitter, ids, parts, meta = _harness()
    # Per README: item/agentMessage/delta carries `itemId` + `delta`.
    translate_notification(
        Notification(
            method=schema.ITEM_AGENT_MESSAGE_DELTA,
            params={"itemId": "i1", "delta": "hi"},
        ),
        emit=emitter,
        tool_name_by_id=ids,
        final_text_parts=parts,
        result_meta=meta,
    )
    assert emitter.calls == [("token", {"delta": "hi"})]
    assert parts == ["hi"]


def test_reasoning_delta_streams_thinking():
    emitter, ids, parts, meta = _harness()
    translate_notification(
        Notification(method=schema.ITEM_REASONING_DELTA, params={"delta": "thought"}),
        emit=emitter,
        tool_name_by_id=ids,
        final_text_parts=parts,
        result_meta=meta,
    )
    assert emitter.calls == [("thinking", {"delta": "thought"})]


def test_item_started_command_emits_tool_start():
    emitter, ids, parts, meta = _harness()
    # Per README: item/started carries an `item` object.
    translate_notification(
        Notification(
            method=schema.ITEM_STARTED,
            params={
                "item": {
                    "id": "i1",
                    "kind": "commandExecution",
                    "command": "ls",
                    "input": {"args": ["-la"]},
                },
            },
        ),
        emit=emitter,
        tool_name_by_id=ids,
        final_text_parts=parts,
        result_meta=meta,
    )
    assert ids == {"i1": "ls"}
    assert emitter.calls[0][0] == "tool_start"
    assert emitter.calls[0][1]["tool_name"] == "ls"
    assert emitter.calls[0][1]["tool_call_id"] == "i1"


def test_item_completed_emits_tool_result_with_recovered_name():
    emitter, ids, parts, meta = _harness()
    ids["i1"] = "ls"
    translate_notification(
        Notification(
            method=schema.ITEM_COMPLETED,
            params={"item": {"id": "i1", "summary": "listed 3 entries"}},
        ),
        emit=emitter,
        tool_name_by_id=ids,
        final_text_parts=parts,
        result_meta=meta,
    )
    assert emitter.calls[0][0] == "tool_result"
    assert emitter.calls[0][1]["tool_name"] == "ls"
    assert emitter.calls[0][1]["result_summary"] == "listed 3 entries"
    assert emitter.calls[0][1]["is_error"] is False


def test_item_completed_marks_errors():
    emitter, ids, parts, meta = _harness()
    translate_notification(
        Notification(
            method=schema.ITEM_COMPLETED,
            params={"item": {"id": "i2", "name": "Bash", "isError": True, "text": "boom"}},
        ),
        emit=emitter,
        tool_name_by_id=ids,
        final_text_parts=parts,
        result_meta=meta,
    )
    assert emitter.calls[0][1]["is_error"] is True


def test_token_usage_updated_records_meta():
    emitter, ids, parts, meta = _harness()
    translate_notification(
        Notification(
            method=schema.NOTIFICATION_TOKEN_USAGE_UPDATED,
            params={
                "tokenUsage": {
                    "modelContextWindow": 4000,
                    "total": {
                        "inputTokens": 120,
                        "outputTokens": 30,
                        "reasoningOutputTokens": 10,
                        "cachedInputTokens": 20,
                        "totalTokens": 160,
                    },
                    "last": {
                        "inputTokens": 12,
                        "outputTokens": 3,
                        "reasoningOutputTokens": 1,
                        "cachedInputTokens": 2,
                        "totalTokens": 16,
                    },
                }
            },
        ),
        emit=emitter,
        tool_name_by_id=ids,
        final_text_parts=parts,
        result_meta=meta,
    )
    assert meta["usage"]["total_tokens"] == 160
    assert meta["usage"]["input_tokens"] == 120
    assert meta["usage"]["output_tokens"] == 30
    assert meta["usage"]["reasoning_output_tokens"] == 10
    assert meta["usage"]["cached_tokens"] == 20
    assert meta["usage"]["context_window_tokens"] == 4000
    assert meta["usage"]["last_total_tokens"] == 16
    assert "codex_token_usage" not in meta["usage"]


def test_turn_completed_with_turn_object_finalizes_meta():
    """Per README, turn/completed carries a `turn` object with id + status."""
    emitter, ids, parts, meta = _harness()
    parts.append("hello")
    translate_notification(
        Notification(
            method=schema.NOTIFICATION_TURN_COMPLETED,
            params={
                "turn": {
                    "id": "t1",
                    "status": "completed",
                    "costUsd": 0.04,
                    "usage": {"input_tokens": 10, "output_tokens": 20},
                    "error": None,
                }
            },
        ),
        emit=emitter,
        tool_name_by_id=ids,
        final_text_parts=parts,
        result_meta=meta,
    )
    assert meta["completed"] is True
    assert meta["final_text"] == "hello"
    assert meta["total_cost_usd"] == 0.04
    assert meta["usage"] == {"input_tokens": 10, "output_tokens": 20}
    assert "is_error" not in meta


def test_plan_delta_and_completed_plan_item_are_not_fake_tool_results():
    emitter, ids, parts, meta = _harness()
    translate_notification(
        Notification(
            method=schema.ITEM_PLAN_DELTA,
            params={"itemId": "plan-1", "delta": "1. Inspect"},
        ),
        emit=emitter,
        tool_name_by_id=ids,
        final_text_parts=parts,
        result_meta=meta,
    )
    translate_notification(
        Notification(
            method=schema.ITEM_COMPLETED,
            params={"item": {"id": "plan-1", "type": "plan", "text": "1. Inspect\n2. Fix"}},
        ),
        emit=emitter,
        tool_name_by_id=ids,
        final_text_parts=parts,
        result_meta=meta,
    )

    assert emitter.calls == []
    assert "1. Inspect" in meta["native_plan_text"]
    assert "2. Fix" in parts[-1]


def test_turn_completed_with_turn_error_records_failure():
    emitter, ids, parts, meta = _harness()
    translate_notification(
        Notification(
            method=schema.NOTIFICATION_TURN_COMPLETED,
            params={
                "turn": {
                    "id": "t1",
                    "status": "failed",
                    "error": {"message": "rate limited"},
                }
            },
        ),
        emit=emitter,
        tool_name_by_id=ids,
        final_text_parts=parts,
        result_meta=meta,
    )
    assert meta["completed"] is True
    assert meta["is_error"] is True
    assert meta["error"] == "rate limited"


def test_error_notification_records_is_error():
    """Per README, top-level `error` notification has `{ error: { message, ... } }`."""
    emitter, ids, parts, meta = _harness()
    translate_notification(
        Notification(
            method=schema.NOTIFICATION_ERROR,
            params={"error": {"message": "rate limited", "codexErrorInfo": {}}},
        ),
        emit=emitter,
        tool_name_by_id=ids,
        final_text_parts=parts,
        result_meta=meta,
    )
    assert meta["is_error"] is True
    assert meta["error"] == "rate limited"


def test_unknown_notification_does_not_crash():
    emitter, ids, parts, meta = _harness()
    translate_notification(
        Notification(method="something/new", params={}),
        emit=emitter,
        tool_name_by_id=ids,
        final_text_parts=parts,
        result_meta=meta,
    )
    assert emitter.calls == []
    assert meta == {}
