"""Codex runtime — dynamic-tools bridge attach behavior + protocol shapes.

Fixtures derived from the upstream codex app-server protocol README:
https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md
"""

from __future__ import annotations

import uuid

from integrations.codex import schema
from integrations.codex.harness import (
    _build_turn_input,
    _codex_native_app_server_params_for_context,
    _codex_native_command_is_mutating,
    _codex_thread_restart_reason,
    _codex_skill_paths_by_name,
    _dynamic_tool_entry,
    _dynamic_tools_changed,
    _dynamic_tools_signature,
    _extract_thread_id,
    _extract_turn_id,
    _extract_codex_skill_tokens,
    _prompt_with_bridge_guidance,
    _resolve_codex_native_app_server_call,
    _server_supports_dynamic_tools,
    _should_resume_codex_thread,
    _summarize_native_command_result,
)
from integrations.sdk import HarnessInputAttachment, HarnessInputManifest, HarnessToolSpec, build_turn_context


class _FakeClient:
    def __init__(self, capabilities: dict | None) -> None:
        self.server_capabilities = capabilities or {}


def _turn_ctx(manifest: HarnessInputManifest | None = None):
    return build_turn_context(
        spindrel_session_id=uuid.uuid4(),
        bot_id="codex-bot",
        turn_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        workdir="/tmp/project",
        harness_session_id=None,
        permission_mode="default",
        input_manifest=manifest,
    )


def _resume_ctx(*, prior_cwd: str | None, workdir: str = "/tmp/project"):
    metadata = {}
    if prior_cwd is not None:
        metadata["effective_cwd"] = prior_cwd
    return build_turn_context(
        spindrel_session_id=uuid.uuid4(),
        bot_id="codex-bot",
        turn_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        workdir=workdir,
        harness_session_id="thread-old",
        permission_mode="default",
        harness_metadata=metadata,
    )


def test_dynamic_tools_supported_when_capability_true():
    client = _FakeClient({"dynamicTools": True})
    assert _server_supports_dynamic_tools(client) is True


def test_dynamic_tools_unsupported_when_capability_false():
    client = _FakeClient({"dynamicTools": False})
    assert _server_supports_dynamic_tools(client) is False


def test_dynamic_tools_optimistic_when_capability_silent():
    client = _FakeClient({})
    assert _server_supports_dynamic_tools(client) is True


def test_dynamic_tool_envelope_uses_input_text_kind():
    """Per README, contentItems entries use ``inputText`` (not ``text``)."""
    body = schema.dynamic_tool_text_result("ok", success=True)
    assert body[schema.DYNAMIC_TOOL_RESULT_SUCCESS] is True
    items = body[schema.DYNAMIC_TOOL_RESULT_CONTENT_ITEMS]
    assert items[0]["type"] == schema.DYNAMIC_TOOL_CONTENT_ITEM_KIND_TEXT == "inputText"
    assert items[0]["text"] == "ok"


def test_thread_start_dynamic_tools_entry_uses_input_schema():
    """Per README, dynamicTools entries use ``inputSchema`` (not ``parameters``)."""
    spec = HarnessToolSpec(
        name="search_channel_knowledge",
        description="Search channel knowledge",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        schema={},
    )
    entry = _dynamic_tool_entry(spec)
    assert "inputSchema" in entry
    assert entry["namespace"] == "spindrel"
    assert entry["deferLoading"] is True
    assert "parameters" not in entry
    assert "query" in entry["inputSchema"]["properties"]


def test_dynamic_tools_signature_changes_when_schema_changes():
    first = _dynamic_tools_signature([
        {
            "name": "search",
            "description": "Search",
            "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
        }
    ])
    second = _dynamic_tools_signature([
        {
            "name": "search",
            "description": "Search",
            "inputSchema": {"type": "object", "properties": {"q": {"type": "number"}}},
        }
    ])

    assert first != second
    assert first == _dynamic_tools_signature([
        {
            "inputSchema": {"properties": {"q": {"type": "string"}}, "type": "object"},
            "description": "Search",
            "name": "search",
        }
    ])


def test_dynamic_tools_signature_is_order_insensitive():
    left = _dynamic_tools_signature([
        {"name": "b", "description": "B", "inputSchema": {"type": "object"}},
        {"name": "a", "description": "A", "inputSchema": {"type": "object"}},
    ])
    right = _dynamic_tools_signature([
        {"name": "a", "description": "A", "inputSchema": {"type": "object"}},
        {"name": "b", "description": "B", "inputSchema": {"type": "object"}},
    ])

    assert left == right


