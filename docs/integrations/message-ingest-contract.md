# Message Ingest Contract

When your integration receives a human-authored message and submits it to the
agent — via [`submit_chat`](../api/chat.md), `inject_message`, or
`store_passive_message_http` — it MUST follow this rule:

> `content` is the raw text the human typed. Nothing else.
> Routing, identity, threading, and platform-native tokens go in `msg_metadata`.

The assembly layer composes the LLM-facing attribution header (`[Name]:` or
`[Name (<@U…>)]:`) and injects thread summaries as system blocks. Do not do
that formatting at ingest — it produces double attribution, drifts the
persisted content away from what the human actually said, and forces the UI
to carry one bespoke regex per integration.

---

## Why this exists

Historically, Slack/Discord/BlueBubbles each invented their own content
prefix:

```
[Slack channel:C06RY3YBSLE user:Olivia (<@U06STGBF4Q0>)] testing from slack
[Discord channel:123456 user:Olivia] testing from discord
[Olivia]: testing from imessage
```

Three consequences fell out of that choice:

1. **`Message.content` diverged from reality.** The DB no longer stores what
   the human typed.
2. **The UI needed one regex per integration to strip the prefix back off.**
   When Slack tweaked the prefix to include `(<@U…>)`, the UI regex broke
   silently and the raw junk leaked into the web chat. Discord never had a
   UI stripper — so every Discord message renders its raw prefix today.
