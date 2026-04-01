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
        "config_fields": [
            {"key": "cameras", "type": "string", "label": "Cameras", "description": "Comma-separated camera names (empty = all)", "default": ""},
            {"key": "labels", "type": "string", "label": "Labels", "description": "Comma-separated object labels (empty = all)", "default": ""},
            {"key": "min_score", "type": "number", "label": "Min Score", "description": "Minimum detection score (0-1)", "default": 0.5},
        ],
    },
}
