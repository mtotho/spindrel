---
name: Attachments & Files
description: Sending files, finding uploads, image generation/editing, and delegation with attachments
triggers: image, attachment, upload, file, send_file, generate_image, list_attachments, get_attachment, photo, picture
category: core
---

# Attachments & Files

## Architecture

- Attachments are stored in the database with UUIDs and are persistent across all clients (Slack, web UI, etc.)
- File bytes never pass through the LLM context — tools fetch bytes directly from the DB
- Every file sent to the channel (via `send_file` or `generate_image`) creates a DB attachment linked to the assistant message
- On the web UI, attachments appear as download links below the message
- On Slack, attachments are uploaded as native Slack files

## Tools

### send_file — deliver a file to the channel

The single tool for posting any file to the chat. Two modes:

| Parameter | Type | Required | Notes |
|---|---|---|---|
| path | string | One of path or attachment_id | File on disk. Workspace paths (`/workspace/...`) translated automatically |
| attachment_id | string | One of path or attachment_id | UUID of an existing attachment (from `list_attachments`) |
| caption | string | No | Caption to display with the file |
| filename | string | No | Override display filename |

**From disk:**
```
send_file(path="/workspace/output/report.pdf", caption="Monthly report")
```

**Re-post an existing attachment:**
```
send_file(attachment_id="<uuid>", caption="Here's that file again")
```

Both modes create a persistent DB attachment and deliver to the channel.

### list_attachments — find files in the channel

| Parameter | Type | Default | Notes |
|---|---|---|---|
| limit | int | 5 | Max 50 |
| page | int | 1 | For pagination |
| type_filter | string | (all) | `image`, `file`, `text`, `audio`, `video` |

Returns: `id`, `filename`, `type`, `mime_type`, `size_bytes`, `description`, `posted_by`, `posted_at`

No `channel_id` parameter needed — defaults to current channel automatically.

### get_attachment(attachment_id) — inspect metadata

Returns description, filename, type, mime_type, has_file_data, posted_by, posted_at.

Does **NOT** return file bytes. Use for metadata only.

### describe_attachment(attachment_id, prompt?) — vision analysis

Without `prompt`: returns the existing auto-generated description.
With `prompt`: makes a fresh vision model call (e.g. "What's in this image?").

Works with image attachments only.

### delete_attachment(attachment_id) — permanently delete

Permanently removes an attachment from the database **and** from any connected
integration (e.g. deletes the Slack file). Irreversible. Use `list_attachments`
to find the UUID first.

```
delete_attachment(attachment_id="<uuid>")
```

### delete_recent_attachments — bulk delete by age

Delete all attachments in the current channel created within the last N seconds. No UUID lookup needed — useful for bots that process then clean up.

| Parameter | Type | Default | Notes |
|---|---|---|---|
| max_age_seconds | int | 120 | Max 600 (10 min) |
| type_filter | string | (all) | `image`, `file`, `text`, `audio`, `video` |

```
delete_recent_attachments(type_filter="image", max_age_seconds=120)
```

Returns a list of deleted filenames and whether each was also removed from the integration.

### save_attachment(attachment_id, path) — download to disk

Save an attachment's file data to the filesystem. Use when you need to process a file locally (e.g. include a user-uploaded image in a slide deck).

### generate_image — create or edit images

See the **generate-image** skill for full details on provider differences, Gemini limitations, and prompt best practices.

Generated images are automatically saved as attachments and delivered to the channel.

## Auto-visible attachments

Any tool that creates an attachment (`frigate_snapshot`, `generate_image`, `exec_sandbox` file output, etc.) automatically links it to the assistant message that triggered the tool. The image/file appears on the web UI and Slack without any extra step — you do **not** need to call `send_file` afterward.

Use `send_file` only when you need to:
- Send a file from disk (`path=...`)
- Re-post an older attachment to highlight it with a specific caption (`attachment_id=...`)

## Common Patterns

### Send a file from disk
```
send_file(path="/workspace/data/results.csv")
```

### Re-post a file someone uploaded earlier
```
1. list_attachments(type_filter="file", limit=5)
2. send_file(attachment_id="<uuid>")
```

### Generate an image from scratch
```
generate_image(prompt="A watercolor sunset over mountains")
```

### Edit an existing image
```
1. list_attachments(type_filter="image", limit=5)
2. generate_image(prompt="Make the sky purple", attachment_ids=["<uuid>"])
```
Note: Direct editing works with OpenAI models. Gemini models auto-fall back to generating a new image using descriptions of the reference images — see the **generate-image** skill for details.

### Combine multiple images
```
1. list_attachments(type_filter="image", limit=10)
2. generate_image(prompt="Merge both images into a panorama", attachment_ids=["<uuid1>", "<uuid2>"])
```

### Iterative editing (chain edits)
Generated images become attachments immediately:
```
1. generate_image(prompt="A red sports car")
2. list_attachments(type_filter="image", limit=1)  → get the UUID
3. generate_image(prompt="Add rain and dramatic clouds", attachment_ids=["<uuid>"])
```

### Save an uploaded file to disk for processing
```
1. list_attachments(type_filter="file", limit=5)
2. save_attachment(attachment_id="<uuid>", path="/workspace/data/")
```

### Delete an attachment (also removes from Slack)
```
1. list_attachments(type_filter="image", limit=5)
2. delete_attachment(attachment_id="<uuid>")
```

### Analyze then clean up (e.g. assess a photo then delete it)
```
1. describe_attachment(attachment_id="<uuid>", prompt="Assess this image")
2. delete_recent_attachments(type_filter="image", max_age_seconds=120)
```
No UUID lookup needed for the delete — it cleans up all recent images in the channel.

### Describe an image
```
1. list_attachments(type_filter="image", limit=3)
2. describe_attachment(attachment_id="<uuid>", prompt="Are there any people in this image?")
```

## Common Mistakes

| Wrong | Right | Why |
|---|---|---|
| `get_attachment` then pass base64 to `generate_image` | `generate_image(attachment_ids=[id])` | generate_image fetches bytes directly |
| Passing `n=3` with a Gemini model | Omit `n` or set `n=1` | Only OpenAI models support n>1 |
| Guessing attachment UUIDs | Call `list_attachments` first | UUIDs are random; you must look them up |
| Using `list_attachments(channel_id="C06RY3YBSLE")` | Omit channel_id | Slack IDs aren't UUIDs; current channel is used automatically |
| Using `send_file` to re-show an attachment from the same turn | Just reference it in your response text | Attachments are auto-visible on the message that created them |
| Calling `send_file` after `frigate_snapshot` or `frigate_event_snapshot` | Just use the attachment_id for analysis if needed | Frigate media tools auto-display in the channel |

## Delegation Context

When bot A delegates to bot B, bot B inherits the parent's channel context:
- `list_attachments()` sees the same attachments as bot A
- `generate_image(attachment_ids=[...])` can reference parent channel images
- `send_file(attachment_id="<uuid>")` can re-post files from the parent channel

No special parameters needed — channel context propagates automatically.
