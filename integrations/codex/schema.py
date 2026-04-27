"""Codex app-server protocol shapes — sourced from the installed binary.

**All** method names, item kinds, approval-policy values, sandbox profile
names, and envelope field names that the harness adapter consumes live in
this module. ``harness.py`` / ``events.py`` / ``approvals.py`` reference
named constants from here — never literal strings.

The constants are a vendored snapshot of the upstream
``codex-rs/app-server`` schema (see https://github.com/openai/codex). When
the installed ``codex`` binary exposes ``codex app-server generate-json-schema --experimental``
(or equivalent), ``verify_schema_against_binary`` should be called at
startup to catch drift between the snapshot and the local binary.

Why constants and not literals: drift between docs and binary releases is
common, and grepping for a single constant is the only way to fix every
caller in one pass when the upstream renames a method or enum value.
"""

from __future__ import annotations

from dataclasses import dataclass


class CodexSchemaError(RuntimeError):
    """Raised when the installed binary's schema disagrees with the vendored snapshot."""


# ---------------------------------------------------------------------------
# JSON-RPC method names (client → server)
# ---------------------------------------------------------------------------

METHOD_INITIALIZE = "initialize"
NOTIFICATION_INITIALIZED = "initialized"
METHOD_THREAD_START = "thread/start"
METHOD_THREAD_RESUME = "thread/resume"
METHOD_THREAD_COMPACT_START = "thread/compact/start"
METHOD_TURN_START = "turn/start"
METHOD_TURN_INTERRUPT = "turn/interrupt"
METHOD_ACCOUNT_READ = "account/read"
METHOD_MODEL_LIST = "model/list"


# ---------------------------------------------------------------------------
# Notification + item kinds (server → client, fire-and-forget)
# ---------------------------------------------------------------------------

ITEM_STARTED = "item/started"
ITEM_COMPLETED = "item/completed"
ITEM_AGENT_MESSAGE_DELTA = "item/agentMessage/delta"
ITEM_REASONING_TEXT_DELTA = "item/reasoning/textDelta"
ITEM_REASONING_SUMMARY_TEXT_DELTA = "item/reasoning/summaryTextDelta"
# Backwards-compat alias for older callers; reasoning streams arrive on the
# textDelta channel by default.
ITEM_REASONING_DELTA = ITEM_REASONING_TEXT_DELTA
ITEM_COMMAND_OUTPUT_DELTA = "item/commandExecution/outputDelta"
ITEM_FILE_CHANGE_OUTPUT_DELTA = "item/fileChange/outputDelta"

NOTIFICATION_THREAD_STARTED = "thread/started"
NOTIFICATION_PLAN_UPDATED = "turn/plan/updated"
NOTIFICATION_DIFF_UPDATED = "turn/diff/updated"
NOTIFICATION_TOKEN_USAGE_UPDATED = "thread/tokenUsage/updated"
NOTIFICATION_TURN_COMPLETED = "turn/completed"
NOTIFICATION_ERROR = "error"


# ---------------------------------------------------------------------------
# Server-initiated request methods (server → client, requires response)
# ---------------------------------------------------------------------------

SERVER_REQUEST_COMMAND_APPROVAL = "item/commandExecution/requestApproval"
SERVER_REQUEST_FILE_CHANGE_APPROVAL = "item/fileChange/requestApproval"
SERVER_REQUEST_PERMISSIONS = "item/permissions/requestApproval"
SERVER_REQUEST_USER_INPUT = "item/tool/requestUserInput"
SERVER_REQUEST_TOOL_CALL = "item/tool/call"

# All approval-shaped server requests share a `decision` reply enum.
APPROVAL_REQUEST_METHODS: frozenset[str] = frozenset(
    {
        SERVER_REQUEST_COMMAND_APPROVAL,
        SERVER_REQUEST_FILE_CHANGE_APPROVAL,
        SERVER_REQUEST_PERMISSIONS,
    }
)

APPROVAL_DECISION_ACCEPT = "accept"
APPROVAL_DECISION_ACCEPT_FOR_SESSION = "acceptForSession"
APPROVAL_DECISION_DECLINE = "decline"
APPROVAL_DECISION_CANCEL = "cancel"


# ---------------------------------------------------------------------------
# Approval policy + sandbox profile values
# ---------------------------------------------------------------------------

APPROVAL_POLICY_NEVER = "never"
APPROVAL_POLICY_UNLESS_TRUSTED = "untrusted"
APPROVAL_POLICY_ON_REQUEST = "on-request"
APPROVAL_POLICY_ON_FAILURE = "on-failure"

SANDBOX_DANGER_FULL_ACCESS = "danger-full-access"
SANDBOX_WORKSPACE_WRITE = "workspace-write"
SANDBOX_READ_ONLY = "read-only"


# ---------------------------------------------------------------------------
# turn/start input content-item kinds
# ---------------------------------------------------------------------------

INPUT_ITEM_TEXT = "text"
INPUT_ITEM_IMAGE = "image"
INPUT_ITEM_LOCAL_IMAGE = "localImage"
INPUT_ITEM_SKILL = "skill"
INPUT_ITEM_MENTION = "mention"


def text_input_item(text: str) -> dict:
    """Build the ``input`` array entry for a plain-text user message."""
    return {"type": INPUT_ITEM_TEXT, "text": text}


# ---------------------------------------------------------------------------
# Dynamic-tool envelope shapes
# ---------------------------------------------------------------------------

DYNAMIC_TOOL_RESULT_CONTENT_ITEMS = "contentItems"
DYNAMIC_TOOL_RESULT_SUCCESS = "success"
DYNAMIC_TOOL_CONTENT_ITEM_KIND_TEXT = "inputText"
DYNAMIC_TOOL_CONTENT_ITEM_KIND_IMAGE = "inputImage"

# Field names on the incoming ``item/tool/call`` request from the server.
TOOL_CALL_REQUEST_TOOL_FIELD = "tool"
TOOL_CALL_REQUEST_ARGUMENTS_FIELD = "arguments"
TOOL_CALL_REQUEST_CALL_ID_FIELD = "callId"


@dataclass(frozen=True)
class CodexDynamicToolSpec:
    """One entry in ``thread/start``'s ``dynamicTools`` array.

    Per the upstream protocol the field is ``inputSchema`` (NOT
    ``parameters``); ``deferLoading`` is optional.
    """

    name: str
    description: str
    inputSchema: dict
    deferLoading: bool = False


def dynamic_tool_text_result(text: str, *, success: bool) -> dict:
    """Build the canonical Codex dynamic-tool result envelope."""
    return {
        DYNAMIC_TOOL_RESULT_CONTENT_ITEMS: [
            {"type": DYNAMIC_TOOL_CONTENT_ITEM_KIND_TEXT, "text": text}
        ],
        DYNAMIC_TOOL_RESULT_SUCCESS: success,
    }


# ---------------------------------------------------------------------------
# Schema introspection
# ---------------------------------------------------------------------------


def verify_schema_against_binary(binary_path: str) -> None:
    """Optionally probe the installed binary for a schema-drift check.

    The codex binary exposes ``codex app-server generate-json-schema
    --experimental`` for protocol introspection. This function is a stub
    today; once we wire it up it should compare the returned method names
    + enum values against the constants above and raise
    ``CodexSchemaError`` on drift.
    """
    return None
