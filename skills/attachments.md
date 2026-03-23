# Attachment & Image Capabilities

## Overview
You can access, retrieve, and edit images and files that users have shared in the channel.
Attachments are stored persistently in the database — you can reference images from earlier
in the conversation, even across sessions.

## Tools Available

### list_attachments
Lists recent attachments in the channel. Use this when the user refers to "that image" or
"the file I uploaded earlier" and you need to find it.

Parameters:
- limit (default 5): how many to return
- type_filter: "image", "file", "text", "audio", "video"

Returns: id, filename, type, description, posted_by, posted_at

### get_attachment(attachment_id)
Fetches the full file by DB UUID. Returns file_data_base64 — actual file bytes encoded as base64.

Use this when you need to:
- Display or analyze an image
- Pass an image to generate_image for editing
- Read the full content of a text/file attachment

### generate_image(prompt, source_image_b64?)
Generates a new image from a prompt, or edits an existing image.

To edit an existing image:
1. Call list_attachments() to find the image ID
2. Call get_attachment(id) to get file_data_base64
3. Call generate_image(prompt="your edit instructions", source_image_b64=<file_data_base64>)

## Common Patterns

### "Edit that image I posted"
1. list_attachments(type_filter="image", limit=5) → find the right one
2. get_attachment(id) → get file_data_base64
3. generate_image(prompt="...", source_image_b64=file_data_base64)

### "What was in the image I shared earlier?"
1. list_attachments(type_filter="image") → check descriptions
2. If description is already there, answer from it
3. If not, get_attachment(id) → pass file_data_base64 to vision

### "Analyze the CSV I uploaded"
1. list_attachments(type_filter="text") or list_attachments(type_filter="file")
2. get_attachment(id) → decode file_data_base64 → read as text
