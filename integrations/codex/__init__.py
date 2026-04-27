"""Codex harness integration — drives the OpenAI Codex CLI's app-server protocol.

Spawns the user-installed ``codex`` binary as ``codex app-server`` and speaks
JSON-RPC over its stdin/stdout. No third-party Python SDK is involved; the
binary is the deployment prerequisite.
"""
