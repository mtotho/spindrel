"""get_workspace_skill tool — lets the agent fetch workspace skill content on demand."""
import logging

from app.agent.context import current_bot_id, current_channel_id
from app.tools.registry import register
from app.services.shared_workspace import shared_workspace_service, SharedWorkspaceError

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "get_workspace_skill",
        "description": (
            "Retrieve the full content of a workspace skill file by its path. "
            "Use this when you need detailed information from one of the workspace's on-demand skills. "
            "The workspace skill index in your system context shows which skills are available."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_path": {
                    "type": "string",
                    "description": "The workspace-relative path to the skill file (e.g. 'common/skills/on-demand/reference.md')",
                },
            },
            "required": ["skill_path"],
        },
    },
})
async def get_workspace_skill(skill_path: str) -> str:
    """Fetch workspace skill content by path."""
    bot_id = current_bot_id.get()
    if not bot_id:
        return "Error: no bot context available."

    # Get workspace_id from bot config
    from app.agent.bots import get_bot
    try:
        bot = get_bot(bot_id)
    except Exception:
        return "Error: bot not found."

    # Validate path is within skill directories
    if not skill_path.endswith(".md"):
        return "Error: skill path must end with .md"
    if "/skills/" not in skill_path:
        return "Error: skill path must be within a skills/ directory"

    # Security: only allow common/skills/ and bots/{bot_id}/skills/
    valid_prefixes = [
        "common/skills/",
        f"bots/{bot_id}/skills/",
    ]
    if not any(skill_path.startswith(p) for p in valid_prefixes):
        return f"Error: access denied — skill must be in common/skills/ or bots/{bot_id}/skills/"

    try:
        result = shared_workspace_service.read_file(bot.shared_workspace_id, skill_path)
        return result["content"]
    except SharedWorkspaceError as exc:
        return f"Error reading workspace skill: {exc}"
    except Exception:
        logger.exception("Failed to read workspace skill %s", skill_path)
        return "Error: failed to read workspace skill."
