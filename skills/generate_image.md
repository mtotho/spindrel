---
name: Image Generation
description: Generate, edit, and combine images with provider-specific guidance (OpenAI vs Gemini)
triggers: generate image, create image, edit image, combine images, dall-e, gpt-image, image generation
category: core
---

# generate_image Tool Guide

## Parameters

| Parameter | Type | Required | Notes |
|---|---|---|---|
| prompt | string | Yes | Detailed description of what to generate or how to edit |
| attachment_ids | string[] | No | Source image UUIDs for editing (get from `list_attachments`) |
| model | string | No | Override image model (e.g. `gpt-image-1`, `dall-e-3`, `gemini/gemini-2.5-flash-image`) |
| provider_id | string | No | Route to specific provider when model names overlap |
| n | int | No | Number of variations (1-10, **OpenAI models only**) |

Generated images are automatically saved as attachments and delivered to the channel — no need to call `send_file` afterward.

## Provider Differences

### OpenAI models (`gpt-image-1`, `dall-e-3`)
- **Full edit support**: pass `attachment_ids` to edit/combine existing images
- `gpt-image-1`: supports `n` up to 10 for batch generation
- `dall-e-3`: `n` is always 1

### Gemini models (`gemini/gemini-2.5-flash-image`)
- **No direct image editing**: Gemini does not support the `images.edit()` endpoint
- When you pass `attachment_ids` with a Gemini model, the tool **automatically falls back** to generation using descriptions of the reference images
- The result is a newly generated image inspired by the descriptions — it will not be a pixel-accurate edit
- `n` parameter is ignored (always generates 1 image)
- **For best results with Gemini**: write a detailed prompt that describes exactly what you want, including details from the reference images

### What to tell the user

When Gemini is the image model and the user asks to edit/combine images:
- **Do** explain that the model can generate a new image inspired by their reference images, but cannot directly edit them
- **Do** offer to generate with a detailed prompt incorporating what you see in the images
- **Don't** just say "I can't do that" — the tool handles the fallback automatically, so call it and let it work

## Prompt Best Practices

### Be specific and detailed
```
❌ "A dog"
✅ "A golden retriever puppy sitting in a field of sunflowers at golden hour, warm lighting, shallow depth of field"
```

### For edits/combinations (OpenAI)
```
generate_image(
  prompt="Make the sky a dramatic purple sunset with orange clouds",
  attachment_ids=["<uuid>"]
)
```

### For Gemini "edits" (automatic fallback)
When Gemini falls back to generation, the tool automatically prepends reference image descriptions to your prompt. Write your prompt as if describing the desired final result:
```
generate_image(
  prompt="Both dogs from the photos sitting together on a park bench, photorealistic style",
  attachment_ids=["<uuid1>", "<uuid2>"]
)
```

## Common Workflows

### Generate from scratch
```
generate_image(prompt="A watercolor sunset over mountains")
```

### Edit an existing image (OpenAI)
```
1. list_attachments(type_filter="image", limit=5)
2. generate_image(prompt="Remove the background and replace with a beach scene", attachment_ids=["<uuid>"])
```

### Combine images
```
1. list_attachments(type_filter="image", limit=10)
2. generate_image(prompt="Create a composite of both images side by side", attachment_ids=["<uuid1>", "<uuid2>"])
```

### Iterative editing
```
1. generate_image(prompt="A red sports car")
2. list_attachments(type_filter="image", limit=1)  → get UUID
3. generate_image(prompt="Add rain and dramatic storm clouds", attachment_ids=["<uuid>"])
```

## Common Mistakes

| Wrong | Right | Why |
|---|---|---|
| Calling `get_attachment` to get base64, then passing to prompt | `generate_image(attachment_ids=[id])` | Tool fetches bytes directly from DB |
| Passing `n=3` with Gemini | Omit `n` or set `n=1` | Only OpenAI models support n>1 |
| Saying "I can't edit with Gemini" | Call `generate_image` normally | The tool auto-falls back to generation with descriptions |
| Guessing attachment UUIDs | Call `list_attachments` first | UUIDs are random; you must look them up |
