"""Example integration setup manifest."""

SETUP = {
    "icon": "Plug",
    "env_vars": [
        {"key": "EXAMPLE_API_KEY", "required": False, "description": "Optional API key for the example service"},
    ],
    "webhook": None,
    "instructions_url": None,
}
