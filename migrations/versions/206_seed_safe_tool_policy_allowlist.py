"""Seed safe-tool allowlist for tool policy engine.

Pairs with the `TOOL_POLICY_DEFAULT_ACTION` flip from "deny" to
"require_approval" (`app/config.py`). With the new default, every
unmatched tool prompts the user for approval — so without this seed,
even reading a skill or listing tasks would interrupt the agent.

Each rule is global (`bot_id IS NULL`), priority 10 (well below the
default 100 used by user-installed rules), and `enabled=true`. Users can
disable any rule via the admin UI without touching this migration.

The `file` tool gets a per-operation gate: read/list/grep/glob/history
and the bot's own-workspace writes (create/append/edit/mkdir/json_patch/
restore) are allowed; overwrite/delete/move fall through to the default
require_approval. The autonomous-default at `tool_policies.py:51-62`
already gates overwrite/delete from heartbeat/task/subagent/hygiene
origins; this rule extends the same shape into interactive chat.

Excluded by intent (still require approval): plan/todo writes (legitimacy
under review), prune_enrolled_*, persona writes, generate_image,
send_file, activate_capability, pin_panel, file overwrite/delete/move,
and everything in mutating/exec_capable/control_plane tiers.

Revision ID: 206
Revises: 205
"""
from alembic import op
import sqlalchemy as sa


revision = "206"
down_revision = "205"
branch_labels = None
depends_on = None


_REASON = "Default safe-tool allowlist (migration 206)"
_PRIORITY = 10

_SIMPLE_ALLOWS: list[str] = [
    # Pure inspection / time
    "get_current_time",
    "get_current_local_time",
    "get_skill",
    "get_skill_list",
    "get_tool_info",
    "get_trace",
    "list_session_traces",
    "list_pipelines",
    "list_tasks",
    "get_task_result",
    "get_plan",
    "list_plans",
    "list_todos",
    "list_channels",
    "list_attachments",
    "list_api_endpoints",
    "get_attachment",
    "describe_attachment",
    "view_attachment",
    "get_memory_file",
    "get_last_heartbeat",
    # Read / search
    "read_conversation_history",
    "summarize_channel",
    "search_history",
    "search_workspace",
    "search_channel_workspace",
    "search_channel_archive",
    "search_memory",
    "search_bot_memory",
    # UI / ephemeral surfaces
    "spawn_subagents",
    "respond_privately",
    "client_action",
    "open_modal",
]

_FILE_SAFE_OPS = [
    "read", "list", "grep", "glob", "history",
    "create", "append", "edit", "mkdir", "json_patch", "restore",
]


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        insert_simple = sa.text(
            "INSERT INTO tool_policy_rules (bot_id, tool_name, action, conditions, priority, reason, enabled) "
            "VALUES (NULL, :tool_name, 'allow', '{}'::jsonb, :priority, :reason, TRUE)"
        )
        insert_file = sa.text(
            "INSERT INTO tool_policy_rules (bot_id, tool_name, action, conditions, priority, reason, enabled) "
            "VALUES (NULL, 'file', 'allow', CAST(:conditions AS jsonb), :priority, :reason, TRUE)"
        )
    else:
        # SQLite (tests): JSON column accepts text
        insert_simple = sa.text(
            "INSERT INTO tool_policy_rules (bot_id, tool_name, action, conditions, priority, reason, enabled) "
            "VALUES (NULL, :tool_name, 'allow', '{}', :priority, :reason, 1)"
        )
        insert_file = sa.text(
            "INSERT INTO tool_policy_rules (bot_id, tool_name, action, conditions, priority, reason, enabled) "
            "VALUES (NULL, 'file', 'allow', :conditions, :priority, :reason, 1)"
        )

    for tool_name in _SIMPLE_ALLOWS:
        bind.execute(insert_simple, {
            "tool_name": tool_name,
            "priority": _PRIORITY,
            "reason": _REASON,
        })

    import json as _json
    file_conditions = _json.dumps({"arguments": {"operation": {"in": _FILE_SAFE_OPS}}})
    bind.execute(insert_file, {
        "conditions": file_conditions,
        "priority": _PRIORITY,
        "reason": f"{_REASON} — read + own-workspace writes; overwrite/delete/move still prompt",
    })


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "DELETE FROM tool_policy_rules WHERE bot_id IS NULL AND priority = :priority AND reason LIKE :reason_prefix"
    ), {"priority": _PRIORITY, "reason_prefix": "Default safe-tool allowlist (migration 206)%"})
