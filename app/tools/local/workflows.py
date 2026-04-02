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
            "IMPORTANT: After triggering, use get_run with the returned run_id to monitor progress."
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

        # Build step summary with progress info
        step_summaries = []
        for i, state in enumerate(run.step_states):
            summary: dict = {
                "index": i,
                "status": state["status"],
            }
            if state.get("result"):
                summary["result_preview"] = str(state["result"])[:200]
            if state.get("error"):
                summary["error"] = str(state["error"])[:200]
            if state.get("started_at"):
                summary["started_at"] = state["started_at"]
            if state.get("completed_at"):
                summary["completed_at"] = state["completed_at"]
            step_summaries.append(summary)

        done = sum(1 for s in run.step_states if s["status"] == "done")
        failed = sum(1 for s in run.step_states if s["status"] == "failed")
        skipped = sum(1 for s in run.step_states if s["status"] == "skipped")
        total = len(run.step_states)

        return json.dumps({
            "run_id": str(run.id),
            "workflow_id": run.workflow_id,
            "status": run.status,
            "progress": f"{done}/{total} done, {failed} failed, {skipped} skipped",
            "done": done,
            "failed": failed,
            "skipped": skipped,
            "error": run.error,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "steps": step_summaries,
        }, indent=2)

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
