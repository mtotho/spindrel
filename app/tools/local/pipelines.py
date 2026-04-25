"""Agent tools for discovering, defining, and running Pipelines.

Pipelines are stored in the shared ``tasks`` table (``task_type='pipeline'``),
but the noisy ``tasks``-shaped surface is unfriendly when the caller wants
multi-step Automations specifically. These tools give the LLM a clean view:

* ``list_pipelines`` — Pipeline definitions only, no concrete Runs, slug-addressable.
* ``define_pipeline`` — create a NEW multi-step Pipeline definition.
* ``run_pipeline`` — spawn a Run with ``params`` + ``channel_id``.

The underlying storage is unchanged; this is a vocabulary split, not a model
split. ``schedule_prompt`` covers the single-prompt Automation case;
``run_task`` still works for any Automation definition by id.
"""
import json
import uuid

from sqlalchemy import select

from app.agent.context import current_channel_id
from app.db.engine import async_session
from app.db.models import Task
from app.services.task_seeding import pipeline_uuid
from app.tools.local.tasks import _create_task_row
from app.tools.registry import register


def _looks_like_slug(value: str) -> bool:
    """Slug: contains a dot or non-hex char, and is not a valid UUID."""
    try:
        uuid.UUID(value)
        return False
    except ValueError:
        return True


async def _resolve_pipeline_id(raw: str, db) -> uuid.UUID | None:
    """Accept either a UUID or a system-pipeline slug.

    System slugs (e.g. ``orchestrator.analyze_discovery``) resolve via the
    deterministic ``uuid5`` used by ``task_seeding``. If the derived UUID
    doesn't match a row, fall back to a title / trailing-slug lookup so
    user-created pipelines are also reachable by name.
    """
    try:
        return uuid.UUID(raw)
    except ValueError:
        pass

    derived = pipeline_uuid(raw)
    row = await db.get(Task, derived)
    if row and row.task_type == "pipeline":
        return derived

    # Fallback — match by title (case-insensitive) or by "id-looking" title
    # fragment. Keeps user-created pipelines reachable by name.
    stmt = select(Task).where(Task.task_type == "pipeline")
    candidates = (await db.execute(stmt)).scalars().all()
    for c in candidates:
        if c.title and c.title.lower() == raw.lower():
            return c.id
    return None


@register({
    "type": "function",
    "function": {
        "name": "list_pipelines",
        "description": (
            "List multi-step Pipeline definitions — system audit pipelines "
            "(analyze_discovery, analyze_skill_quality, analyze_memory_quality, "
            "analyze_tool_usage, analyze_costs, full_scan, deep_dive_bot) plus "
            "any user-created Pipelines. Returns each Pipeline's slug, title, "
            "description, required params, and whether it needs a channel/bot "
            "at launch. To run one, pass its slug to `run_pipeline`. This is "
            "the Pipeline-focused view of `list_tasks`; use `list_tasks` when "
            "you also want Scheduled prompts or other Automations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": (
                        "Filter by origin: 'system' for built-in audit pipelines, "
                        "'user' for user-created. Omit to see both."
                    ),
                    "enum": ["system", "user"],
                },
            },
            "required": [],
        },
    },
}, returns={
    "type": "object",
    "properties": {
        "count": {"type": "integer"},
        "pipelines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Pipeline definition UUID"},
                    "title": {"type": "string"},
                    "source": {"type": "string", "enum": ["system", "user"]},
                    "bot_id": {"type": ["string", "null"]},
                    "description": {"type": "string"},
                    "params_schema": {"type": "object"},
                    "requires_channel": {"type": "boolean"},
                    "requires_bot": {"type": "boolean"},
                    "step_count": {"type": "integer"},
                    "hint": {"type": "string"},
                },
                "required": ["id", "title", "source"],
            },
        },
    },
    "required": ["count", "pipelines"],
})
async def list_pipelines(source: str | None = None) -> str:
    async with async_session() as db:
        stmt = (
            select(Task)
            .where(Task.task_type == "pipeline")
            .where(Task.parent_task_id.is_(None))
            .order_by(Task.source, Task.title)
        )
        if source:
            stmt = stmt.where(Task.source == source)
        rows = (await db.execute(stmt)).scalars().all()

    out: list[dict] = []
    for r in rows:
        exec_cfg = r.execution_config or {}
        entry: dict = {
            "id": str(r.id),
            "title": r.title or "(untitled)",
            "source": r.source,
            "bot_id": r.bot_id,
        }
        # Slug for system pipelines — reverse-resolve via title match on the
        # deterministic seed. For user pipelines there's no slug; callers pass
        # the UUID or the title.
        if r.source == "system" and r.title:
            # Derive slug from the seeded row id by comparing against known
            # naming convention. The YAML `id` field is the slug; we stored it
            # implicitly via pipeline_uuid(). We can't recover it without
            # reading the YAML, so expose the UUID and let the caller quote
            # either value into run_pipeline.
            entry["hint"] = "pass this id (or the YAML slug, e.g. 'orchestrator.analyze_discovery') to run_pipeline"
        if exec_cfg.get("description"):
            entry["description"] = exec_cfg["description"]
        if exec_cfg.get("params_schema"):
            entry["params_schema"] = exec_cfg["params_schema"]
        if exec_cfg.get("requires_channel"):
            entry["requires_channel"] = True
        if exec_cfg.get("requires_bot"):
            entry["requires_bot"] = True
        if r.steps:
            entry["step_count"] = len(r.steps)
        out.append(entry)

    return json.dumps({"pipelines": out, "count": len(out)}, ensure_ascii=False)


