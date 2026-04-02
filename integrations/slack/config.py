"""Slack integration identity fields for user profile linking."""

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
