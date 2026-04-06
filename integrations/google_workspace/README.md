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
