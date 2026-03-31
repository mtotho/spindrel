"""Slack integration background process declaration.

Used by IntegrationProcessManager to auto-start the Slack Bolt bot
alongside the agent server in both dev and production.
"""

DESCRIPTION = "Slack Bolt bot (socket mode)"
CMD = ["python", "integrations/slack/slack_bot.py"]
WATCH_PATHS = ["integrations/slack/"]
REQUIRED_ENV = ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"]
