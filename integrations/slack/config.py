"""Slack integration identity fields + server-side settings.

The subprocess at ``slack_bot.py`` reads ``slack_settings.py`` (env-only,
hard-required). Server-side code (renderer + tools) reads ``settings``
below, which is DB-backed with env fallback via ``make_settings``.
"""
from integrations.sdk import make_settings

_Settings = make_settings("slack", {
    "SLACK_BOT_TOKEN": "",
    "SLACK_APP_TOKEN": "",
})

settings = _Settings()


IDENTITY_FIELDS = [
    {
        "key": "user_id",
        "label": "Slack User ID",
        "description": "Find in Slack profile > \u22ee > Copy member ID",
    },
    {
        "key": "icon_emoji",
        "label": "Icon Emoji",
        "description": "Emoji used when mirroring your messages to Slack (e.g. :wave:)",
    },
]
