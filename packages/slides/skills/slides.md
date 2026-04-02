---
name: Slide Decks (Marp)
description: Create presentations using Marp Markdown syntax — HTML, PDF, or PPTX output
---
# SKILL: Slide Decks (Marp)

> Powered by [Marp](https://marp.app) — an open-source Markdown presentation ecosystem by [@marp-team](https://github.com/marp-team). MIT licensed.

## Overview
Create slide presentations from Markdown using the `create_slides` tool. Slides use [Marp](https://github.com/marp-team/marp-cli) syntax — standard Markdown with `---` separators between slides and optional directives for theming and layout.

## Tool
- `create_slides` — takes Marp Markdown content, converts to HTML/PDF/PPTX, and **sends the file directly to the chat** in one step. No separate send/post call needed — the file is delivered to Slack/web UI automatically. Parameters: `markdown`, `format` (html/pdf/pptx), `filename`

If Marp CLI is not installed, the tool will try to install it automatically via `npx`. If that fails, it returns an error with install instructions (`npm install -g @marp-team/marp-cli`).

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
marp: true              # Required — enables Marp rendering
theme: default          # Theme: default, gaia, uncover
paginate: true          # Show slide numbers
header: 'Company Name'  # Header on every slide
footer: '2026'          # Footer on every slide
size: 16:9              # Aspect ratio (default 16:9, also 4:3)
color: '#333'           # Default text color
backgroundColor: '#fff' # Default background
---
```

### Per-slide directives (HTML comments)
```markdown
<!-- _class: lead -->       # Apply class to this slide only
<!-- _backgroundColor: #1a1a2e -->
<!-- _color: white -->
<!-- _paginate: false -->   # Hide page number on this slide
<!-- _header: '' -->        # Clear header on this slide
```

### Theme classes
**default theme:**
- `lead` — centered, larger title text (good for title/section slides)
- `invert` — dark background, light text

**gaia theme:**
- `lead` — centered title
- `invert` — inverted colors
- `gaia` — accent-colored background

**uncover theme:**
- `lead` — centered
- `invert` — dark mode

### Images
```markdown
# Slide with image
![width:500px](https://example.com/image.png)

# Background image (fills entire slide)
![bg](https://example.com/photo.jpg)

# Background with overlay text
![bg brightness:0.5](https://example.com/photo.jpg)
# Title over dark background

# Split: image on right, text on left
![bg right:40%](https://example.com/chart.png)
## Key findings
- Point A
- Point B

# Multiple backgrounds (side by side)
![bg](image1.png)
![bg](image2.png)
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

### Math (KaTeX)
```markdown
Inline: $E = mc^2$

Block:
$$
\int_0^\infty e^{-x^2} dx = \frac{\sqrt{\pi}}{2}
$$
```

## Key Workflows

### Quick presentation
1. Ask the user what the presentation is about
2. Draft the Marp Markdown with a title slide + content slides
3. `create_slides(markdown="...", format="html")` — generates self-contained HTML

### Polished deck for sharing
1. Write slides with the `gaia` or `uncover` theme
2. Use `<!-- _class: lead -->` for title/section slides
3. `create_slides(markdown="...", format="pptx", filename="quarterly_review")` — PowerPoint output

### Presentation with user-provided images
1. `list_attachments(type_filter="image")` — find images shared in the conversation
2. `save_attachment(attachment_id="...", path="/tmp/slides/photo.jpg")` — save each image to disk
3. Reference them in the markdown: `![bg right:40%](/tmp/slides/photo.jpg)`
4. `create_slides(markdown="...")` — Marp renders with `--allow-local-files` so local paths work

### Iterative refinement
1. Generate the first version as HTML (fastest)
2. Share with user, get feedback
3. Edit the markdown and regenerate
4. When finalized: `create_slides(format="pdf")` or `create_slides(format="pptx")`

## Tips
- **Always include `marp: true`** in frontmatter (the tool auto-adds it if missing)
- **Title slides**: use `<!-- _class: lead -->` to center the content
- **Section dividers**: a slide with just `# Section Title` and `<!-- _class: lead -->` works well
- **Keep slides concise**: 3-5 bullet points max per slide, let the visual layout do the work
- **`paginate: true`** in frontmatter adds slide numbers automatically
- **HTML output** is a single self-contained file — no external dependencies, opens in any browser
- **PPTX output** creates a real PowerPoint file that can be edited in PowerPoint/Google Slides
