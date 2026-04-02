---
name: image-editing
description: >
  Advanced image editing patterns: iterative edit chains, version tracking,
  multi-image composition, style transfer, batch generation, and delegation
  workflows. Load when doing complex multi-step image work beyond simple
  generate-and-done.
---

# Image Editing Patterns

## Iterative Edit Chain

The most common workflow — generate, assess, refine, repeat.

```
# 1. Generate the initial image
generate_image(prompt="A cozy cabin in snowy mountains, warm light from windows, oil painting style")

# 2. Get its UUID
list_attachments(type_filter="image", limit=1)
# → uuid: "abc-123"

# 3. First edit pass
generate_image(prompt="Add a frozen lake in the foreground reflecting the cabin lights", attachment_ids=["abc-123"])

# 4. Get the new version's UUID
list_attachments(type_filter="image", limit=1)
# → uuid: "def-456"

# 5. Second edit pass
generate_image(prompt="Add northern lights in the sky, green and purple", attachment_ids=["def-456"])
```

**Key principle:** Each `generate_image` call creates a NEW attachment. Always call `list_attachments` again to get the latest UUID before the next edit. Don't reuse old UUIDs unless you want to branch from an earlier version.

## Version Branching

Create variations from the same base image:

```
# Generate base
generate_image(prompt="A portrait of a woman with flowing hair")
list_attachments(type_filter="image", limit=1)
# → base_uuid: "abc-123"

# Branch A: watercolor style
generate_image(prompt="Convert to watercolor painting style", attachment_ids=["abc-123"])

# Branch B: from the SAME base (use the original UUID, not branch A)
generate_image(prompt="Convert to charcoal sketch style", attachment_ids=["abc-123"])

# Branch C: also from base
generate_image(prompt="Convert to pop art style with bold colors", attachment_ids=["abc-123"])
```

**Tip:** Tell the user which version you're branching from. "I'll create three style variations from the original portrait."

## Multi-Image Composition

Combine multiple images into one:

```
# Get UUIDs of images to combine
list_attachments(type_filter="image", limit=5)
# → ["landscape-uuid", "character-uuid"]

# Composite
generate_image(
    prompt="Place the character from the second image into the landscape from the first image, matching lighting and perspective",
    attachment_ids=["landscape-uuid", "character-uuid"]
)
```

Works best when you describe the spatial relationship: "place X in the foreground of Y", "overlay X onto the left side of Y".

## Re-examining Earlier Images

When you need to see an image from earlier in the conversation (not the most recent):

```
# Find it
list_attachments(type_filter="image", limit=10)
# → shows all recent images with UUIDs and timestamps

# Load it into your context
view_attachment(attachment_id="older-image-uuid")
# → You now see the image and can analyze it

# Then edit from it
generate_image(prompt="...", attachment_ids=["older-image-uuid"])
```

Use `view_attachment` when:
- Comparing two versions ("which looks better?")
- Going back to an earlier version to branch from it
- Answering questions about a specific image the user references

## Style Transfer

Apply the style of one image to the content of another:

```
list_attachments(type_filter="image", limit=5)
# → ["content-uuid", "style-uuid"]

generate_image(
    prompt="Recreate the scene from the first image in the artistic style of the second image. Preserve the composition and subjects from image 1 but apply the color palette, brushwork, and aesthetic of image 2.",
    attachment_ids=["content-uuid", "style-uuid"]
)
```

## Batch Generation

When creating a series of related images (e.g., icon set, storyboard frames):

```
# Frame 1
generate_image(prompt="Storyboard frame 1: A detective enters a dimly lit office. Film noir style, high contrast black and white.")

# Frame 2 (independent, no attachment_ids needed)
generate_image(prompt="Storyboard frame 2: Close-up of a mysterious letter on the desk. Film noir style, high contrast black and white.")

# Frame 3
generate_image(prompt="Storyboard frame 3: The detective picks up the letter, shadow falling across their face. Film noir style, high contrast black and white.")
```

**Consistency tip:** Repeat the style cues in every prompt. The model doesn't remember prior generations — each call is independent.

## Saving for External Use

When the user wants to use images outside the chat:

```
# Find the final version
list_attachments(type_filter="image", limit=1)
# → uuid: "final-uuid"

# Save to disk (workspace paths work)
save_attachment(attachment_id="final-uuid", path="/workspace/output/final-image.png")

# Or send with a specific filename
send_file(attachment_id="final-uuid", filename="project-hero-image.png", caption="Final approved version")
```

## Working with User Photos

When a user uploads a photo and wants edits:

1. **Acknowledge what you see** — "I can see your photo of [description]. What changes would you like?"
2. **Get the UUID** — `list_attachments(type_filter="image", limit=1)`
3. **Edit with clear instructions** — Be precise about what to change and what to preserve
4. **Show the result** — It appears automatically, then describe what changed

For photos, precision matters more than creativity:
- "Remove the background and replace with solid white" (specific)
- "Make the lighting warmer, increase the golden tones" (specific)
- "Make it look better" (too vague — ask for clarification)

## Provider Notes

- **OpenAI models** (gpt-image, dall-e): Support `n` parameter for multiple variations in one call
- **Gemini models**: `n` parameter is ignored; generate one at a time
- **Edit quality**: Results vary by provider. If an edit doesn't work well, try rephrasing the prompt rather than retrying the same one
- **Model override**: Pass `model="gpt-image-1"` or `model="dall-e-3"` to use a specific image model instead of the server default
- **Provider routing**: Pass `provider_id="openai-prod"` when two providers have models with the same name — this disambiguates which endpoint to use
- Default resolution: tool `provider_id` param > `IMAGE_GENERATION_PROVIDER_ID` config > bot's provider > env fallback

## Common Mistakes

| Wrong | Right | Why |
|---|---|---|
| Reusing an old UUID after edits | Call `list_attachments` to get the latest | Each generation creates a NEW attachment |
| `get_attachment` before `generate_image` | Just pass `attachment_ids` directly | `generate_image` fetches bytes internally |
| Vague edit prompts ("make it better") | Specific changes ("increase contrast, saturate the reds") | Models need concrete instructions |
| Generating without confirming intent | Describe what you'll create, then generate | Saves wasted generations |
| Using `send_file` after `generate_image` | Skip it — generated images auto-display | Avoids duplicate images in chat |
| Assuming the model remembers prior images | Repeat style cues in every prompt | Each call is independent |
