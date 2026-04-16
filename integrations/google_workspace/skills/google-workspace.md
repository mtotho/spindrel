---
name: Google Workspace
description: Comprehensive guide to the GWS CLI tool for Drive, Gmail, Calendar, Sheets, Docs, and more
---
# SKILL: Google Workspace CLI

## Overview
The `gws` tool wraps the Google Workspace CLI, giving you access to 18+ Google services.
Each command follows this pattern:

```
gws <service> <resource> <method> [flags]
```

Or use helper shortcuts (prefixed with `+`):

```
gws <service> +<shortcut> [flags]
```

## Common Flags

| Flag | Description |
|------|-------------|
| `--params '{"key":"val"}'` | URL / path parameters (JSON object) |
| `--json '{"key":"val"}'` | Request body (JSON object) |
| `--format table` | Output as a formatted table (default: JSON) |
| `--format csv` | Output as CSV |
| `--page-all` | Automatically paginate through all results |
| `--upload <path>` | Upload a local file (Drive, etc.) |
| `--output <path>` | Download/export to a local file |
| `--dry-run` | Show the API request without executing |
| `--fields "field1,field2"` | Select specific response fields |

## Google Drive

### Key Commands
```bash
# List files
gws drive files list
gws drive files list --params '{"q":"mimeType=\"application/vnd.google-apps.folder\""}' --format table

# Search files by name
gws drive files list --params '{"q":"name contains \"report\""}' --format table

# Get file metadata
gws drive files get --params '{"fileId":"FILE_ID"}'

# Download a file
gws drive files get --params '{"fileId":"FILE_ID","alt":"media"}' --output ./downloaded.pdf

# Upload a file
gws drive +upload --upload ./document.pdf

# Create a folder
gws drive files create --json '{"name":"New Folder","mimeType":"application/vnd.google-apps.folder"}'

# Move a file (add to new parent, remove from old)
gws drive files update --params '{"fileId":"FILE_ID","addParents":"FOLDER_ID","removeParents":"OLD_FOLDER_ID"}'

# Delete a file
gws drive files delete --params '{"fileId":"FILE_ID"}'

# List files in a specific folder
gws drive files list --params '{"q":"\"FOLDER_ID\" in parents"}' --format table

# Share a file
gws drive permissions create --params '{"fileId":"FILE_ID"}' --json '{"role":"reader","type":"user","emailAddress":"user@example.com"}'
```

### Helper Shortcuts
- `+upload` — Upload file with automatic MIME detection
- `+export` — Export Google Docs/Sheets as PDF, DOCX, etc.

## Gmail

### Key Commands
```bash
# Triage inbox (unread, important)
gws gmail +triage

# List messages
gws gmail users.messages list --params '{"userId":"me","q":"is:unread"}' --format table

# Read a message
gws gmail users.messages get --params '{"userId":"me","id":"MSG_ID"}'

# Send an email
gws gmail +send --params '{"to":"recipient@example.com"}' --json '{"subject":"Hello","body":"Message body"}'

# Reply to a message
gws gmail +reply --params '{"messageId":"MSG_ID"}' --json '{"body":"Reply text"}'

# Search messages
gws gmail users.messages list --params '{"userId":"me","q":"from:boss@company.com after:2024/01/01"}' --format table

# List labels
gws gmail users.labels list --params '{"userId":"me"}'

# Modify labels (archive = remove INBOX)
gws gmail users.messages modify --params '{"userId":"me","id":"MSG_ID"}' --json '{"removeLabelIds":["INBOX"]}'

# Trash a message
gws gmail users.messages trash --params '{"userId":"me","id":"MSG_ID"}'

# Create a draft
gws gmail users.drafts create --params '{"userId":"me"}' --json '{"message":{"raw":"BASE64_ENCODED"}}'
```

### Helper Shortcuts
- `+triage` — Smart inbox summary (unread, flagged, recent)
- `+send` — Compose and send with simple params
- `+reply` — Reply to a specific message

## Google Calendar

### Key Commands
```bash
# Today's agenda
gws calendar +agenda

# List upcoming events
gws calendar events list --params '{"calendarId":"primary","timeMin":"2024-01-01T00:00:00Z","maxResults":"10","singleEvents":"true","orderBy":"startTime"}' --format table

# Create an event
gws calendar +insert --json '{"summary":"Team Meeting","start":{"dateTime":"2024-06-15T10:00:00-05:00"},"end":{"dateTime":"2024-06-15T11:00:00-05:00"},"attendees":[{"email":"colleague@example.com"}]}'

# Get event details
gws calendar events get --params '{"calendarId":"primary","eventId":"EVENT_ID"}'

# Update an event
gws calendar events update --params '{"calendarId":"primary","eventId":"EVENT_ID"}' --json '{"summary":"Updated Title"}'

# Delete an event
gws calendar events delete --params '{"calendarId":"primary","eventId":"EVENT_ID"}'

# List calendars
gws calendar calendarList list --format table

# Quick add (natural language)
gws calendar events quickAdd --params '{"calendarId":"primary","text":"Lunch with Alice tomorrow at noon"}'
```

### Helper Shortcuts
- `+agenda` — Today's events at a glance
- `+insert` — Create event with simplified input

## Google Sheets

