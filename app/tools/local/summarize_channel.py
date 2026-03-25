"""Agent tool for summarizing historical channel messages."""
from app.agent.context import current_channel_id
from app.tools.registry import register


@register({
    "type": "function",
    "function": {
        "name": "summarize_channel",
        "description": (
            "Summarize historical messages in this channel. Fetches raw turns "
            "(not compaction summaries) and produces a focused summary. "
            "Supports date range filtering and skip/take pagination."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skip": {
                    "type": "integer",
                    "description": "Turns to skip from oldest. Ignored when date range is set. Default 0.",
                },
                "take": {
                    "type": "integer",
                    "description": "Max turns to summarize. Default 100.",
                },
                "target_size": {
                    "type": "integer",
                    "description": "Target summary size in characters. Falls back to channel default (~1000).",
                },
                "prompt": {
                    "type": "string",
                    "description": "Custom focus prompt, e.g. 'what decisions were made about the database schema'. Combined with the base summarizer prompt.",
                },
                "start_date": {
                    "type": "string",
                    "description": "ISO 8601 date/datetime. Summarize messages from this point forward. Can be used alone or with end_date.",
                },
                "end_date": {
                    "type": "string",
                    "description": "ISO 8601 date/datetime. Summarize messages before this point. Can be used alone or with start_date.",
                },
            },
        },
    },
})
async def summarize_channel(
    skip: int = 0,
    take: int | None = None,
    target_size: int | None = None,
    prompt: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    channel_id = current_channel_id.get()
    if not channel_id:
        return "Error: no channel_id in context."

    from app.services.summarizer import summarize_messages
    return await summarize_messages(
        channel_id=channel_id,
        skip=skip,
        take=take,
        target_size=target_size,
        prompt=prompt,
        start_date=start_date,
        end_date=end_date,
    )