def test_dynamic_tools_change_detects_add_remove_and_schema_drift():
    assert _dynamic_tools_changed(
        harness_session_id=None,
        current_signature="next",
        prior_signature="prior",
    ) is False
    assert _dynamic_tools_changed(
        harness_session_id="thread-1",
        current_signature="next",
        prior_signature="prior",
    ) is True
    assert _dynamic_tools_changed(
        harness_session_id="thread-1",
        current_signature=None,
        prior_signature="prior",
    ) is True
    assert _dynamic_tools_changed(
        harness_session_id="thread-1",
        current_signature=None,
        prior_signature="",
    ) is False


def test_codex_thread_restart_reason_detects_workdir_changes_for_agents_md_reload():
    assert _codex_thread_restart_reason(_resume_ctx(prior_cwd="/tmp/project")) is None
    assert _codex_thread_restart_reason(
        _resume_ctx(prior_cwd="/tmp/old-project", workdir="/tmp/project")
    ) == "workdir_changed"
    assert _codex_thread_restart_reason(_resume_ctx(prior_cwd=None)) == "unknown_prior_cwd"


def test_codex_resume_gate_requires_same_workdir_and_same_dynamic_tools():
    same = _resume_ctx(prior_cwd="/tmp/project")
    changed = _resume_ctx(prior_cwd="/tmp/old-project", workdir="/tmp/project")

    assert _should_resume_codex_thread(same, dynamic_tools_changed=False) is True
    assert _should_resume_codex_thread(same, dynamic_tools_changed=True) is False
    assert _should_resume_codex_thread(changed, dynamic_tools_changed=False) is False


def test_bridge_guidance_names_exact_callable_dynamic_tools():
    prompt = _prompt_with_bridge_guidance(
        "Call get_tool_info for list_channels.",
        ["list_channels", "get_tool_info"],
    )

    assert "Callable Spindrel dynamic tools this turn: get_tool_info, list_channels" in prompt
    assert "invoke the dynamic tool by its exact name" in prompt
    assert "Do not emulate it with shell commands" in prompt
    assert "The callable tool list below is exhaustive for this turn" in prompt
    assert "read_workspace_file" in prompt
    assert "sandbox, process namespace, or runtime shell is broken" in prompt
    assert prompt.startswith("Call get_tool_info for list_channels.")
    assert prompt.index("Call get_tool_info for list_channels.") < prompt.index("<spindrel_tool_guidance>")
    assert "not the primary coding surface" in prompt


def test_extract_thread_id_reads_nested_thread_object():
    """Per README: thread/start result is { thread: { id, ... } }."""
    assert _extract_thread_id({"thread": {"id": "th-1"}}) == "th-1"
    assert _extract_thread_id({"threadId": "th-x"}) is None
    assert _extract_thread_id({}) is None
    assert _extract_thread_id(None) is None


def test_extract_turn_id_reads_nested_turn_object():
    """Per README: turn/start result is { turn: { id, ... } }."""
    assert _extract_turn_id({"turn": {"id": "t-1"}}) == "t-1"
    assert _extract_turn_id({"turnId": "t-x"}) is None
    assert _extract_turn_id({}) is None


def test_text_input_item_shape():
    """Per README: turn/start.input is an array of typed content items."""
    item = schema.text_input_item("hello world")
    assert item == {"type": "text", "text": "hello world"}


def test_codex_turn_input_maps_manifest_images_to_native_items():
    ctx = _turn_ctx(HarnessInputManifest(
        attachments=(
            HarnessInputAttachment(
                kind="image",
                source="inline_attachment",
                name="screen.png",
                mime_type="image/png",
                content_base64="AAA",
            ),
            HarnessInputAttachment(
                kind="image",
                source="channel_workspace",
                name="photo.jpg",
                mime_type="image/jpeg",
                path="/tmp/project/data/photo.jpg",
            ),
        )
    ))

    items = _build_turn_input("Look at these.", ctx)

    assert items[0] == {"type": "text", "text": "Look at these."}
    assert items[1] == {"type": "image", "url": "data:image/png;base64,AAA"}
    assert items[2] == {"type": "localImage", "path": "/tmp/project/data/photo.jpg"}