### Key Commands
```bash
# Read a range
gws sheets +read --params '{"spreadsheetId":"SHEET_ID","range":"Sheet1!A1:D10"}'

# Append rows
gws sheets +append --params '{"spreadsheetId":"SHEET_ID","range":"Sheet1!A1"}' --json '{"values":[["Alice","100"],["Bob","200"]]}'

# Get spreadsheet metadata
gws sheets spreadsheets get --params '{"spreadsheetId":"SHEET_ID"}'

# Update a range
gws sheets spreadsheets.values update --params '{"spreadsheetId":"SHEET_ID","range":"Sheet1!A1","valueInputOption":"USER_ENTERED"}' --json '{"values":[["Updated"]]}'

# Create a new spreadsheet
gws sheets spreadsheets create --json '{"properties":{"title":"New Sheet"}}'

# Clear a range
gws sheets spreadsheets.values clear --params '{"spreadsheetId":"SHEET_ID","range":"Sheet1!A1:D10"}'
```

### Helper Shortcuts
- `+read` — Read cells from a range
- `+append` — Add rows to the end of a range

## Google Docs

### Key Commands
```bash
# Create a document (⚠️ Docs API ignores "parents" — create first, then move via Drive)
gws docs documents create --json '{"title":"My Document"}'

# Move doc to a folder after creation
gws drive files update --params '{"fileId":"DOC_ID","addParents":"FOLDER_ID","removeParents":"root"}'

# Get document content
gws docs documents get --params '{"documentId":"DOC_ID"}'

# Insert text (index 1 = start of document body)
gws docs documents batchUpdate --params '{"documentId":"DOC_ID"}' --json '{"requests":[{"insertText":{"location":{"index":1},"text":"Hello World"}}]}'
```

> **Note:** Docs and Slides APIs require enablement in your GCP project. Read operations (list, get, search) work without extra config.

## Google Slides

> **⚠️ Path syntax:** Use dots for sub-resources — `slides presentations.pages get` works, `slides presentations pages get` (space) fails silently.

```bash
# Create a presentation
gws slides presentations create --json '{"title":"My Presentation"}'

# Get presentation (includes slide/page IDs)
gws slides presentations get --params '{"presentationId":"PRES_ID"}'

# Get a specific page/slide
gws slides presentations.pages get --params '{"presentationId":"PRES_ID","pageObjectId":"PAGE_ID"}'

# Insert text into a shape (⚠️ default title slide placeholders are locked — create a blank slide first)
gws slides presentations.batchUpdate --params '{"presentationId":"PRES_ID"}' --json '{"requests":[{"insertText":{"objectId":"SHAPE_ID","text":"Hello","insertionIndex":0}}]}'

# Create a blank slide (use layoutIndex, NOT predefinedLayout — predefinedLayout is unsupported)
gws slides presentations.batchUpdate --params '{"presentationId":"PRES_ID"}' --json '{"requests":[{"createSlide":{"slideLayoutReference":{"layoutIndex":1}}}]}'
```

## Google Tasks

```bash
# List task lists
gws tasks tasklists list --format table

# List tasks in a specific list (use tasklist ID from above)
gws tasks tasks list --params '{"tasklist":"TASKLIST_ID"}'

# Create a task
gws tasks tasks insert --params '{"tasklist":"TASKLIST_ID"}' --json '{"title":"Buy groceries","due":"2024-06-20T00:00:00Z"}'

# Move/reorder a task
gws tasks tasks move --params '{"tasklist":"TASKLIST_ID","task":"TASK_ID"}' --json '{"previous":"OTHER_TASK_ID"}'

# Update a task (⚠️ GOTCHA: `id` must be in --json body, not just --params)
gws tasks tasks update --params '{"tasklist":"TASKLIST_ID","task":"TASK_ID"}' --json '{"id":"TASK_ID","status":"completed"}'

# Delete a task
gws tasks tasks delete --params '{"tasklist":"TASKLIST_ID","task":"TASK_ID"}'
```

## Google Contacts (People API)

```bash
# List contacts
gws people people.connections list --params '{"resourceName":"people/me","personFields":"names,emailAddresses,phoneNumbers"}' --format table

# Search contacts
gws people people searchContacts --params '{"query":"Alice","readMask":"names,emailAddresses"}'

# Create a contact
gws people people createContact --json '{"names":[{"givenName":"John","familyName":"Doe"}],"emailAddresses":[{"value":"john@example.com"}]}'
```

## Google Chat

```bash
# List spaces
gws chat spaces list --format table

# Send a message
gws chat spaces.messages create --params '{"parent":"spaces/SPACE_ID"}' --json '{"text":"Hello from the bot!"}'
```

## Google Forms

```bash
# Get a form
gws forms forms get --params '{"formId":"FORM_ID"}'

# List responses
gws forms forms.responses list --params '{"formId":"FORM_ID"}' --format table
```

## Google Keep

```bash
# List notes
gws keep notes list --format table

# Create a note
gws keep notes create --json '{"title":"Quick Note","body":{"text":{"text":"Remember to..."}}}'
```

## Google Meet

```bash
# Create a meeting space
gws meet spaces create --json '{}'

# Get a space
gws meet spaces get --params '{"name":"spaces/SPACE_ID"}'
```

## Tips

1. **Pagination**: Use `--page-all` to get all results, or `--params '{"pageSize":"50"}'` to control page size
2. **Output format**: Default is JSON. Use `--format table` for human-readable output
3. **Field selection**: Use `--fields "id,name,mimeType"` to reduce response size
4. **Date format**: Google APIs use RFC 3339 (`2024-06-15T10:00:00Z` or with offset `-05:00`)
5. **Gmail search**: Uses the same syntax as the Gmail search bar (`from:`, `to:`, `subject:`, `after:`, `before:`, `is:unread`, etc.)
6. **Drive search**: Use `q` parameter with Drive query syntax (`name contains`, `mimeType=`, `modifiedTime >`, etc.)
7. **Error handling**: If a command fails, check the error message — common issues are wrong IDs, missing permissions, or malformed JSON
8. **Dry run**: Use `--dry-run` to preview the API request before executing
