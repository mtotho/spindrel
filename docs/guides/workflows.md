# Workflows (Deprecated)

!!! warning "Deprecated — use Pipelines"
    Workflows have been superseded by **[Pipelines](pipelines.md)**. The workflow admin UI is hidden, the `workflows/` YAML directory is no longer loaded, and bot tools like `manage_workflow` have been removed. Existing workflow rows remain in the database as read-only history.

    If you land here from a stale link, read **[Pipelines](pipelines.md)** — it covers the same ground (multi-step automation, conditions, approval gates, parameters, scheduling, cross-bot delegation) with a cleaner model: one storage type (`Task`), per-channel subscriptions, and in-chat sub-session rendering.

## Why the switch

Workflows and tasks ran on two parallel code paths. Pipelines merge them:

| Workflows (old) | Pipelines (new) |
|---|---|
| Separate `Workflow` model + `manage_workflow` tool + visual editor | One `Task` model with a `steps:` array |
| Triggered via `manage_workflow run`, heartbeat `workflow_id`, or API | Triggered via `/admin/tasks/<id>/launchpad`, `run_pipeline` tool, heartbeat `pipeline_id`, or `channel_pipeline_subscriptions` cron |
| Workflow runs posted plain lifecycle messages to chat | Pipeline runs render as a chat-native **sub-session** — a modal or docked transcript showing every step's LLM thinking, tool widgets, and output |
| No per-channel subscriptions — workflows were global | `channel_pipeline_subscriptions` binds a pipeline to a channel with its own cron schedule |
| `on_error` branching on the whole run | Step-level `fail_if` + tool-error signaling |

## Migration

There is no automatic migration. Any workflow YAML you were loading from `workflows/` should be reauthored as a pipeline:

1. Create a new task at **Admin → Tasks → New**.
2. Set `pipeline_mode: true` and copy each workflow step into the `steps:` array.
3. If the workflow was triggered by a heartbeat, switch the heartbeat config from `workflow_id` to `pipeline_id`.
4. If the workflow was called from a bot via `manage_workflow run`, use the `run_pipeline(pipeline_id, params, channel_id)` tool instead.

See **[Pipelines](pipelines.md)** for the step type reference (`exec`, `tool`, `agent`, `user_prompt`, `foreach`), conditions, `fail_if`, and the full configuration surface.
