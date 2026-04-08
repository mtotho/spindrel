# Google Workspace Integration

Connect your agent to Google Drive, Gmail, Calendar, Sheets, Docs, and more via the [GWS CLI](https://github.com/nicholasgasior/gws).

## Setup

### 1. Create Google OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create a project (or select an existing one)
3. Click **Create Credentials** → **OAuth client ID**
4. Application type: **Web application**
5. Add an authorized redirect URI: `{your-server-url}/integrations/google_workspace/auth/callback`
6. Copy the **Client ID** and **Client Secret**

### 2. Enable Google APIs

In the [API Library](https://console.cloud.google.com/apis/library), enable the APIs for each service you want to use:

| Service | API to enable |
|---------|---------------|
| Drive | Google Drive API |
| Gmail | Gmail API |
| Calendar | Google Calendar API |
| Sheets | Google Sheets API |
| Docs | Google Docs API |
| Slides | Google Slides API |
| Tasks | Google Tasks API |
| Contacts | People API |
| Chat | Google Chat API |
| Forms | Google Forms API |
| Keep | Google Keep API |
| Meet | Google Meet REST API |

### 3. Configure the Integration

1. Paste your **Client ID** and **Client Secret** in the Configuration section below and click **Save**
2. Click **Install npm Packages** to install the GWS CLI binary
3. Select which Google services you want to authorize, then click **Connect Google Account**
4. Complete the Google consent flow in the browser window

### 4. Activate on a Channel

1. Go to a channel's **Integrations** tab
2. Activate **Google Workspace**
3. Choose which services this channel can access (you can give different channels different access)

That's it — your agent can now use the `gws` tool to interact with Google Workspace.

## Recommended OAuth Scopes

Scope selection happens in Google Cloud Console on your OAuth consent screen, not in Spindrel. Below are the minimum scopes per service:

| Service | Required Scopes | Notes |
|---------|----------------|-------|
| Drive | `drive.readonly` or `drive` | `drive` for read+write |
| Gmail | `gmail.readonly`, `gmail.send` | `gmail.modify` for full access |
| Calendar | `calendar.readonly` or `calendar` | `calendar` for creating events |
| Sheets | `spreadsheets.readonly` or `spreadsheets` | |
| Docs | `documents.readonly` or `documents` | |
| Slides | `presentations.readonly` or `presentations` | |
| Tasks | `tasks.readonly` or `tasks` | |
| Contacts | `contacts.readonly` or `contacts` | Uses People API |
| Chat | `chat.messages.readonly` or `chat.messages` | |
| Forms | `forms.body.readonly` or `forms.body` | |
| Keep | `keep.readonly` or `keep` | |
| Meet | `meetings.space.readonly` or `meetings.space.created` | |

All scopes are prefixed with `https://www.googleapis.com/auth/`. The `.readonly` variants are sufficient for read-only agents; use the full variants if your agent needs to create or modify content.
