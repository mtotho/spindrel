# SKILL: Web Page Editing

## Purpose
Guide for creating and editing HTML/CSS/JS files in a Python Docker workspace.
Never use `cat > file` or `echo > file` to overwrite existing files — this destroys content.

---

## Rule #1: Never Destructively Overwrite

**WRONG — wipes the file:**
```bash
cat > index.html << 'EOF'
...content...
EOF
```

**WRONG:**
```bash
echo "<p>hello</p>" > index.html
```

These destroy all existing content. Never use `>` redirect on an existing file unless you are intentionally replacing the entire file from scratch and have confirmed it does not yet exist.

---

## Tools Available (Python image — no installs needed)

Python 3 is always present. Use it as your primary editing engine.

### Read a file before editing
Always read the file first so you know what you're working with:
```bash
cat index.html
```

---

## Surgical Edits with Python (preferred)

### Replace a specific string or block
```bash
python3 - << 'EOF'
path = "index.html"
with open(path, "r") as f:
    content = f.read()

content = content.replace(
    '<p>Old text</p>',
    '<p>New text</p>'
)

with open(path, "w") as f:
    f.write(content)
EOF
```

### Insert content after a specific line/tag
```bash
python3 - << 'EOF'
path = "index.html"
with open(path, "r") as f:
    content = f.read()

# Insert a <script> tag before </body>
content = content.replace(
    '</body>',
    '<script src="app.js"></script>\n</body>'
)

with open(path, "w") as f:
    f.write(content)
EOF
```

### Add a CSS class or attribute to a specific tag
```bash
python3 - << 'PYEOF'
from html.parser import HTMLParser

path = "index.html"
with open(path, "r") as f:
    content = f.read()

# Simple string replace is fine for unique targets
content = content.replace(
    '<div id="main">',
    '<div id="main" class="container">'
)

with open(path, "w") as f:
    f.write(content)
PYEOF
```

---

## Structured HTML Editing with BeautifulSoup (install if needed)

If edits are complex (e.g., manipulating multiple elements, traversing the DOM), install BeautifulSoup:

```bash
pip install -q beautifulsoup4 lxml
```

### Example: Add a nav item
```bash
python3 - << 'EOF'
from bs4 import BeautifulSoup

path = "index.html"
with open(path, "r") as f:
    soup = BeautifulSoup(f, "lxml")

nav = soup.find("nav")
if nav:
    new_link = soup.new_tag("a", href="/about")
    new_link.string = "About"
    nav.append(new_link)

with open(path, "w") as f:
    f.write(str(soup))
EOF
```

### Example: Replace inner content of an element by ID
```bash
python3 - << 'EOF'
from bs4 import BeautifulSoup

path = "index.html"
with open(path, "r") as f:
    soup = BeautifulSoup(f, "lxml")

el = soup.find(id="hero-title")
if el:
    el.string = "New Headline"

with open(path, "w") as f:
    f.write(str(soup))
EOF
```

---

## Simple sed for Line-Level Edits

Good for single-line replacements when Python feels like overkill:

```bash
# Replace first occurrence of a line containing a pattern
sed -i 's|<title>Old Title</title>|<title>New Title</title>|' index.html

# Append a line after a match
sed -i '/<\/head>/i\  <link rel="stylesheet" href="style.css">' index.html

# Delete a specific line by content
sed -i '/<p>Remove this<\/p>/d' index.html
```

> Note: `sed -i` edits in-place. Always `cat` the file after to verify.

---

## Creating a New File (the only time full write is acceptable)

Only use full write when the file does not yet exist:

```bash
# Check first
[ -f index.html ] && echo "EXISTS" || echo "SAFE TO CREATE"
```

Then write it:
```bash
cat > index.html << 'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Page Title</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <h1>Hello</h1>
  <script src="app.js"></script>
</body>
</html>
EOF
```

---

## CSS File Edits

Same rules apply. Use Python replace or sed. Never overwrite style.css with `>`.

```bash
# Append a new rule to the end of a CSS file
cat >> style.css << 'EOF'

.new-class {
  color: red;
  font-size: 1rem;
}
EOF
```

`>>` appends — this is safe for adding new rules.

---

## JS File Edits

```bash
# Append a function to app.js
cat >> app.js << 'EOF'

function newFeature() {
  console.log("added");
}
EOF
```

For replacing existing functions, use Python's `str.replace()` on the exact function signature.

---

## Verification After Every Edit

Always confirm the edit landed correctly:
```bash
# Show surrounding context of your change
grep -n "your changed string" index.html

# Or view the full file
cat index.html
```

---

## Decision Tree

```
Need to edit a file?
├── File does not exist yet → cat > file (full write OK)
└── File exists
    ├── Simple string swap → Python str.replace()
    ├── Line-level change → sed -i
    ├── Append new content → cat >> file
    └── Complex DOM manipulation → BeautifulSoup (pip install -q beautifulsoup4 lxml)
```