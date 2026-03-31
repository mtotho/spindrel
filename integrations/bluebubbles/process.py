"""BlueBubbles integration background process declaration.

Used by IntegrationProcessManager to auto-start the Socket.IO client
alongside the agent server in both dev and production.
"""

DESCRIPTION = "BlueBubbles iMessage bridge (Socket.IO)"
CMD = ["python", "integrations/bluebubbles/bb_client.py"]
WATCH_PATHS = ["integrations/bluebubbles/"]
REQUIRED_ENV = ["BLUEBUBBLES_SERVER_URL", "BLUEBUBBLES_PASSWORD"]
