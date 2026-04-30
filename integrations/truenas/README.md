# TrueNAS Integration

This integration talks directly to TrueNAS over WebSocket. It prefers the modern JSON-RPC endpoint at `/api/current` and falls back to the legacy `/websocket` protocol for older TrueNAS installs.

MCP status: TrueNAS publishes a research-preview MCP server, but the current Spindrel integration MCP path expects URL-backed MCP servers while the TrueNAS MCP project is documented primarily as a local client binary. For v1, the direct API is the stable path for curated tools and preset widgets. A future `truenas_mcp` tool family can sit beside these tools if the MCP transport becomes a clean fit.
