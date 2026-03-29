---
name: attachments-and-images
description: "Load when the task involves images, attachments, or file handling: generating images, editing images, combining/mixing images, finding uploaded files, referencing earlier uploads, or any use of generate_image, list_attachments, or get_attachment tools. Also trigger when a delegated bot needs to work with images from the parent channel. Do NOT trigger for plain text conversations with no file/image component."
---

# Attachment & Image Mastery

## Core Principle

Image bytes never pass through the LLM context. Attachments are referenced by UUID; image tools fetch bytes directly from the database. Passing base64 through tool results will overflow the context window.

## Tools

### list_attachments

Find attachments in the current channel. Call this first whenever the user references an image or file.

| Parameter | Type | Default | Notes |
|---|---|---|---|
| limit | int | 5 | Max 20 |
| type_filter | string | (all) | `image`, `file`, `text`, `audio`, `video` |

Returns: `id`, `filename`, `type`, `mime_type`, `size_bytes`, `description`, `posted_by`, `posted_at`

No `channel_id` parameter needed — defaults to the current channel context automatically.

### get_attachment(attachment_id)

Fetch metadata for a single attachment by UUID. Returns description, filename, type, mime_type, has_file_data (boolean), posted_by, posted_at.

Does **NOT** return file bytes or base64. Use this to inspect metadata only.

### generate_image

Generate from scratch or edit existing images. The image model is configured server-side.

| Parameter | Type | Required | Notes |
|---|---|---|---|
| prompt | string | Yes | Describe what to generate, or the edits to apply |
| attachment_ids | string[] | No | UUIDs from list_attachments — fetches bytes directly from DB |
| n | int | No | Number of images (1-10). Only works with OpenAI models (gpt-image, dall-e). Ignored by Gemini. |

## Correct Patterns

### Generate from scratch

```
generate_image(prompt="A watercolor painting of a sunset over mountains")
```

One tool call. No attachments needed.

### Edit a single image

```
1. list_attachments(type_filter="image", limit=5)
2. generate_image(prompt="Make the sky purple", attachment_ids=["<uuid>"])
```

Two tool calls. Do NOT call get_attachment — generate_image fetches bytes itself.

### Mix/combine multiple images

```
1. list_attachments(type_filter="image", limit=10)
2. generate_image(
     prompt="Create a hybrid creature combining elements of both images",
     attachment_ids=["<uuid_1>", "<uuid_2>"]
   )
```

Pass multiple UUIDs. The image API receives all source images for multi-reference editing.

### "Edit that image I posted"

```
1. list_attachments(type_filter="image", limit=3)
   → Pick the most recent or the one matching the user's description
2. generate_image(prompt="<user's edit request>", attachment_ids=["<uuid>"])
```

### Generate multiple variations

```
generate_image(prompt="A logo for a coffee shop", n=4)
```

Only works with OpenAI image models. Each variation is saved as a separate attachment and sent as a separate image.

### Iterative editing (chaining)

Generated images are saved as attachments, so you can edit your own output:

```
1. generate_image(prompt="A red sports car on a mountain road")
   → Image is saved as an attachment automatically
2. list_attachments(type_filter="image", limit=1)
   → Find the image you just generated
3. generate_image(prompt="Add rain and dramatic clouds", attachment_ids=["<uuid>"])
```

### "What's in this image?"

```
1. list_attachments(type_filter="image", limit=3)
2. get_attachment("<uuid>")
   → Read the description field
```

If the description is populated (from auto-summarization), answer from it. If description is null and you need to analyze the image, say so — you cannot retrieve raw bytes through tool results without overflowing context.

## Common Mistakes

| Wrong | Right | Why |
|---|---|---|
| `get_attachment(id)` then pass base64 to `generate_image` | `generate_image(attachment_ids=[id])` | get_attachment doesn't return base64; generate_image fetches bytes directly |
| Passing `n=3` with a Gemini model | Omit `n` or set `n=1` | Gemini rejects the `n` parameter; only OpenAI models support it |
| Skipping `list_attachments` and guessing UUIDs | Always call `list_attachments` first | Attachment UUIDs are random; you must look them up |
| Calling `list_attachments(channel_id="C06RY3YBSLE")` | Call `list_attachments()` with no channel_id | Slack channel IDs are not valid UUIDs; omit the param to use current channel context |

## Delegation Context

When bot A delegates to bot B (via `delegate_to_agent`), bot B inherits the parent's channel context. This means:

- Bot B can call `list_attachments()` and see the same attachments as bot A
- Bot B can pass those attachment IDs to `generate_image`
- The user can upload an image, ask bot A to delegate to an image-specialist bot B, and bot B will find the upload

No special parameters needed — channel context propagates automatically.

## Image Output & Persistence

Every image produced by `generate_image` is **automatically saved as an attachment** in the current channel. This means:

- Generated images appear in `list_attachments` immediately — they're first-class attachments just like user uploads
- You can chain edits: generate an image, then call `list_attachments` to get its UUID, then pass it back to `generate_image` with new edits
- Other bots in the same channel (via delegation) can find and reference generated images
- The `posted_by` field will be the bot ID that generated it, and `source_integration` will be `generate_image`

The image is also returned as a `client_action` with type `upload_image` so the client (Slack, web, etc.) can display it. When `n > 1` (OpenAI only), each variation is saved and sent separately.

## Pre-Generation Checklist

- [ ] If editing: called `list_attachments` to get the UUID(s)
- [ ] Prompt is descriptive (not just "edit it" — describe the desired changes)
- [ ] Using `attachment_ids`, not `source_image_b64` (deprecated)
- [ ] Not passing `n > 1` unless certain the model is OpenAI-based
- [ ] Not calling `get_attachment` just to feed bytes into `generate_image`
