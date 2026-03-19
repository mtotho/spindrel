# Plan: Slack File Attachments + Image Generation

## What I still don't have (assumptions noted where they apply)

- **`app/agent/loop.py`** — `run(..., user_message=..., attachments=...)` returns `RunResult` with `.response`, `.transcript`, `.client_actions`.
- **`slack-integration/message_handlers.py`** — `dispatch(..., say, client, files=...)` calls `post_chat` with optional `attachments`.
- **`slack-integration/agent_client.py`** — `httpx` POST to `/chat`; **`BOT_TOKEN`** for `url_private_download` is imported from `slack_settings` (not a separate module name).
- **`app/routers/chat.py`** — Chat API lives here (not `app/api/chat.py`). `ChatRequest` includes `attachments`.
- **`app/db/models.py`** — `Message.content` is `Text`; multimodal turns are stored as **JSON strings** with **image data redacted** to avoid huge rows (see `app/services/sessions.py`).
- **Slack YAML** — Bot definition is `bots/slack_bot.yaml` (repo layout), not `slack_bot.yaml` at repo root.

---

## Phases

### Phase 1 — Text file ingestion (Slack-only changes)

No server changes. The Slack bot downloads text files and appends content inline to the message string before dispatching.

**`slack-integration/message_handlers.py`**

Add:
```python
TEXT_MIMES = {
    "text/plain", "text/markdown", "text/csv", "text/html",
    "application/json", "application/xml", "text/x-python",
    "application/x-yaml",
}
MAX_TEXT_FILE_BYTES = 32_000  # ~8k tokens

async def _download_slack_file(url: str) -> bytes:
    from slack_settings import BOT_TOKEN  # or however it's imported
    r = await http.get(url, headers={"Authorization": f"Bearer {BOT_TOKEN}"})
    r.raise_for_status()
    return r.content

async def _extract_text_from_files(files: list[dict]) -> tuple[str, list[dict]]:
    """
    Returns (appended_text_for_message, image_file_list).
    Text files: downloaded, content appended inline.
    Image files: returned as dicts for Phase 2 processing.
    """
    text_parts = []
    image_files = []
    for f in (files or []):
        mime = f.get("mimetype", "")
        name = f.get("name", "attachment")
        url = f.get("url_private_download") or f.get("url_private")
        if not url:
            continue
        if mime in TEXT_MIMES or mime.startswith("text/"):
            try:
                data = await _download_slack_file(url)
                content = data[:MAX_TEXT_FILE_BYTES].decode("utf-8", errors="replace")
                truncated = len(data) > MAX_TEXT_FILE_BYTES
                suffix = "\n[...truncated]" if truncated else ""
                text_parts.append(f"\n\n[Attached file: {name}]\n```\n{content}{suffix}\n```")
            except Exception as e:
                text_parts.append(f"\n[Could not fetch {name}: {e}]")
        elif mime.startswith("image/"):
            image_files.append(f)
    return "".join(text_parts), image_files
```

Update `dispatch` signature:
```python
async def dispatch(channel: str, user: str, text: str, say, files: list = None):
    appended, image_files = await _extract_text_from_files(files or [])
    # image_files unused until Phase 2
    full_text = f"[Slack channel:{channel} user:{user}] {text}{appended}"
    # ... rest unchanged, pass full_text as message
```

Update `on_message` and `on_mention` to pass `files=event.get("files", [])`.

**Slack app manifest**: add `files:read` scope.

**No server changes in Phase 1.**

---

### Phase 2 — Image vision (server + Slack changes)

**`slack-integration/message_handlers.py`**

