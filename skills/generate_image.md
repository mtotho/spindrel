---
name: Image Generation
description: Generate or edit images directly with the generate_image tool — works on any bot, no dedicated image bot needed.
triggers: generate image, create image, edit image, draw, picture of, combine images, change the sky, swap the background, dall-e, gpt-image, gemini image, nano banana
category: media
---

# generate_image

`generate_image` is a regular tool any bot can call. There is no dedicated image
bot — if the user asks for an image, just call the tool. Generated images are
persisted as channel attachments and delivered to every connected client (web,
Slack, Discord) automatically; do not also call `send_file`.

## Parameters

| Param | Type | Required | Notes |
|---|---|---|---|
| `prompt` | string | Yes | Detailed description of the image to generate, or the change to make when editing. |
| `attachment_ids` | string[] | No | UUIDs of existing images to use as source/reference (from `list_attachments`). Triggers an edit. |
| `model` | string | No | Override the server default. Pass an `id` flagged `supports_image_generation` (e.g. `gpt-image-1`, `dall-e-3`, `gemini/gemini-2.5-flash-image`). |
| `provider_id` | string | No | Required only when two providers serve the same model id. |
| `n` | int | No | Variations to return (1–10). Honored where the underlying model supports batch. |
| `size` | string | No | `1024x1024` / `1792x1024` / `1024x1792`. OpenAI shape; mapped from `aspect_ratio` if you only set the latter. |
| `aspect_ratio` | string | No | `1:1`, `16:9`, `9:16`, `3:2`, `2:3`. Native to Gemini; mapped to `size` for OpenAI. |
| `seed` | int | No | Random seed where the provider supports it. |

## When to use which call shape

* **Generate from scratch** — pass `prompt` only.
* **Edit / restyle / combine** — pass `prompt` plus one or more `attachment_ids`.
  First call `list_attachments(type_filter="image")` to find the UUIDs.
* **Multiple variations** — pass `n=3..10`. OpenAI `gpt-image-*` returns the
  full batch; `dall-e-3` is clamped to 1; Gemini returns 1.

## Server defaults

The default image model + provider live in **Admin → Settings → Image Generation**.
The dropdown only lists models flagged `supports_image_generation` — if a model
isn't there, flip the checkbox in **Admin → Providers → (provider) → Models**.
You can always override per-call via `model` and `provider_id`.

## Examples

```
generate_image(prompt="A golden retriever puppy in a field of sunflowers at golden hour, shallow depth of field, cinematic lighting")
```

```
list_attachments(type_filter="image", limit=5)
generate_image(prompt="Replace the sky with a dramatic purple sunset", attachment_ids=["<uuid>"])
```

```
generate_image(prompt="Photoreal composite — both dogs sitting together on a park bench", attachment_ids=["<uuid1>","<uuid2>"])
```

```
generate_image(prompt="Watercolor sunset over mountains", aspect_ratio="16:9", n=3)
```

## Common mistakes

| Wrong | Right | Why |
|---|---|---|
| Calling `get_attachment` to get base64 first | Pass the UUID directly via `attachment_ids` | The tool reads bytes from the DB itself. |
| Delegating to a separate "image bot" | Call `generate_image` directly | Any bot can produce images via this tool. |
| Guessing attachment UUIDs | `list_attachments` first | UUIDs are random; do not invent. |
