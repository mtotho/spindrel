"""Widget author surface — re-exports from ``app.services.widget_py``.

Widget bundles use::

    from spindrel.widget import on_action, on_cron, on_event, ctx

    @on_action("save")
    async def save(args):
        await ctx.db.execute("insert into items(text) values (?)", [args["text"]])
        return {"ok": True}
"""
from app.services.widget_py import (
    ctx,
    on_action,
    on_cron,
    on_event,
)

__all__ = ["ctx", "on_action", "on_cron", "on_event"]