_DEFINE_PIPELINE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "define_pipeline",
        "description": (
            "CREATE a NEW multi-step Pipeline definition. Use this for declarative "
            "Automations that chain multiple steps (exec / tool / agent / user_prompt / "
            "foreach). For single-prompt Automations, call `schedule_prompt` instead. "
            "To RE-RUN an existing Pipeline, call `run_pipeline` with its slug or id — "
            "do NOT redefine it here. Call `list_pipelines` first to check whether a "
            "matching definition already exists. "
            "Defaults to the current bot in the current channel. The Run lands in the "
            "target channel (or the bot's primary channel when bot_id is set)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short human-readable title for the Pipeline (shown in UI). Keep under ~60 chars.",
                },
                "steps": {
                    "type": "string",
                    "description": (
                        "JSON array of step definitions. Each step needs at minimum "
                        "id and type ('exec', 'tool', 'agent', 'user_prompt', or 'foreach'). "
                        "'user_prompt' pauses the Pipeline for human approval (response shapes: "
                        "'binary' or 'multi_item'; resolved via POST /tasks/{id}/steps/{i}/resolve). "
                        "'foreach' iterates a list from a prior step ('over: {{steps.X.result.items}}') "
                        "running 'do' sub-steps per item — sub-step type 'tool' only in v1. "
                        "Example: '[{\"id\":\"search\",\"type\":\"tool\",\"tool_name\":\"web_search\","
                        "\"tool_args\":{\"query\":\"latest news\"}},{\"id\":\"analyze\",\"type\":\"agent\","
                        "\"prompt\":\"Summarize the search results.\"}]'"
                    ),
                },
                "execution_config": {
                    "type": "string",
                    "description": (
                        "JSON object with execution overrides. Valid keys: "
                        "model_override (string), tools (list of tool names), "
                        "skills (list of skill IDs). Applied to agent steps."
                    ),
                },
                "bot_id": {
                    "type": "string",
                    "description": (
                        "Bot to run this Pipeline. Defaults to the current bot. "
                        "When targeting a different bot, the Run lands in that bot's "
                        "primary channel with its dispatch config."
                    ),
                },
                "scheduled_at": {
                    "type": "string",
                    "description": (
                        "When the Pipeline should run. ISO 8601 datetime or relative offset "
                        "(+30m, +2h, +1d). Omit or null to make the definition idle "
                        "(run only when invoked via `run_pipeline`)."
                    ),
                },
                "recurrence": {
                    "type": "string",
                    "description": (
                        "Repeat interval: +30m, +1h, +1d, +1w. After each successful Run, "
                        "the next occurrence is automatically scheduled. Omit for one-shot."
                    ),
                },
                "trigger_config": {
                    "type": "string",
                    "description": (
                        "JSON object configuring event-based triggers. "
                        "Example: '{\"type\":\"event\",\"event_source\":\"github\",\"event_type\":\"push\"}'. "
                        "Status will be set to 'active' when trigger_config is provided."
                    ),
                },
                "max_run_seconds": {
                    "type": "integer",
                    "description": (
                        "Maximum time in seconds a single Run is allowed before being "
                        "terminated. Overrides channel and global defaults."
                    ),
                },
            },
            "required": ["steps"],
        },
    },
}


