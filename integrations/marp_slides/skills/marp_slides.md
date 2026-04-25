---
name: Marp Slides
description: Create presentations using Marp Markdown syntax as HTML, PDF, or PPTX output
---
# SKILL: Marp Slides

> Powered by [Marp](https://marp.app), an open-source Markdown presentation ecosystem by [@marp-team](https://github.com/marp-team). MIT licensed.

## Overview

Create slide presentations from Markdown using the `create_marp_slides` tool. Slides use [Marp](https://github.com/marp-team/marp-cli) syntax: standard Markdown with `---` separators between slides and optional directives for theming and layout.

## Tool

- `create_marp_slides` takes Marp Markdown content, converts it to HTML/PDF/PPTX, and sends the file directly to the chat in one step. No separate send/post call is needed. Parameters: `markdown`, `format` (`html`, `pdf`, `pptx`), `filename`.

If Marp CLI is not installed, the tool tries to run it through `npx --yes @marp-team/marp-cli`. If that fails, it returns an error with install instructions.

## Marp Markdown Syntax

### Basic structure

```markdown
---
marp: true
theme: default
paginate: true
---

# Title Slide

Subtitle or description

---

# Second Slide

- Bullet point one
- Bullet point two
- Bullet point three

---

# Third Slide

Content here
```

### Frontmatter directives

```yaml
---
marp: true
theme: default
paginate: true
header: 'Company Name'
footer: '2026'
size: 16:9
color: '#333'
backgroundColor: '#fff'
---
```

### Per-slide directives

```markdown
<!-- _class: lead -->
<!-- _backgroundColor: #1a1a2e -->
<!-- _color: white -->
<!-- _paginate: false -->
<!-- _header: '' -->
```

### Theme classes

- `lead` centers and enlarges title text for title or section slides.
- `invert` switches to a dark background with light text.
- `gaia` provides an accent-colored background when using the Gaia theme.

### Images

```markdown
# Slide with image
![width:500px](https://example.com/image.png)

# Background image
![bg](https://example.com/photo.jpg)

# Background with overlay text
![bg brightness:0.5](https://example.com/photo.jpg)
# Title over dark background

# Split image and text
![bg right:40%](https://example.com/chart.png)
## Key findings
- Point A
- Point B
```

### Multi-column layout

```markdown
<div style="display: flex; gap: 40px;">
<div style="flex: 1;">

## Left Column
- Item A
- Item B

</div>
<div style="flex: 1;">

## Right Column
- Item C
- Item D

</div>
</div>
```

### Code blocks

````markdown
```python
def hello():
    print("Hello, world!")
```
````

### Tables

```markdown
| Feature | Status |
|---------|--------|
| Auth    | Done   |
| API     | WIP    |
| Tests   | TODO   |
```

### Math

```markdown
Inline: $E = mc^2$

Block:
$$
\int_0^\infty e^{-x^2} dx = \frac{\sqrt{\pi}}{2}
$$
```

## Key Workflows

### Quick presentation

1. Ask the user what the presentation is about.
2. Draft the Marp Markdown with a title slide and content slides.
3. Call `create_marp_slides(markdown="...", format="html")`.

### Polished deck for sharing

1. Write slides with the `gaia` or `uncover` theme.
2. Use `<!-- _class: lead -->` for title and section slides.
3. Call `create_marp_slides(markdown="...", format="pptx", filename="quarterly_review")`.

### Presentation with user-provided images

1. `list_attachments(type_filter="image")` to find images shared in the conversation.
2. `save_attachment(attachment_id="...", path="/tmp/marp-slides/photo.jpg")` to save each image to disk.
3. Reference them in the markdown: `![bg right:40%](/tmp/marp-slides/photo.jpg)`.
4. Call `create_marp_slides(markdown="...")`; Marp renders with `--allow-local-files`.

### Iterative refinement

1. Generate the first version as HTML.
2. Share it with the user and collect feedback.
3. Edit the markdown and regenerate.
4. When finalized, use `format="pdf"` or `format="pptx"`.

## Tips

- Always include `marp: true` in frontmatter; the tool auto-adds it if missing.
- Use `<!-- _class: lead -->` for title slides and section dividers.
- Keep slides concise: 3-5 bullet points per slide.
- `paginate: true` adds slide numbers automatically.
- HTML output is a single self-contained file.
- PPTX output creates an editable PowerPoint file.
