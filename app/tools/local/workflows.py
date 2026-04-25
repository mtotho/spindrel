# manage_workflow tool removed — superseded by:
# - define_pipeline (multi-step Pipeline definitions)
# - schedule_prompt (single-prompt Scheduled Automations)
# - call_api for full workflow CRUD (workflow backend remains for API access)
#
# The workflow backend (app/services/workflows.py, workflow_executor.py) still
# exists for API access. Only the bot-facing tool is removed.