@register(
    _DEFINE_PIPELINE_SCHEMA,
    safety_tier="control_plane",
    requires_bot_context=True,
    requires_channel_context=True,
)
async def define_pipeline(
    steps: str,
    title: str | None = None,
    execution_config: str | None = None,
    bot_id: str | None = None,
    scheduled_at: str | None = None,
    recurrence: str | None = None,
    trigger_config: str | None = None,
    max_run_seconds: int | None = None,
) -> str:
    try:
        parsed_steps = json.loads(steps)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in steps parameter."}, ensure_ascii=False)
    if not isinstance(parsed_steps, list) or not parsed_steps:
        return json.dumps({"error": "steps must be a non-empty JSON array."}, ensure_ascii=False)

    parsed_ec = None
    if execution_config:
        try:
            parsed_ec = json.loads(execution_config)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON in execution_config parameter."}, ensure_ascii=False)

    parsed_tc = None
    if trigger_config:
        try:
            parsed_tc = json.loads(trigger_config)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON in trigger_config parameter."}, ensure_ascii=False)

    return await _create_task_row(
        prompt="",
        title=title,
        parsed_steps=parsed_steps,
        parsed_ec=parsed_ec,
        parsed_tc=parsed_tc,
        workspace_file_path=None,
        scheduled_at=scheduled_at,
        bot_id=bot_id,
        reply_in_thread=False,
        recurrence=recurrence,
        trigger_rag_loop=False,
        max_run_seconds=max_run_seconds,
    )


@register({
    "type": "function",
    "function": {
        "name": "run_pipeline",
        "description": (
            "Spawn a concrete run of a pipeline definition. Accepts either "
            "the pipeline's UUID or its slug (e.g. 'orchestrator.analyze_discovery'). "
            "Pass `params` when the pipeline declares required params "
            "(see list_pipelines → params_schema). Defaults channel_id to the "
            "current channel so the run's anchor posts back where the user is. "
            "Use `get_task_result` on the returned id to fetch the output once "
            "complete, or `list_tasks(parent_task_id=<definition_id>)` for run history."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pipeline_id": {
                    "type": "string",
                    "description": (
                        "Pipeline definition UUID or slug (e.g. 'orchestrator.analyze_discovery')."
                    ),
                },
                "params": {
                    "type": "object",
                    "description": (
                        "Runtime params for this run, merged into execution_config.params "
                        "so step templates can reach them as {{params.*}}. Example: "
                        "{\"bot_id\": \"crumb\"} for the analyze_* pipelines."
                    ),
                    "additionalProperties": True,
                },
                "channel_id": {
                    "type": "string",
                    "description": (
                        "Override the channel where the run's anchor + approval widgets "
                        "post. Defaults to the current channel."
                    ),
                },
                "bot_id": {
                    "type": "string",
                    "description": (
                        "Override the bot under which the pipeline's agent steps run. "
                        "Rarely needed — most pipelines pin bot_id in the YAML."
                    ),
                },
            },
            "required": ["pipeline_id"],
        },
    },
}, safety_tier="control_plane", requires_channel_context=True)
async def run_pipeline(
    pipeline_id: str,
    params: dict | None = None,
    channel_id: str | None = None,
    bot_id: str | None = None,
) -> str:
    from app.services.task_ops import spawn_child_run

    async with async_session() as db:
        resolved = await _resolve_pipeline_id(pipeline_id, db)
        if resolved is None:
            return json.dumps(
                {"error": f"Pipeline not found: {pipeline_id!r}. Call list_pipelines to see available ids/slugs."},
                ensure_ascii=False,
            )

        # Default channel_id to the current channel — matches the UI launchpad
        # behavior where a user triggers a pipeline from a channel and expects
        # the anchor + approval widget to land there.
        effective_channel: uuid.UUID | None = None
        if channel_id:
            try:
                effective_channel = uuid.UUID(channel_id)
            except ValueError:
                return json.dumps({"error": f"Invalid channel_id: {channel_id!r}"}, ensure_ascii=False)
        else:
            effective_channel = current_channel_id.get()

        try:
            child = await spawn_child_run(
                resolved,
                db,
                params=params,
                channel_id=effective_channel,
                bot_id=bot_id,
            )
        except ValueError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        await db.commit()
        await db.refresh(child)

    result: dict = {
        "id": str(child.id),
        "parent_task_id": str(resolved),
        "status": child.status,
        "task_type": child.task_type,
        "bot_id": child.bot_id,
    }
    if child.title:
        result["title"] = child.title
    if child.steps:
        result["step_count"] = len(child.steps)
    if params:
        result["params"] = params
    return json.dumps(result, ensure_ascii=False)
