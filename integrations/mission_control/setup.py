"""Mission Control integration setup manifest."""

SETUP = {
    "env_vars": [
        {
            "key": "AGENT_API_KEY",
            "required": False,
            "secret": True,
            "description": "API key for the MC container to authenticate with the agent server (proxy requests)",
        },
        {
            "key": "MISSION_CONTROL_PORT",
            "required": False,
            "description": "Dashboard port",
            "default": "9100",
        },
        {
            "key": "MISSION_CONTROL_IMAGE",
            "required": False,
            "description": "Docker image for the dashboard",
            "default": "mission-control:latest",
        },
        {
            "key": "MISSION_CONTROL_CONTAINER_NAME",
            "required": False,
            "description": "Docker container name",
            "default": "mission-control",
        },
        {
            "key": "WORKSPACE_ROOT",
            "required": False,
            "description": "Host path to agent workspaces",
            "default": "~/.agent-workspaces",
        },
    ],
    "webhook": None,
    "instructions_url": None,
}
