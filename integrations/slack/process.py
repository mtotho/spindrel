"""Slack integration background process declaration.

Used by scripts/dev-server.sh (via scripts/list_integration_processes.py) to
auto-start the Slack Bolt bot alongside the agent server in development.
"""

DESCRIPTION = "Slack Bolt bot (socket mode)"
CMD = ["python", "integrations/slack/slack_bot.py"]
REQUIRED_ENV = ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"]
