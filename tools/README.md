# User tools

Drop Python modules here (`.py` files). At server startup each file is imported; any function decorated with `@tool` (from `app.tools.tool`) or `@register` (from `app.tools.registry`) is registered as a local tool.

List the tool name in your bot’s `local_tools` in `bots/*.yaml`, same as built-in tools.

Additional directories can be set with the `TOOL_DIRS` environment variable (colon-separated paths, absolute or relative to the process working directory).

See [TOOL_RAG_PLAN.md](../TOOL_RAG_PLAN.md) for how dynamic tool retrieval uses embeddings for bots with many MCP tools.
