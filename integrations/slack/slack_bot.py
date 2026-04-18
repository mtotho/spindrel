"""
Slack Socket Mode bot: routes Slack messages to the agent server POST /chat.
Runs as a separate process; no inbound ports. Configure via slack_config.yaml and env.
"""
import asyncio
import sys
from pathlib import Path

# Same-dir imports work when run as `python slack-integration/slack_bot.py`; ensure
# they also work under `run_path`, tests, or if repo root is earlier on sys.path.
_SLACK_DIR = str(Path(__file__).resolve().parent)
if _SLACK_DIR not in sys.path:
    sys.path.insert(0, _SLACK_DIR)

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from slack_settings import APP_LEVEL_TOKEN, BOT_TOKEN
from message_handlers import register_message_handlers
from slash_commands import register_slash_commands
from approval_handlers import register_approval_handlers
from channel_approval_handlers import register_channel_approval_handlers
from reaction_handlers import register_reaction_handlers
from app_home import register_app_home
from shortcuts import register_shortcuts
from view_handlers import register_view_handlers
from modal_action_handler import register_modal_action_handler

app = AsyncApp(token=BOT_TOKEN)
register_message_handlers(app)
register_slash_commands(app)
register_approval_handlers(app)
register_channel_approval_handlers(app)
register_reaction_handlers(app)
register_app_home(app)
register_shortcuts(app)
register_view_handlers(app)
register_modal_action_handler(app)


async def main():
    handler = AsyncSocketModeHandler(app, APP_LEVEL_TOKEN)
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