Update `_extract_text_from_files` → rename to `_process_slack_files`, return image attachments as structured dicts:
```python
async def _process_slack_files(files: list[dict]) -> tuple[str, list[dict]]:
    """Returns (text_to_append, attachments_for_api)."""
    text_parts = []
    attachments = []
    for f in (files or []):
        mime = f.get("mimetype", "")
        name = f.get("name", "attachment")
        url = f.get("url_private_download") or f.get("url_private")
        if not url:
            continue
        try:
            data = await _download_slack_file(url)
        except Exception as e:
            text_parts.append(f"\n[Could not fetch {name}: {e}]")
            continue
        if mime in TEXT_MIMES or mime.startswith("text/"):
            content = data[:MAX_TEXT_FILE_BYTES].decode("utf-8", errors="replace")
            text_parts.append(f"\n\n[Attached file: {name}]\n```\n{content}\n```")
        elif mime.startswith("image/"):
            attachments.append({
                "type": "image",
                "content": base64.b64encode(data).decode(),
                "mime_type": mime,
                "name": name,
            })
    return "".join(text_parts), attachments
```

Update `dispatch` to pass `attachments` to `agent_client.post_chat`.

Update `dispatch` to handle `client_actions` in response (upload_image — Phase 3).

**`slack-integration/agent_client.py`**

Add `attachments` param to `post_chat`:
```python
async def post_chat(
    message: str,
    bot_id: str,
    client_id: str,
    session_id: str,
    attachments: list[dict] = None,
) -> dict:
    payload = {
        "message": message,
        "bot_id": bot_id,
        "client_id": client_id,
        "session_id": session_id,
    }
    if attachments:
        payload["attachments"] = attachments
    r = await http.post(...)
    ...
```

**`app/api/chat.py`**

Add:
```python
class Attachment(BaseModel):
    type: str                   # "image" (extensible later)
    content: str                # base64-encoded bytes
    mime_type: str = "image/jpeg"
    name: str = ""
```

Add to `ChatRequest`:
```python
attachments: list[Attachment] = []
```

Pass `req.attachments` into `run(...)` call (both `/chat` and `/chat/stream`).

**`app/agent/loop.py`**

Add `attachments` parameter to `run()` and `run_stream()`.

When building the user turn, if attachments are present, construct multipart content:
```python
def _build_user_content(text: str, attachments: list) -> str | list:
    if not attachments:
        return text
    parts = [{"type": "text", "text": text}]
    for att in attachments:
        if att.type == "image":
            parts.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": att.mime_type,
                    "data": att.content,
                }
            })
    return parts
```

Note: this is Anthropic-style multipart. If routing through LiteLLM to non-Anthropic models, use OpenAI-style instead:
```python
{"type": "image_url", "image_url": {"url": f"data:{att.mime_type};base64,{att.content}"}}
```
Check what LiteLLM expects for your configured models. If using a mix, you may need to branch on `bot.model`.

**`app/services/sessions.py` / `app/db/models.py`**

`persist_turn` currently does `content=msg.get("content")`. When content is a list (multipart), it must be serialized before DB storage.

Two options:
- **Option A (minimal)**: JSON-serialize list content in `persist_turn`, deserialize in `_message_to_dict`. Keep `Message.content` as `Text`.
- **Option B (cleaner)**: Change `Message.content` to `JSON` column type with Alembic migration.

Recommendation: **Option A** unless you want a migration now.

`persist_turn` change:
```python
content = msg.get("content")
if isinstance(content, list):
    content = json.dumps(content)
record = Message(..., content=content, ...)
```

`_message_to_dict` change:
```python
if msg.content is not None:
    try:
        parsed = json.loads(msg.content)
        d["content"] = parsed if isinstance(parsed, list) else msg.content
    except (json.JSONDecodeError, TypeError):
        d["content"] = msg.content
```

---

### Phase 3 — Image generation tool + Slack upload

**`app/tools/local/image.py`**

- `generate_image` is registered with **`@register`** and the **real implementation** runs through `call_local_tool` like other context-free tools (no `call_image_tool` branch in `loop.py`).
- Returns JSON with `message` + embedded `client_action` for `upload_image`; the loop’s generic `client_action` extraction applies.

Tool schema:
```python
@register({
    "type": "function",
    "function": {
        "name": "generate_image",
        "description": "Generate an image from a text prompt. Returns the image to the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Detailed image description."}
            },
            "required": ["prompt"],
        },
    },
})
async def generate_image(prompt: str) -> str:
    ...
```

