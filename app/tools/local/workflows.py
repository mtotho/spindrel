# manage_workflow tool removed — deprecated in favor of:
# - schedule_task with steps parameter (for pipeline tasks)
# - call_api for full workflow CRUD (legacy workflows)
#
# The workflow backend (app/services/workflows.py, workflow_executor.py) still
# exists for legacy runs and API access. Only the bot-facing tool is removed.
