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

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


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
METHOD_THREAD_LIST = "thread/list"
METHOD_THREAD_READ = "thread/read"
METHOD_THREAD_TURNS_LIST = "thread/turns/list"
METHOD_TURN_START = "turn/start"
METHOD_TURN_INTERRUPT = "turn/interrupt"
METHOD_ACCOUNT_READ = "account/read"
METHOD_MODEL_LIST = "model/list"
METHOD_COLLABORATION_MODE_LIST = "collaborationMode/list"
METHOD_CONFIG_READ = "config/read"
METHOD_CONFIG_VALUE_WRITE = "config/value/write"
METHOD_CONFIG_BATCH_WRITE = "config/batchWrite"
METHOD_MCP_SERVER_STATUS_LIST = "mcpServerStatus/list"
METHOD_MCP_SERVER_RESOURCE_READ = "mcpServer/resource/read"
METHOD_MCP_SERVER_TOOL_CALL = "mcpServer/tool/call"
METHOD_MCP_SERVER_OAUTH_LOGIN = "mcpServer/oauth/login"
METHOD_PLUGIN_LIST = "plugin/list"
METHOD_PLUGIN_READ = "plugin/read"
METHOD_PLUGIN_INSTALL = "plugin/install"
METHOD_PLUGIN_UNINSTALL = "plugin/uninstall"
METHOD_MARKETPLACE_ADD = "marketplace/add"
METHOD_MARKETPLACE_REMOVE = "marketplace/remove"
METHOD_MARKETPLACE_UPGRADE = "marketplace/upgrade"
METHOD_SKILLS_LIST = "skills/list"
METHOD_SKILLS_CONFIG_WRITE = "skills/config/write"
METHOD_EXPERIMENTAL_FEATURE_LIST = "experimentalFeature/list"
METHOD_EXPERIMENTAL_FEATURE_ENABLEMENT_SET = "experimentalFeature/enablement/set"
METHOD_CONVERSATION_LIST = "conversation/list"
METHOD_CONVERSATION_SEARCH = "conversation/search"
METHOD_CONVERSATION_GET = "conversation/get"
METHOD_CONVERSATION_RESPONSES_LIST = "conversation/responses/list"
METHOD_HOOKS_LIST = "hooks/list"
METHOD_APPS_LIST = "app/list"
METHOD_COMMAND_EXECUTE = "command/exec"
METHOD_COMMAND_INPUT = "command/exec/write"
METHOD_COMMAND_KILL = "command/exec/terminate"
METHOD_COMMAND_RESIZE = "command/exec/resize"
METHOD_FS_READ_TEXT_FILE = "fs/readFile"
METHOD_FS_WRITE_TEXT_FILE = "fs/writeFile"
METHOD_FS_LIST_DIRECTORY = "fs/readDirectory"
METHOD_FS_GET_FILE_INFO = "fs/getMetadata"
METHOD_FS_MKDIR = "fs/createDirectory"
METHOD_FS_MOVE = "fs/move"
METHOD_FS_COPY = "fs/copy"
METHOD_FS_DELETE = "fs/remove"
METHOD_FS_WATCH = "fs/watch"
METHOD_FS_UNWATCH = "fs/unwatch"
METHOD_CONFIG_REQUIREMENTS_LIST = "configRequirements/read"
METHOD_USER_LIMITS = "user/limits"
METHOD_USER_LIMITS_SUBSCRIPTION = "user/limits/subscription"
METHOD_ACCOUNT_RATE_LIMITS_READ = "account/rateLimits/read"


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
ITEM_PLAN_DELTA = "item/plan/delta"

