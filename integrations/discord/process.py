"""Discord integration background process declaration.

Used by IntegrationProcessManager to auto-start the Discord bot
alongside the agent server in both dev and production.
"""

DESCRIPTION = "Discord bot (gateway websocket)"
CMD = ["python", "integrations/discord/discord_bot.py"]
WATCH_PATHS = ["integrations/discord/"]
REQUIRED_ENV = ["DISCORD_TOKEN"]