Implementation (summary):
- Calls LiteLLM (same routing logic as OWUI tool, stripped of OWUI upload)
- On success, returns JSON string:
```python
return json.dumps({
    "message": "Image generated successfully.",
    "client_action": {
        "type": "upload_image",
        "data": b64_png_string,
        "filename": "generated.png",
        "caption": "",
    }
})
```

**`app/agent/loop.py`** — client_action extraction

After a tool executes and returns a result string, check for embedded `client_action`:
```python
try:
    parsed = json.loads(tool_result_str)
    if isinstance(parsed, dict) and "client_action" in parsed:
        result.client_actions.append(parsed["client_action"])
        # Replace the tool result content with just the message for the LLM
        tool_result_str = parsed.get("message", "Done.")
except (json.JSONDecodeError, TypeError):
    pass
```

This keeps `client_actions` decoupled from the LLM — the model only sees the short message, not the raw base64.

**`slack-integration/message_handlers.py`** — handle upload_image client_action

In `dispatch`, after getting the response:
```python
for action in body.get("client_actions", []):
    if action.get("type") == "upload_image":
        img_bytes = base64.b64decode(action["data"])
        await app.client.files_upload_v2(
            channel=channel,
            content=img_bytes,
            filename=action.get("filename", "generated.png"),
            initial_comment=action.get("caption", "") or None,
        )
```

Note: `files_upload_v2` requires `files:write` scope and the bot being a member of the channel.

**`slack_bot.yaml`** — add tool:
```yaml
local_tools:
  - generate_image   # add to existing list
```

**Slack app manifest**: add `files:write` scope.

---

## Summary of files changed

| File | Phase | Change |
|------|-------|--------|
| `slack-integration/message_handlers.py` | 1, 2, 3 | File download, text append, image attachments, client_action handler |
| `slack-integration/agent_client.py` | 2 | `attachments` param in payload |
| `app/routers/chat.py` | 2 | `Attachment` model, `attachments` on `ChatRequest`, pass to `run()` |
| `app/agent/loop.py` | 2, 3 | `_build_user_content()` multipart, `attachments` param, client_action extraction |
| `app/services/sessions.py` | 2 | Serialize/deserialize list content in persist/load |
| `app/tools/local/image.py` | 3 | `generate_image` registered with full impl |
| `slack_bot.yaml` | 3 | Add `generate_image` to `local_tools` |
| Slack app manifest | 1, 3 | Add `files:read`, `files:write` scopes |

---

## Implementation (done in repo)

- **Vision**: `_build_user_message_content` in `app/agent/loop.py` uses **OpenAI-style** `image_url` + `data:{mime};base64,...` (matches `AsyncOpenAI` + LiteLLM).
- **Tool `client_action`**: After each tool call, if the result JSON includes `client_action`, it is appended to the response’s `client_actions` and only `message` is stored in the tool message for the LLM (`app/agent/loop.py`).
- **Image generation**: `app/tools/local/image.py` + `IMAGE_GENERATION_MODEL` in `app/config.py`. Uses `images.generate` with `response_format=b64_json`, URL fallback if the backend returns a URL.
- **DB**: Option A–style JSON string for list-shaped content, with **base64 stripped** on persist; `normalize_stored_content` on load. Compaction uses `_stringify_message_content` so summaries never embed huge blobs (`app/services/compaction.py`).
- **Slack uploads**: Bolt handlers take `client`; `files_upload_v2` after `/chat` for `upload_image` actions. **`file_share` subtype** is allowed so file uploads are processed.
- **Memory about images**: There is **no** separate ingest endpoint. Images are only passed as multimodal **`/chat`** attachments; the bot’s model (with persona + retrieved memories) decides whether to call **`save_memory`** like any other turn. The bot still has no Slack channel history—only what you send in each `/chat` request.
- **Scopes**: Slack app needs **`files:read`** (download attachments) and **`files:write`** (generated images).

## Open questions / ops

1. **Image model**: Override per call via tool arg `model` or set `IMAGE_GENERATION_MODEL` in the server environment. Your LiteLLM proxy must expose a working `images/generations`-compatible route for that model.
2. **DALL·E / size**: `image.py` does not pass `size`; extend if your backend requires it.