ITEM_KIND_COMMAND_EXECUTION = "commandExecution"
ITEM_KIND_FILE_CHANGE = "fileChange"
ITEM_KIND_MCP_TOOL_CALL = "mcpToolCall"
ITEM_KIND_DYNAMIC_TOOL = "dynamicTool"
ITEM_KIND_TOOL_CALL = "toolCall"
ITEM_KIND_COLLAB_TOOL_CALL = "collabToolCall"
ITEM_KIND_WEB_SEARCH = "webSearch"
ITEM_KIND_IMAGE_VIEW = "imageView"
TOOL_ITEM_KINDS: frozenset[str] = frozenset(
    {
        ITEM_KIND_COMMAND_EXECUTION,
        ITEM_KIND_FILE_CHANGE,
        ITEM_KIND_MCP_TOOL_CALL,
        ITEM_KIND_DYNAMIC_TOOL,
        ITEM_KIND_TOOL_CALL,
        ITEM_KIND_COLLAB_TOOL_CALL,
        ITEM_KIND_WEB_SEARCH,
        ITEM_KIND_IMAGE_VIEW,
    }
)

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

# Current ``turn/start.sandboxPolicy`` object discriminators. ``thread/start``
# still accepts the legacy flat ``sandbox`` enum above; resumed threads need
# these per-turn policy objects so mode changes take effect immediately.
SANDBOX_POLICY_DANGER_FULL_ACCESS = "dangerFullAccess"
SANDBOX_POLICY_WORKSPACE_WRITE = "workspaceWrite"
SANDBOX_POLICY_READ_ONLY = "readOnly"

COLLABORATION_MODE_PLAN = "plan"
COLLABORATION_MODE_DEFAULT = "default"


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
    namespace: str | None = None
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
    """Probe the installed binary for the app-server schema fields we depend on."""
    with tempfile.TemporaryDirectory(prefix="spindrel-codex-schema-") as tmp:
        out = Path(tmp)
        try:
            subprocess.run(
                [
                    binary_path,
                    "app-server",
                    "generate-json-schema",
                    "--experimental",
                    "--out",
                    str(out),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception as exc:
            raise CodexSchemaError(f"failed to generate codex app-server schema: {exc}") from exc

        thread_start = _load_schema(out / "v2" / "ThreadStartParams.json")
        turn_start = _load_schema(out / "v2" / "TurnStartParams.json")
        user_input = _load_schema(out / "ToolRequestUserInputResponse.json")
        dynamic_tool = _load_schema(out / "DynamicToolCallResponse.json")
        token_usage = _load_schema(out / "v2" / "ThreadTokenUsageUpdatedNotification.json")
        client_request = _load_schema(out / "ClientRequest.json")

    _require_property(thread_start, "dynamicTools", "ThreadStartParams")
    _require_property(turn_start, "collaborationMode", "TurnStartParams")
    _require_property(user_input, "answers", "ToolRequestUserInputResponse")
    _require_property(dynamic_tool, DYNAMIC_TOOL_RESULT_CONTENT_ITEMS, "DynamicToolCallResponse")
    _require_property(dynamic_tool, DYNAMIC_TOOL_RESULT_SUCCESS, "DynamicToolCallResponse")
    _require_property(token_usage, "tokenUsage", "ThreadTokenUsageUpdatedNotification")
    _require_methods(
        client_request,
        (
            METHOD_APPS_LIST,
            METHOD_COMMAND_EXECUTE,
            METHOD_FS_READ_TEXT_FILE,
            METHOD_FS_LIST_DIRECTORY,
            METHOD_FS_GET_FILE_INFO,
            METHOD_CONFIG_REQUIREMENTS_LIST,
        ),
        "ClientRequest",
    )


def _load_schema(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        raise CodexSchemaError(f"failed to read generated schema {path.name}: {exc}") from exc


def _require_property(schema_doc: dict, name: str, label: str) -> None:
    properties = schema_doc.get("properties")
    if not isinstance(properties, dict) or name not in properties:
        raise CodexSchemaError(f"{label} missing required property {name!r}")


def _require_methods(schema_doc: dict, methods: tuple[str, ...], label: str) -> None:
    available = _collect_schema_method_values(schema_doc)
    for method in methods:
        if method not in available:
            raise CodexSchemaError(f"{label} missing required method {method!r}")


def _collect_schema_method_values(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        const = value.get("const")
        if isinstance(const, str) and "/" in const:
            found.add(const)
        enum = value.get("enum")
        if isinstance(enum, list):
            found.update(item for item in enum if isinstance(item, str) and "/" in item)
        for child in value.values():
            found.update(_collect_schema_method_values(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_collect_schema_method_values(child))
    return found
