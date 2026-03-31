"""Frigate integration setup manifest."""

SETUP = {
    "icon": "Camera",
    "env_vars": [
        {"key": "FRIGATE_URL", "required": True, "description": "Frigate NVR base URL (e.g. http://frigate:5000)"},
        {"key": "FRIGATE_API_KEY", "required": False, "description": "Bearer token for Frigate API auth", "secret": True},
        {"key": "FRIGATE_MAX_CLIP_BYTES", "required": False, "description": "Max clip download size (default 50MB)"},
        {"key": "FRIGATE_MQTT_BROKER", "required": False, "description": "MQTT broker hostname for push events"},
        {"key": "FRIGATE_MQTT_PORT", "required": False, "description": "MQTT broker port (default 1883)"},
        {"key": "FRIGATE_MQTT_USERNAME", "required": False, "description": "MQTT auth username"},
        {"key": "FRIGATE_MQTT_PASSWORD", "required": False, "description": "MQTT auth password", "secret": True},
        {"key": "FRIGATE_MQTT_TOPIC_PREFIX", "required": False, "description": "MQTT topic prefix (default: frigate)"},
        {"key": "FRIGATE_MQTT_CAMERAS", "required": False, "description": "Global camera filter for MQTT listener (empty = all)"},
        {"key": "FRIGATE_MQTT_LABELS", "required": False, "description": "Global label filter for MQTT listener (e.g. person,car)"},
        {"key": "FRIGATE_MQTT_MIN_SCORE", "required": False, "description": "Global minimum detection score for MQTT listener (default 0.6)"},
        {"key": "FRIGATE_MQTT_COOLDOWN", "required": False, "description": "Seconds between alerts for same camera+label (default 300)"},
    ],
    "webhook": {
        "path": "/integrations/frigate/webhook",
        "description": "Frigate event receiver (MQTT listener posts here for channel fan-out)",
    },
    "instructions_url": None,
    "binding": {
        "client_id_prefix": "frigate:",
        "client_id_placeholder": "frigate:events",
        "client_id_description": "Frigate event stream (typically frigate:events)",
        "display_name_placeholder": "Frigate Events",
        "filter_schema": {
            "cameras": {"type": "string", "description": "Comma-separated camera filter (e.g. front_door,driveway)"},
            "labels": {"type": "string", "description": "Comma-separated label filter (e.g. person,car)"},
            "min_score": {"type": "number", "description": "Minimum detection score (0-1)"},
        },
    },
}