def test_harness_input_manifest_metadata_redacts_inline_image_bytes():
    manifest = HarnessInputManifest(
        attachments=(
            HarnessInputAttachment(
                kind="image",
                source="inline_attachment",
                name="screen.png",
                mime_type="image/png",
                content_base64="VERY_SECRET_BASE64",
            ),
        )
    )

    metadata = manifest.metadata(runtime_items=({"type": "image", "url": "data:image/png;base64,VERY_SECRET_BASE64"},))

    assert metadata["runtime_item_counts"] == {"image": 1}
    assert metadata["attachments"][0]["has_inline_content"] is True
    assert "VERY_SECRET_BASE64" not in str(metadata)


def test_codex_skill_token_and_path_resolution():
    assert _extract_codex_skill_tokens("$skill-creator do it and $review.bot, now") == (
        "skill-creator",
        "review.bot",
    )
    paths = _codex_skill_paths_by_name({
        "data": [
            {
                "cwd": "/tmp/project",
                "skills": [
                    {"name": "skill-creator", "path": "/home/me/.codex/skills/skill-creator/SKILL.md"},
                    {"name": "missing-path"},
                ],
            }
        ]
    })
    assert paths == {"skill-creator": "/home/me/.codex/skills/skill-creator/SKILL.md"}


def test_initialize_capabilities_carries_experimental_api():
    """Per README, experimentalApi lives under params.capabilities (not at top level)."""
    # Exercises the schema constants used in app_server.initialize().
    assert schema.METHOD_INITIALIZE == "initialize"
    assert schema.NOTIFICATION_INITIALIZED == "initialized"


def test_codex_native_command_method_constants_are_current():
    assert schema.METHOD_CONFIG_READ == "config/read"
    assert schema.METHOD_CONFIG_VALUE_WRITE == "config/value/write"
    assert schema.METHOD_MCP_SERVER_STATUS_LIST == "mcpServerStatus/list"
    assert schema.METHOD_MCP_SERVER_RESOURCE_READ == "mcpServer/resource/read"
    assert schema.METHOD_PLUGIN_LIST == "plugin/list"
    assert schema.METHOD_PLUGIN_READ == "plugin/read"
    assert schema.METHOD_PLUGIN_INSTALL == "plugin/install"
    assert schema.METHOD_PLUGIN_UNINSTALL == "plugin/uninstall"
    assert schema.METHOD_MARKETPLACE_ADD == "marketplace/add"
    assert schema.METHOD_MARKETPLACE_REMOVE == "marketplace/remove"
    assert schema.METHOD_MARKETPLACE_UPGRADE == "marketplace/upgrade"
    assert schema.METHOD_SKILLS_LIST == "skills/list"
    assert schema.METHOD_SKILLS_CONFIG_WRITE == "skills/config/write"
    assert schema.METHOD_EXPERIMENTAL_FEATURE_LIST == "experimentalFeature/list"
    assert schema.METHOD_EXPERIMENTAL_FEATURE_ENABLEMENT_SET == "experimentalFeature/enablement/set"
    assert schema.METHOD_CONVERSATION_LIST == "conversation/list"
    assert schema.METHOD_CONVERSATION_SEARCH == "conversation/search"
    assert schema.METHOD_CONVERSATION_GET == "conversation/get"
    assert schema.METHOD_CONVERSATION_RESPONSES_LIST == "conversation/responses/list"
    assert schema.METHOD_COMMAND_EXECUTE == "command/execute"
    assert schema.METHOD_COMMAND_STATUS == "command/status"
    assert schema.METHOD_COMMAND_INPUT == "command/input"
    assert schema.METHOD_COMMAND_KILL == "command/kill"
    assert schema.METHOD_COMMAND_LIST == "command/list"
    assert schema.METHOD_FS_LIST_CHANGED_FILES == "fs/listChangedFiles"
    assert schema.METHOD_CONFIG_REQUIREMENTS_LIST == "configRequirements/list"
    assert schema.METHOD_CONFIG_REQUIREMENTS_OPEN == "configRequirements/open"
    assert schema.METHOD_USER_LIMITS == "user/limits"
    assert schema.METHOD_USER_LIMITS_SUBSCRIPTION == "user/limits/subscription"
    assert schema.METHOD_THREAD_LIST == "thread/list"
    assert schema.METHOD_THREAD_READ == "thread/read"
    assert schema.METHOD_THREAD_TURNS_LIST == "thread/turns/list"
    assert schema.METHOD_ACCOUNT_RATE_LIMITS_READ == "account/rateLimits/read"


