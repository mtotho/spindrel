"""Harness scenario stager — bots bound to harness runtimes.

Stages two bots:

- ``screenshot-harness-claude`` bound to the real ``claude-code`` runtime
  so the bot editor's *Agent harness* section renders something meaningful
  in the ``harness-bot-editor`` capture.
- ``screenshot-harness-demo``  bound to the env-gated ``demo`` replay
  runtime so a real harness turn can run in a Spindrel channel without
  needing Anthropic OAuth credentials. Drives the ``harness-chat-result``
  capture.

``/admin/harnesses`` and ``/admin/terminal`` need no scenario state — they
are global admin pages — but exposing this scenario here keeps the CLI
verbs (stage / capture / teardown) symmetric with flagship.

Idempotent — stable ``screenshot-harness-*`` ids and a stable
``screenshot:harness-chat`` channel client_id keep reruns dedupe-safe.
"""
from __future__ import annotations

import time

import httpx

from . import StagedState
from ..client import SpindrelClient


HARNESS_BOT_ID = "screenshot-harness-claude"
HARNESS_BOT_NAME = "Claude Code"

DEMO_BOT_ID = "screenshot-harness-demo"
DEMO_BOT_NAME = "Claude Code (demo)"

HARNESS_CHAT_CHANNEL_CLIENT_ID = "screenshot:harness-chat"
HARNESS_CHAT_CHANNEL_NAME = "Claude Code session"
HARNESS_CHAT_PROMPT = (
    "What does app/main.py do? Just give me the short version — entry point, mounts, "
    "routers, anything else worth knowing in two or three sentences."
)


def _ensure_harness_bot(
    client: SpindrelClient,
    *,
    bot_id: str,
    name: str,
    runtime: str,
    workdir: str | None = None,
) -> str:
    bot = client.ensure_bot(
        bot_id=bot_id,
        name=name,
        model="claude-sonnet-4-5",
        system_prompt="",
    )
    fields: dict = {"harness_runtime": runtime}
    if workdir:
        fields["harness_workdir"] = workdir
    client.update_bot(bot_id, **fields)
    return str(bot["id"])


def _wait_for_turn(
    client: SpindrelClient,
    *,
    channel_id: str,
    expected_min_messages: int,
    timeout_seconds: float = 15.0,
) -> int:
    """Poll the session message count until the harness turn lands.

    Returns the final count. Raises ``RuntimeError`` on timeout — the demo
    fixture is short-lived (~3s), so a generous timeout is plenty.
    """
    deadline = time.monotonic() + timeout_seconds
    last_count = 0
    while time.monotonic() < deadline:
        sid = client.get_active_session_id(channel_id)
        if sid:
            try:
                msgs = client._http.get(f"/api/v1/sessions/{sid}/messages").json()
                count = len(msgs.get("messages", msgs)) if isinstance(msgs, dict) else len(msgs)
            except (httpx.HTTPError, KeyError, ValueError):
                count = 0
            last_count = count
            if count >= expected_min_messages:
                return count
        time.sleep(0.5)
    raise RuntimeError(
        f"Harness chat did not produce {expected_min_messages} messages within "
        f"{timeout_seconds}s on channel {channel_id} (last count: {last_count})."
    )


def stage_harness(
    client: SpindrelClient,
    *,
    ssh_alias: str,
    ssh_container: str,
    dry_run: bool = False,
) -> StagedState:
    state = StagedState()

    # 1. Bot bound to the real claude-code runtime — feeds harness-bot-editor.
    claude_bot_id = _ensure_harness_bot(
        client,
        bot_id=HARNESS_BOT_ID,
        name=HARNESS_BOT_NAME,
        runtime="claude-code",
        workdir="/data/harness/screenshot-demo",
    )
    state.bots["harness_claude"] = claude_bot_id

    # 2. Bot bound to the demo replay runtime — feeds harness-chat-result.
    # Skip if the demo runtime isn't registered (env var unset on this host) —
    # the chat capture is opt-in; admin captures still work without it.
    demo_runtime_available = False
    try:
        runtimes = client._get("/api/v1/admin/harnesses").json().get("runtimes", [])
        demo_runtime_available = any(r.get("name") == "demo" for r in runtimes)
    except Exception:
        demo_runtime_available = False

    if not demo_runtime_available:
        return state

    demo_bot_id = _ensure_harness_bot(
        client,
        bot_id=DEMO_BOT_ID,
        name=DEMO_BOT_NAME,
        runtime="demo",
    )
    state.bots["harness_demo"] = demo_bot_id

    # 3. Channel bound to the demo bot.
    ch = client.ensure_channel(
        client_id=HARNESS_CHAT_CHANNEL_CLIENT_ID,
        bot_id=demo_bot_id,
        name=HARNESS_CHAT_CHANNEL_NAME,
        category="Showcase",
    )
    channel_id = str(ch["id"])
    state.channels["harness_chat"] = channel_id

    if dry_run:
        print(
            f"DRY-RUN: would ensure harness chat channel {HARNESS_CHAT_CHANNEL_CLIENT_ID!r} "
            f"and seed prompt={HARNESS_CHAT_PROMPT[:60]!r}..."
        )
        return state

    # 4. Trigger a turn — only if the channel has no recent harness reply.
    # Idempotent across reruns: if the demo replay already ran, skip the
    # chat post (the messages already there are the capture target).
    sid = client.get_active_session_id(channel_id)
    existing = 0
    if sid:
        try:
            data = client._http.get(f"/api/v1/sessions/{sid}/messages").json()
            existing = len(data.get("messages", data)) if isinstance(data, dict) else len(data)
        except Exception:
            existing = 0
    if existing < 2:
        if dry_run:
            print(
                f"DRY-RUN: would POST /chat channel={channel_id} "
                f"prompt={HARNESS_CHAT_PROMPT[:60]!r}..."
            )
        else:
            # send_message defaults bot_id to "default" — for harness bots we
            # MUST pin to the channel's owning bot or the turn dispatches to
            # the default Spindrel agent loop instead of the harness runtime.
            client._post(
                "/chat",
                json={
                    "channel_id": channel_id,
                    "bot_id": demo_bot_id,
                    "message": HARNESS_CHAT_PROMPT,
                },
            )
            # Demo fixture: 1 user msg + 1 assistant reply with embedded tool calls.
            count = _wait_for_turn(
                client,
                channel_id=channel_id,
                expected_min_messages=2,
                timeout_seconds=20.0,
            )
            print(f"harness chat turn settled with {count} messages")

    return state


def teardown_harness(client: SpindrelClient) -> None:
    # Channels first (FK), then bots.
    for ch in client.list_channels():
        cid = ch.get("client_id") or ""
        if cid == HARNESS_CHAT_CHANNEL_CLIENT_ID:
            try:
                client.delete_channel(str(ch["id"]))
            except Exception:
                pass
    for bot_id in (HARNESS_BOT_ID, DEMO_BOT_ID):
        try:
            client.delete_bot(bot_id)
        except Exception:
            pass
