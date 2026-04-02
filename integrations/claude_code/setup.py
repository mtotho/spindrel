"""Claude Code integration setup manifest."""

SETUP = {
    "icon": "Terminal",
    "env_vars": [
        {
            "key": "CLAUDE_CODE_MAX_TURNS",
            "required": False,
            "description": "Max agent turns per CLI invocation (default: 30)",
        },
        {
            "key": "CLAUDE_CODE_TIMEOUT",
            "required": False,
            "description": "Timeout in seconds for CLI execution (default: 1800 = 30 min)",
        },
        {
            "key": "CLAUDE_CODE_PERMISSION_MODE",
            "required": False,
            "description": "CLI permission mode: default, acceptEdits, plan, bypassPermissions (default: bypassPermissions)",
        },
        {
            "key": "CLAUDE_CODE_ALLOWED_TOOLS",
            "required": False,
            "description": "Comma-separated pre-approved tools (default: Read,Write,Edit,Bash,Glob,Grep)",
        },
        {
            "key": "CLAUDE_CODE_MODEL",
            "required": False,
            "description": "Model override (empty = CLI default)",
        },
        {
            "key": "CLAUDE_CODE_MAX_RESUME_RETRIES",
            "required": False,
            "description": "Resume attempts on failure (default: 1)",
        },
    ],
    "webhook": None,
    "instructions_url": None,
    "python_dependencies": [],
}