3. **Double attribution.** The assembly layer already composes `[Name]:`
   from metadata ([`_apply_user_attribution`](https://github.com/…)); the
   ingest-baked prefix stacked on top, so the LLM saw
   `[Olivia]: [Slack channel:… user:Olivia (<@U…>)] text`.

The right layering: integrations emit clean data; the assembly layer turns
data into LLM-facing text.

---

## The canonical metadata shape

Declared as [`IngestMessageMetadata`][schema] in
`app/routers/chat/_schemas.py`:

[schema]: https://github.com/…

| field                 | required | example                       | meaning                                                                             |
| --------------------- | -------- | ----------------------------- | ----------------------------------------------------------------------------------- |
| `source`              | ✓        | `"slack"`                     | Integration identifier                                                              |
| `sender_id`           | ✓        | `"slack:U06STGBF4Q0"`         | Namespaced external id (`<source>:<external_id>`)                                    |
| `sender_display_name` | ✓        | `"Olivia"`                    | UI label + LLM attribution name                                                     |
| `sender_type`         | ✓        | `"human"` \| `"bot"`          | Cross-bot relay vs. real person                                                     |
| `channel_external_id` |          | `"C06RY3YBSLE"`               | Platform-native channel/chat id                                                     |
| `mention_token`       |          | `"<@U06STGBF4Q0>"`            | Platform-native tag syntax the agent echoes back to @-mention this user in a reply |
| `thread_context`      |          | `"[Thread context — …]\n- …"` | Multi-line LLM-ready prior-message summary; injected as a system block              |
| `is_from_me`          |          | `true`                        | BlueBubbles: message was from the local user's own handle                           |
| `passive`             |          | `false`                       | Store only; don't run the agent                                                     |
| `trigger_rag`         |          | `true`                        | Whether retrieval should consider this turn                                         |
| `recipient_id`        |          | `"bot:calc-bot"`              | Intended recipient                                                                  |

Extra keys are allowed (forward-compat); only the four required fields are
validated.

---

## Worked example: Slack inbound

```python
# integrations/slack/message_handlers.py
_slack_display_name = await _resolve_slack_display_name(client, user)

thread_summary = ""
if thread_ts:
    thread_summary = await _fetch_thread_parent_summary(
        client, channel, thread_ts, message_ts,
    )

msg_metadata = {
    "source": "slack",
    "sender_id": f"slack:{user}",
    "sender_display_name": _slack_display_name,
    "sender_type": "bot" if is_bot_sender else "human",
    "channel_external_id": channel,
    # Required so the agent can tag the user back: Slack needs "<@U123>"
    # verbatim — plain "@Name" does not notify.
    "mention_token": None if is_bot_sender else f"<@{user}>",
    # Optional; assembly injects this as a system block adjacent to the turn.
    "thread_context": thread_summary or None,
    # Integration-specific routing/run hints (extra fields allowed):
    "passive": is_passive,
    "include_in_memory": config["passive_memory"],
    "trigger_rag": mentioned or not config["require_mention"],
    "recipient_id": f"bot:{bot_id}" if mentioned else None,
}

await submit_chat(
    message=f"{text}{appended}",     # ← raw user text, nothing else
    bot_id=bot_id,
    client_id=client_id,
    attachments=attachments or None,
    file_metadata=file_metadata or None,
    dispatch_type="slack",
    dispatch_config={...},
    msg_metadata=msg_metadata,
)
```

What the LLM sees after assembly:

```
[Thread context — prior messages in this thread, newest last]
- Ash (<@U03…>): are we still on for tomorrow?
- Olivia (<@U06…>): yeah, lemme confirm

[Olivia (<@U06STGBF4Q0>)]: testing from slack
```

The `<@U06STGBF4Q0>` inside the attribution prefix is what lets the agent
reply with a working @-mention — it copies the token verbatim into its
outbound message.

---

## Worked example: Discord inbound

```python
msg_metadata = {
    "source": "discord",
    "sender_id": f"discord:{user}",
    "sender_display_name": message.author.display_name,
    "sender_type": "bot" if is_bot_sender else "human",
    "channel_external_id": str(channel_id),
    "mention_token": None if is_bot_sender else f"<@{user}>",
}

await submit_chat(
    message=f"{text}{appended}",
    bot_id=bot_id,
    client_id=client_id,
    dispatch_type="discord",
    dispatch_config={...},
    msg_metadata=msg_metadata,
)
```

---

## Worked example: BlueBubbles inbound (no mention token)

```python
# iMessage has no mention-token concept; mention_token stays unset.
extra_metadata = {
    "sender_id": f"bb:{sender_address}",
    "sender_type": "human",
    "sender_display_name": sender_label,   # "Me" for is_from_me, else name
    "channel_external_id": chat_guid,
    "is_from_me": is_from_me,
    "message_guid": data.get("guid", ""),
}

await inject_message(
    session_id, text,                      # ← raw text
    source="bluebubbles",
    extra_metadata=extra_metadata,
    ...
)
```

---

## What the assembly layer does on your behalf

Implemented in `app/routers/chat/_context.py` + `app/agent/message_formatting.py`:

- [`compose_attribution_prefix(meta)`][compose] builds `[Name]:` — or
  `[Name (<@U…>)]:` when `mention_token` is set — and
  [`_apply_user_attribution(messages)`][apply] prepends it to user turns.
- [`compose_thread_context_block(meta)`][thread] pulls `thread_context` out
  and [`_inject_thread_context_blocks(messages)`][inject] inserts it as a
  system message immediately above the user turn.
- Both are idempotent: re-entry leaves already-formatted turns alone.

[compose]: https://github.com/…
[apply]: https://github.com/…
[thread]: https://github.com/…
[inject]: https://github.com/…

---

## Checklist for a new integration

- [ ] `content` passed to `submit_chat` / `inject_message` is the raw user
      text. No brackets, no source name, no channel id, no sender name.
- [ ] `msg_metadata` has `source`, `sender_id`, `sender_display_name`,
      `sender_type`.
- [ ] If the platform has a native @-tag token (Slack `<@U…>`, Discord
      `<@…>`), populate `mention_token`.
- [ ] If the platform delivers prior-message thread context (Slack threaded
      replies, email reply chains), put the LLM-ready summary in
      `thread_context` — NOT in `content`.
- [ ] The UI needs no per-integration regex to render your messages — it
      reads `sender_display_name` + `source` from metadata and displays
      `content` verbatim.

---

## Historic rows

Rows persisted before this contract shipped still carry their baked-in
prefixes. The UI has a transitional `stripLegacyIngestPrefix(content, source)`
helper (see `ui/src/components/chat/messageUtils.ts`) that peels off the
historic shapes for display. It is scheduled for removal after 2026-Q3 —
historic rows will have aged out of active context windows by then.

No data migration is planned: historic LLM context has already been observed
with the old prefixes, and rewriting history creates more surprises than it
prevents.
