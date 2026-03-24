# Agent Server UI

Universal client for the agent server — web, Android, iOS (Expo).

## Quick Start

```bash
cd ui
npm install
npm run web
```

This opens the Expo dev server. Press `w` or visit the URL it prints (usually `http://localhost:8081`).

## Connecting to Your Server

On first load you'll see a login screen asking for:

- **Server URL**: Your agent server address (e.g. `http://localhost:8000` or `https://agent.yourdomain.com`)
- **API Key**: Your `API_KEY` value from the server's `.env` (leave blank if not set)

The app tests the connection via `/health` before saving.

### CORS Setup

Your agent server needs to allow requests from the Expo dev server. Add to your server's `.env`:

```
CORS_ORIGINS=http://localhost:8081
```

Then restart the server. For production, add your actual domain:

```
CORS_ORIGINS=http://localhost:8081,https://ui.yourdomain.com
```

## What Works

- **Login** — connect to any agent server instance
- **Channel list** — browse all channels, see which bot each uses
- **Chat** — send messages, see streaming responses, tool call indicators
- **Bot browser** — view all bots and their config
- **Admin sidebar** — navigation to sessions, knowledge, tasks, tools, providers, sandboxes, logs (placeholder pages for now)

## Project Structure

```
ui/
  app/                          # Expo Router pages (file-based routing)
    (auth)/login.tsx            # Server connection screen
    (app)/
      _layout.tsx               # Three-column shell
      index.tsx                 # Channel list (home)
      channels/[channelId]/     # Chat view
      admin/                    # Admin pages (bots, sessions, etc.)
  src/
    api/
      client.ts                 # Base fetch with auth headers
      hooks/                    # TanStack Query hooks (useBots, useChannels, useChat)
    stores/
      auth.ts                   # Server URL + API key (persisted)
      chat.ts                   # Per-channel message state + SSE handling
      ui.ts                     # Sidebar/panel state
    components/
      layout/                   # AppShell, Sidebar, DetailPanel
      chat/                     # MessageBubble, MessageInput, StreamingIndicator
    hooks/
      useResponsiveColumns.ts   # Responsive 1/2/3 column layout
    types/api.ts                # TypeScript types for API responses
```

## Development

```bash
npm run web       # Web browser
npm run android   # Android (requires dev client or Expo Go)
npm run ios       # iOS (macOS only)
```

## Stack

- **Expo 55** + Expo Router v4
- **NativeWind v4** (Tailwind CSS for React Native)
- **TanStack Query v5** (server state)
- **Zustand** (client state)
- **lucide-react** (icons)
