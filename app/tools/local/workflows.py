"""Local tool: manage_workflow — list, get, trigger, create, and monitor workflows."""

import json
import logging

from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "manage_workflow",
        "description": (
            "Manage reusable workflow templates and monitor workflow runs. "
            "Actions: list (all workflows), get (workflow definition by id), "
            "trigger (start a run, returns run_id), get_run (check run status/progress by run_id), "
            "list_runs (recent runs for a workflow id), create (new workflow). "
            "IMPORTANT: After triggering, use get_run with the returned run_id to monitor progress. "
            "For analysis/optimization, use get_run with include_definitions=true and full_results=true."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "trigger", "create", "get_run", "list_runs"],
                    "description": (
                        "list=all workflows, get=workflow definition (needs id), "
                        "trigger=start a run (needs id), get_run=check run status (needs run_id), "
                        "list_runs=recent runs for a workflow (needs id), create=new workflow."
                    ),
                },
                "id": {
                    "type": "string",
                    "description": "Workflow ID (required for get, trigger, create, list_runs).",
                },
                "run_id": {
                    "type": "string",
                    "description": "Workflow run ID — the UUID returned by trigger. Use with action=get_run to check status.",
                },
                "params": {
                    "type": "string",
                    "description": 'JSON object of parameter values for trigger, e.g. \'{"series_name": "Breaking Bad"}\'.',
                },
                "bot_id": {
                    "type": "string",
                    "description": "Bot ID to execute the workflow. Defaults to current bot if omitted.",
                },
                "channel_id": {
                    "type": "string",
                    "description": "Channel ID for workflow context. Defaults to current channel if omitted.",
                },
                "name": {
                    "type": "string",
                    "description": "Display name (required for create).",
                },
                "description": {
                    "type": "string",
                    "description": "Workflow description (for create).",
                },
                "steps": {
                    "type": "string",
                    "description": "JSON array of step definitions (for create).",
                },
                "defaults": {
                    "type": "string",
                    "description": "JSON object of default execution config (for create).",
                },
                "session_mode": {
                    "type": "string",
                    "enum": ["isolated", "shared"],
                    "description": "Override session mode for trigger (isolated=separate context per step, shared=shared channel context).",
                },
                "include_definitions": {
                    "type": "boolean",
                    "description": "For get_run: include step definitions (id, type, prompt, tool_name, tool_args, when) from the workflow snapshot. Useful for analyzing what each step was supposed to do.",
                },
                "full_results": {
                    "type": "boolean",
                    "description": "For get_run: include full step results instead of previews. Use when analyzing workflow execution in detail (e.g., for optimization or debugging).",
                },
            },
            "required": ["action"],
        },
    },
})
async def manage_workflow(
    action: str,
    id: str | None = None,
    run_id: str | None = None,
    params: str | None = None,
    bot_id: str | None = None,
    channel_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    steps: str | None = None,
    defaults: str | None = None,
    session_mode: str | None = None,
    include_definitions: bool = False,
    full_results: bool = False,
    **kwargs,
) -> str:
    import uuid

    if action == "list":
        from app.services.workflows import list_workflows
        workflows = list_workflows()
        items = []
        for w in workflows:
            items.append({
                "id": w.id,
                "name": w.name,
                "description": w.description,
                "source_type": w.source_type,
                "param_count": len(w.params or {}),
                "step_count": len(w.steps or []),
            })
        return json.dumps({"workflows": items, "count": len(items)}, indent=2)

    if action == "get":
        if not id and run_id:
            # Common confusion: bot passed run_id to "get" — redirect to get_run
            action = "get_run"
        elif not id:
            return json.dumps({"error": "id is required for get"})
        else:
            from app.services.workflows import get_workflow
            w = get_workflow(id)
            if not w:
                return json.dumps({"error": f"Workflow '{id}' not found"})
            return json.dumps({
                "id": w.id,
                "name": w.name,
                "description": w.description,
                "params": w.params,
                "secrets": w.secrets,
                "defaults": w.defaults,
                "steps": w.steps,
                "triggers": w.triggers,
                "tags": w.tags,
                "session_mode": w.session_mode,
                "source_type": w.source_type,
            }, indent=2)

    if action == "trigger":
        if not id:
            return json.dumps({"error": "id is required for trigger"})
        if session_mode and session_mode not in ("isolated", "shared"):
            return json.dumps({"error": "session_mode must be 'isolated' or 'shared'"})

        # Default bot_id/channel_id from context (follows schedule_task pattern)
        from app.agent.context import current_bot_id, current_channel_id
        effective_bot_id = bot_id or current_bot_id.get() or "default"
        effective_channel_id = channel_id

        parsed_params = {}
        if params:
            try:
                parsed_params = json.loads(params)
            except json.JSONDecodeError:
                return json.dumps({"error": "Invalid JSON in params"})

        parsed_channel_id = None
        if effective_channel_id:
            try:
                parsed_channel_id = uuid.UUID(effective_channel_id)
            except ValueError:
                return json.dumps({"error": "Invalid channel_id UUID"})
        else:
            # Fall back to current channel context
            ctx_channel = current_channel_id.get()
            if ctx_channel:
                parsed_channel_id = ctx_channel

        from app.services.workflow_executor import trigger_workflow
        try:
            run = await trigger_workflow(
                id,
                parsed_params,
                bot_id=effective_bot_id,
                channel_id=parsed_channel_id,
                triggered_by="tool",
                session_mode=session_mode,
            )
        except Exception as e:
            return json.dumps({"error": str(e)})

        return json.dumps({
            "run_id": str(run.id),
            "workflow_id": run.workflow_id,
            "status": run.status,
            "step_count": len(run.step_states),
            "hint": "Use action=get_run with this run_id to check progress.",
        })

    if action == "list_runs":
        if not id and run_id:
            # Probably meant get_run — redirect
            action = "get_run"
        elif not id:
            return json.dumps({"error": "id is required for list_runs"})
        else:
            from sqlalchemy import select
            from app.db.engine import async_session
            from app.db.models import WorkflowRun

            async with async_session() as db:
                stmt = (
                    select(WorkflowRun)
                    .where(WorkflowRun.workflow_id == id)
                    .order_by(WorkflowRun.created_at.desc())
                    .limit(10)
                )
                rows = (await db.execute(stmt)).scalars().all()

            runs = []
            for r in rows:
                done = sum(1 for s in r.step_states if s["status"] == "done")
                failed = sum(1 for s in r.step_states if s["status"] == "failed")
                total = len(r.step_states)
                runs.append({
                    "run_id": str(r.id),
                    "status": r.status,
                    "progress": f"{done}/{total} done, {failed} failed",
                    "triggered_by": r.triggered_by,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                })

            return json.dumps({"workflow_id": id, "runs": runs, "count": len(runs)}, indent=2)

    # get_run placed after list_runs so redirects from "get" and "list_runs" can reach it
    if action == "get_run":
        if not run_id:
            return json.dumps({"error": "run_id is required for get_run"})

        try:
            parsed_run_id = uuid.UUID(run_id)
        except ValueError:
            return json.dumps({"error": f"Invalid run_id UUID: {run_id}"})

        from app.db.engine import async_session
        from app.db.models import WorkflowRun

        async with async_session() as db:
            run = await db.get(WorkflowRun, parsed_run_id)

        if not run:
            return json.dumps({"error": f"Workflow run '{run_id}' not found"})

        # Resolve step definitions from snapshot (or live definition as fallback)
        snapshot = run.workflow_snapshot or {}
        snapshot_steps = snapshot.get("steps", [])

        # Build step summary with progress info
        step_summaries = []
        for i, state in enumerate(run.step_states):
            # Pull step definition info from snapshot
            step_def = snapshot_steps[i] if i < len(snapshot_steps) else {}

            summary: dict = {
                "index": i,
                "id": step_def.get("id", f"step_{i}"),
                "type": step_def.get("type", "agent"),
                "status": state["status"],
            }
            if full_results:
                if state.get("result"):
                    summary["result"] = state["result"]
            else:
                if state.get("result"):
                    summary["result_preview"] = str(state["result"])[:500]
            if state.get("error"):
                summary["error"] = str(state["error"])[:500]
            if state.get("started_at"):
                summary["started_at"] = state["started_at"]
            if state.get("completed_at"):
                summary["completed_at"] = state["completed_at"]

            # Include step definitions for analysis (prompt, tool_name, conditions, etc.)
            if include_definitions and step_def:
                definition: dict = {}
                if step_def.get("prompt"):
                    definition["prompt"] = step_def["prompt"]
                if step_def.get("tool_name"):
                    definition["tool_name"] = step_def["tool_name"]
                if step_def.get("tool_args"):
                    definition["tool_args"] = step_def["tool_args"]
                if step_def.get("when"):
                    definition["when"] = step_def["when"]
                if step_def.get("tools"):
                    definition["tools"] = step_def["tools"]
                if step_def.get("carapaces"):
                    definition["carapaces"] = step_def["carapaces"]
                if step_def.get("on_failure"):
                    definition["on_failure"] = step_def["on_failure"]
                if step_def.get("model"):
                    definition["model"] = step_def["model"]
                if definition:
                    summary["definition"] = definition

            step_summaries.append(summary)

        done = sum(1 for s in run.step_states if s["status"] == "done")
        failed = sum(1 for s in run.step_states if s["status"] == "failed")
        skipped = sum(1 for s in run.step_states if s["status"] == "skipped")
        total = len(run.step_states)

        result_dict: dict = {
            "run_id": str(run.id),
            "workflow_id": run.workflow_id,
            "status": run.status,
            "session_mode": run.session_mode,
            "progress": f"{done}/{total} done, {failed} failed, {skipped} skipped",
            "done": done,
            "failed": failed,
            "skipped": skipped,
            "error": run.error,
            "params": run.params,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "steps": step_summaries,
        }
        # Include workflow-level defaults when definitions are requested
        if include_definitions and snapshot.get("defaults"):
            result_dict["defaults"] = snapshot["defaults"]
        return json.dumps(result_dict, indent=2)

    if action == "create":
        if not id or not name:
            return json.dumps({"error": "id and name are required for create"})

        parsed_steps = []
        if steps:
            try:
                parsed_steps = json.loads(steps)
            except json.JSONDecodeError:
                return json.dumps({"error": "Invalid JSON in steps"})

        parsed_defaults = {}
        if defaults:
            try:
                parsed_defaults = json.loads(defaults)
            except json.JSONDecodeError:
                return json.dumps({"error": "Invalid JSON in defaults"})

        from app.services.workflows import create_workflow
        try:
            w = await create_workflow({
                "id": id,
                "name": name,
                "description": description,
                "steps": parsed_steps,
                "defaults": parsed_defaults,
                "source_type": "bot",
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

        return json.dumps({
            "id": w.id,
            "name": w.name,
            "created": True,
        })

    return json.dumps({"error": f"Unknown action: {action}"})
