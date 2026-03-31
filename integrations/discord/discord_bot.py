"""
Discord Gateway bot: routes Discord messages to the agent server POST /chat.
Runs as a separate process; connects via WebSocket Gateway. Configure via discord_config.yaml and env.
"""
import asyncio
import logging
import sys
from pathlib import Path

# Same-dir imports work when run as `python integrations/discord/discord_bot.py`
_DISCORD_DIR = str(Path(__file__).resolve().parent)
if _DISCORD_DIR not in sys.path:
    sys.path.insert(0, _DISCORD_DIR)

import discord
from discord import app_commands

from discord_settings import DISCORD_TOKEN
from message_handlers import dispatch
from slash_commands import register_slash_commands
from approval_handlers import handle_approval_interaction, is_approval_custom_id

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("discord_bot")

# Intents: need message_content to read message text, guilds for channel info
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = False  # not needed

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Register slash commands on the tree
register_slash_commands(tree)


@client.event
async def on_ready():
    """Sync slash commands to all guilds on ready."""
    logger.info("Discord bot ready as %s (id=%s)", client.user, client.user.id)
    logger.info("Connected to %d guild(s)", len(client.guilds))
    try:
        synced = await tree.sync()
        logger.info("Synced %d application commands", len(synced))
    except Exception:
        logger.exception("Failed to sync application commands")


@client.event
async def on_message(message: discord.Message):
    """Handle incoming messages."""
    # Ignore our own messages
    if message.author == client.user:
        return

    # Ignore DMs for now (only handle guild channels)
    if not message.guild:
        return

    # Check if the bot was mentioned
    mentioned = client.user in message.mentions if client.user else False

    # Dispatch to the message handler
    await dispatch(message, mentioned=mentioned)


@client.event
async def on_interaction(interaction: discord.Interaction):
    """Handle button interactions (approval buttons).

    The CommandTree handles slash command interactions automatically.
    This handler catches component interactions (buttons) that aren't
    part of slash commands.
    """
    if interaction.type != discord.InteractionType.component:
        return

    custom_id = interaction.data.get("custom_id", "")
    if is_approval_custom_id(custom_id):
        await handle_approval_interaction(interaction)


async def main():
    async with client:
        await client.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