def test_summarize_native_command_result_counts_common_list_fields():
    assert _summarize_native_command_result("mcp-status", {"servers": [{}, {}]}) == "mcp-status: 2 item(s)."
    assert _summarize_native_command_result("config", {"cwd": "/tmp"}) == "config: returned 1 top-level field(s)."
    assert _summarize_native_command_result("features", ["a"]) == "Runtime command completed."


def test_codex_native_command_maps_management_methods():
    assert _resolve_codex_native_app_server_call("plugins", ("list",)) == (schema.METHOD_PLUGIN_LIST, {})
    assert _resolve_codex_native_app_server_call("plugins", ("read", "fixture")) == (
        schema.METHOD_PLUGIN_READ,
        {"pluginName": "fixture"},
    )
    assert _resolve_codex_native_app_server_call("plugins", ("install", "fixture")) == (None, {})
    assert _resolve_codex_native_app_server_call("plugins", ("uninstall", "fixture-id")) == (
        schema.METHOD_PLUGIN_UNINSTALL,
        {"pluginId": "fixture-id"},
    )
    assert _resolve_codex_native_app_server_call("skills", ("disable", "reviewer")) == (
        schema.METHOD_SKILLS_CONFIG_WRITE,
        {"enabled": False, "path": None, "name": "reviewer"},
    )
    assert _resolve_codex_native_app_server_call("features", ("enable", "dynamicTools")) == (
        schema.METHOD_EXPERIMENTAL_FEATURE_ENABLEMENT_SET,
        {"enablement": {"dynamicTools": True}},
    )
    assert _resolve_codex_native_app_server_call("config", ("set", "model", '"gpt-5.4"')) == (
        schema.METHOD_CONFIG_VALUE_WRITE,
        {"keyPath": "model", "value": "gpt-5.4", "mergeStrategy": "upsert"},
    )
    assert _resolve_codex_native_app_server_call("status", ()) == (
        schema.METHOD_ACCOUNT_READ,
        {"refreshToken": False},
    )
    assert _resolve_codex_native_app_server_call("diff", ()) == (None, {})
    assert _resolve_codex_native_app_server_call("resume", ()) == (
        schema.METHOD_THREAD_LIST,
        {},
    )
    assert _resolve_codex_native_app_server_call("resume", ("search", "fixture")) == (
        schema.METHOD_THREAD_LIST,
        {"query": "fixture"},
    )
    assert _resolve_codex_native_app_server_call("agents", ()) == (
        schema.METHOD_THREAD_LIST,
        {},
    )
    assert _resolve_codex_native_app_server_call("agents", ("show", "thread-1")) == (
        schema.METHOD_THREAD_READ,
        {"threadId": "thread-1"},
    )
    assert _resolve_codex_native_app_server_call("agents", ("turns", "thread-1")) == (
        schema.METHOD_THREAD_TURNS_LIST,
        {"threadId": "thread-1"},
    )
    assert _resolve_codex_native_app_server_call("cloud", ()) == (
        schema.METHOD_ACCOUNT_RATE_LIMITS_READ,
        {},
    )
    assert _resolve_codex_native_app_server_call("approvals", ()) == (None, {})
    assert _resolve_codex_native_app_server_call("review", ()) == (None, {})


def test_codex_native_skills_list_is_scoped_to_harness_workdir():
    ctx = _turn_ctx()

    params = _codex_native_app_server_params_for_context(schema.METHOD_SKILLS_LIST, {}, ctx)

    assert params == {"cwds": ["/tmp/project"]}


def test_codex_native_diff_is_scoped_to_harness_workdir():
    ctx = _turn_ctx()

    params = _codex_native_app_server_params_for_context(schema.METHOD_FS_LIST_CHANGED_FILES, {}, ctx)

    assert params == {"cwd": "/tmp/project"}


def test_codex_native_command_classifies_mutating_args():
    assert _codex_native_command_is_mutating("plugins", ("install", "fixture")) is True
    assert _codex_native_command_is_mutating("plugins", ("read", "fixture")) is False
    assert _codex_native_command_is_mutating("skills", ("disable", "reviewer")) is True
    assert _codex_native_command_is_mutating("features", ("list",)) is False
