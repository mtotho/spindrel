"""Frigate MQTT listener background process declaration.

Used by IntegrationProcessManager to auto-start the MQTT event listener
alongside the agent server in both dev and production.
"""

DESCRIPTION = "Frigate MQTT event listener"
CMD = ["python", "integrations/frigate/mqtt_listener.py"]
WATCH_PATHS = ["integrations/frigate/"]
REQUIRED_ENV = ["FRIGATE_MQTT_BROKER"]
