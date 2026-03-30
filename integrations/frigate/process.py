"""Frigate MQTT listener background process declaration.

Used by scripts/dev-server.sh (via scripts/list_integration_processes.py) to
auto-start the MQTT event listener alongside the agent server in development.
"""

DESCRIPTION = "Frigate MQTT event listener"
CMD = [
    "watchfiles",
    "--filter", "python",
    "python integrations/frigate/mqtt_listener.py",
    "integrations/frigate/",
]
REQUIRED_ENV = ["FRIGATE_MQTT_BROKER"]
