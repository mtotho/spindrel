"""Mission Control background process declaration.

Used by scripts/dev-server.sh to auto-start the dashboard container
alongside the agent server in development.
"""

DESCRIPTION = "Mission Control dashboard (Docker container)"
CMD = ["python", "integrations/mission_control/container.py"]
REQUIRED_ENV = []  # No required env — works with defaults
