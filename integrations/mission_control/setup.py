"""Mission Control integration setup manifest."""

SETUP = {
    "version": "2.0",
    "icon": "LayoutDashboard",
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
    "web_ui": {
        "static_dir": "dashboard/dist",
        "dev_port": 5173,
    },
    "activation": {
        "carapaces": ["mission-control"],
        "requires_workspace": True,
        "description": "Project management with task boards, plans, and timelines",
        "compatible_templates": ["mission-control"],
    },
    "webhook": None,
    "instructions_url": None,
    "sidebar_section": {
        "id": "mission-control",
        "title": "MISSION CONTROL",
        "icon": "LayoutDashboard",
        "items": [
            {"label": "Dashboard", "href": "/integration/mission_control", "icon": "LayoutDashboard"},
            {"label": "Kanban", "href": "/integration/mission_control/kanban", "icon": "Columns"},
            {"label": "Timeline", "href": "/integration/mission_control/timeline", "icon": "Clock"},
            {"label": "Plans", "href": "/integration/mission_control/plans", "icon": "ClipboardCheck"},
            {"label": "Journal", "href": "/integration/mission_control/journal", "icon": "BookOpen"},
            {"label": "Memory", "href": "/integration/mission_control/memory", "icon": "Brain"},
            {"label": "Setup", "href": "/integration/mission_control/setup", "icon": "HelpCircle"},
            {"label": "Settings", "href": "/integration/mission_control/settings", "icon": "Settings"},
        ],
        "readiness_endpoint": "/integrations/mission_control/readiness",
        "readiness_field": "dashboard",
    },
}
