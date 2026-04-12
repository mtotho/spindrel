---
name: Excalidraw Diagrams
description: Create hand-drawn-style diagrams from Excalidraw JSON or Mermaid syntax — SVG/PNG output
---
# SKILL: Excalidraw Diagrams

> Powered by [Excalidraw](https://excalidraw.com) — open-source virtual whiteboard. MIT licensed.

## Overview
Create hand-drawn-style diagrams that render directly in chat. Two tools:

- **`mermaid_to_excalidraw`** — write Mermaid syntax, get an Excalidraw-styled image. Best for flowcharts, sequence diagrams, ER diagrams. **Use this when possible** — it's faster and less error-prone.
- **`create_excalidraw`** — provide raw Excalidraw element JSON for full control over positioning, styling, and layout. Use when Mermaid can't express what you need (custom layouts, mixed shapes, precise positioning).

Both tools deliver the image directly to chat as an inline attachment. No separate send step needed.

## Tool: mermaid_to_excalidraw

The high-value path. Write standard Mermaid syntax and the tool converts it to Excalidraw's hand-drawn style before rendering.

**Parameters:**
- `mermaid` (required) — Mermaid diagram definition
- `filename` (optional, default "diagram") — output filename
- `format` (optional, "svg"|"png", default "svg")

### Supported diagram types
```
flowchart TD
    A[Start] --> B{Decision}
    B -->|Yes| C[Process]
    B -->|No| D[End]
```

```
sequenceDiagram
    Client->>Server: Request
    Server->>DB: Query
    DB-->>Server: Result
    Server-->>Client: Response
```

```
erDiagram
    USER ||--o{ ORDER : places
    ORDER ||--|{ LINE_ITEM : contains
    PRODUCT ||--o{ LINE_ITEM : "is in"
```

### When to use Mermaid vs raw JSON
- **Mermaid**: flowcharts, sequence diagrams, ER diagrams, state diagrams, class diagrams. Layout is automatic.
- **Raw JSON**: mind maps, architecture diagrams with custom positioning, diagrams mixing many shape types, anything needing precise visual control.

## Tool: create_excalidraw

Full control over every element. You provide the elements array, the tool wraps it in a document and exports.

**Parameters:**
- `elements` (required) — array of Excalidraw element objects
- `app_state` (optional) — document settings like background color
- `filename` (optional, default "diagram")
- `format` (optional, "svg"|"png", default "svg")

### Element types

**rectangle**
```json
{
  "id": "box1", "type": "rectangle",
  "x": 100, "y": 100, "width": 200, "height": 80,
  "strokeColor": "#1e1e1e", "backgroundColor": "#a5d8ff",
  "fillStyle": "hachure", "roughness": 1, "strokeWidth": 2,
  "roundness": {"type": 3}
}
```

**ellipse**
```json
{
  "id": "circle1", "type": "ellipse",
  "x": 100, "y": 100, "width": 150, "height": 150,
  "strokeColor": "#1e1e1e", "backgroundColor": "#b2f2bb",
  "fillStyle": "solid", "roughness": 1
}
```

**diamond**
```json
{
  "id": "decision1", "type": "diamond",
  "x": 100, "y": 100, "width": 160, "height": 120,
  "strokeColor": "#1e1e1e", "backgroundColor": "#ffec99",
  "fillStyle": "hachure", "roughness": 1
}
```

**text**
```json
{
  "id": "label1", "type": "text",
  "x": 120, "y": 125, "width": 160, "height": 30,
  "text": "Auth Service",
  "fontSize": 20, "fontFamily": 1,
  "textAlign": "center", "verticalAlign": "middle",
  "strokeColor": "#1e1e1e"
}
```

**arrow** (connecting shapes)
```json
{
  "id": "arrow1", "type": "arrow",
  "x": 300, "y": 140, "width": 100, "height": 0,
  "points": [[0, 0], [100, 0]],
  "strokeColor": "#1e1e1e", "strokeWidth": 2, "roughness": 1,
  "startBinding": {"elementId": "box1", "focus": 0, "gap": 4},
  "endBinding": {"elementId": "box2", "focus": 0, "gap": 4}
}
```

**line** (no arrowhead)
```json
{
  "id": "line1", "type": "line",
  "x": 100, "y": 200, "width": 300, "height": 0,
  "points": [[0, 0], [300, 0]],
  "strokeColor": "#1e1e1e", "strokeStyle": "dashed"
}
```

### Key properties

| Property | Values | Notes |
|---|---|---|
| `fillStyle` | `"hachure"`, `"cross-hatch"`, `"solid"` | hachure = classic hand-drawn fill |
| `roughness` | `0` (smooth), `1` (artist), `2` (cartoonist) | 1 is the default Excalidraw look |
| `strokeStyle` | `"solid"`, `"dashed"`, `"dotted"` | |
| `strokeWidth` | `1`, `2`, `4` | 2 is a good default |
| `fontFamily` | `1` (Virgil/hand-drawn), `2` (Helvetica), `3` (Cascadia/mono) | Use 1 for sketchy look |
| `textAlign` | `"left"`, `"center"`, `"right"` | |
| `opacity` | `0`–`100` | |
| `roundness` | `{"type": 3}` or `null` | type 3 = rounded corners |

### Color palette (good defaults)
- Blue: `#a5d8ff` (bg), `#1971c2` (stroke)
- Green: `#b2f2bb` (bg), `#2f9e44` (stroke)
- Yellow: `#ffec99` (bg), `#e67700` (stroke)
- Red: `#ffc9c9` (bg), `#e03131` (stroke)
- Purple: `#d0bfff` (bg), `#7048e8` (stroke)
- Gray: `#dee2e6` (bg), `#495057` (stroke)
- Default stroke: `#1e1e1e`

### Bindings (connecting arrows to shapes)
Arrows connect to shapes via `startBinding` and `endBinding`:
```json
{
  "elementId": "target_shape_id",
  "focus": 0,
  "gap": 4
}
```
- `focus`: `-1` to `1` — where on the shape edge the arrow attaches. `0` = center.
- `gap`: pixels between arrow tip and shape border.

When using bindings, the target shape needs `boundElements` referencing the arrow:
```json
{
  "id": "box1", "type": "rectangle", ...,
  "boundElements": [{"id": "arrow1", "type": "arrow"}]
}
```

### Grouping
Add the same group ID to multiple elements' `groupIds` array to group them:
```json
{"id": "box1", ..., "groupIds": ["group_auth"]},
{"id": "label1", ..., "groupIds": ["group_auth"]}
```

## Common patterns

### Architecture diagram (3 services)
```json
[
  {"id": "web", "type": "rectangle", "x": 50, "y": 100, "width": 180, "height": 80,
   "backgroundColor": "#a5d8ff", "fillStyle": "hachure", "roughness": 1, "strokeWidth": 2,
   "boundElements": [{"id": "a1", "type": "arrow"}]},
  {"id": "web_label", "type": "text", "x": 85, "y": 125, "width": 110, "height": 30,
   "text": "Web App", "fontSize": 20, "fontFamily": 1, "textAlign": "center"},

  {"id": "api", "type": "rectangle", "x": 350, "y": 100, "width": 180, "height": 80,
   "backgroundColor": "#b2f2bb", "fillStyle": "hachure", "roughness": 1, "strokeWidth": 2,
   "boundElements": [{"id": "a1", "type": "arrow"}, {"id": "a2", "type": "arrow"}]},
  {"id": "api_label", "type": "text", "x": 390, "y": 125, "width": 100, "height": 30,
   "text": "API Server", "fontSize": 20, "fontFamily": 1, "textAlign": "center"},

  {"id": "db", "type": "rectangle", "x": 650, "y": 100, "width": 180, "height": 80,
   "backgroundColor": "#ffec99", "fillStyle": "hachure", "roughness": 1, "strokeWidth": 2,
   "boundElements": [{"id": "a2", "type": "arrow"}]},
  {"id": "db_label", "type": "text", "x": 695, "y": 125, "width": 90, "height": 30,
   "text": "Database", "fontSize": 20, "fontFamily": 1, "textAlign": "center"},

  {"id": "a1", "type": "arrow", "x": 230, "y": 140, "width": 120, "height": 0,
   "points": [[0,0],[120,0]], "strokeWidth": 2, "roughness": 1,
   "startBinding": {"elementId": "web", "focus": 0, "gap": 4},
   "endBinding": {"elementId": "api", "focus": 0, "gap": 4}},

  {"id": "a2", "type": "arrow", "x": 530, "y": 140, "width": 120, "height": 0,
   "points": [[0,0],[120,0]], "strokeWidth": 2, "roughness": 1,
   "startBinding": {"elementId": "api", "focus": 0, "gap": 4},
   "endBinding": {"elementId": "db", "focus": 0, "gap": 4}}
]
```

## Tips
- **Use `mermaid_to_excalidraw` when possible** — automatic layout avoids positioning math
- **Unique IDs**: use descriptive strings (`"box_auth"`, `"arrow_to_db"`) — never duplicate
- **Text sizing**: estimate width as `charCount * fontSize * 0.6`, height as `fontSize * 1.4`
- **Spacing**: leave 40–60px gaps between shapes for arrows and readability
- **Roughness 1** gives the classic hand-drawn look; use 0 for clean diagrams
- **Font family 1** (Virgil) matches the sketchy aesthetic; use 3 (Cascadia) for code/technical labels
- **Keep it simple**: under 15 elements is ideal. For complex diagrams, use Mermaid
- **Background**: default white. Set `app_state: {"viewBackgroundColor": "#f8f9fa"}` for light gray
