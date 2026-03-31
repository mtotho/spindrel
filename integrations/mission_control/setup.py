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
    "sidebar_section": {
        "id": "mission-control",
        "title": "MISSION CONTROL",
        "icon": "LayoutDashboard",
        "items": [
            {"label": "Dashboard", "href": "/mission-control", "icon": "LayoutDashboard"},
            {"label": "Kanban", "href": "/mission-control/kanban", "icon": "Columns"},
            {"label": "Timeline", "href": "/mission-control/timeline", "icon": "Clock"},
            {"label": "Plans", "href": "/mission-control/plans", "icon": "ClipboardCheck"},
            {"label": "Journal", "href": "/mission-control/journal", "icon": "BookOpen"},
            {"label": "Memory", "href": "/mission-control/memory", "icon": "Brain"},
            {"label": "Setup", "href": "/mission-control/setup", "icon": "HelpCircle"},
            {"label": "Settings", "href": "/mission-control/settings", "icon": "Settings"},
        ],
        "readiness_endpoint": "/api/v1/mission-control/readiness",
        "readiness_field": "dashboard",
    },
}
