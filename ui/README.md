# Agent Server UI

Universal client for the agent server — web, Android, iOS (Expo).

## Quick Start (Local Dev)

```bash
cd ui
npm install
npm run web
```

This starts the Expo dev server (default port 8081). If that port is taken, it'll prompt for another.

On first load you'll see a login screen. Enter:
- **Server URL**: `http://localhost:8000` (or wherever your agent server runs)
- **API Key**: Your `API_KEY` from the server's `.env` (leave blank if not set)

### CORS Setup

The agent server must allow requests from the UI's origin. Add to your server's `.env`:

```
CORS_ORIGINS=http://localhost:8081
```

If running on a different port, update accordingly. Comma-separate multiple origins:

```
CORS_ORIGINS=http://localhost:8081,http://localhost:19006,https://agent.yourdomain.com
```

Restart the server after changing `.env`.

## Production Deployment

The UI runs as its own container in docker-compose — nginx serving static files on port 8081.

### Deploy

Same workflow as everything else — push and pull:

```bash
# Dev machine:
git push

# Prod server:
git pull
docker compose up --build -d
```

The UI is at `http://yourserver:8081`. The login screen asks for the agent server URL.

### CORS

The agent server must allow requests from the UI's origin. Add to your server's `.env`:

```
CORS_ORIGINS=http://10.10.30.208:8081
```

For multiple origins (prod + local dev):

```
CORS_ORIGINS=http://10.10.30.208:8081,http://localhost:8081
```

Then restart the agent server process.

### Local Dev (Without Docker)

```bash
cd ui
npm install
npm run web
```

Hot-reload at `http://localhost:8081`. Set `CORS_ORIGINS=http://localhost:8081` in your server `.env`.

## What Works

- **Login** — connect to any agent server instance
- **Channel list** — browse all channels, see which bot each uses
- **Chat** — send messages, see streaming responses, tool call indicators
- **Bot browser** — view all bots and their config
- **Admin sidebar** — navigation to sessions, knowledge, tasks, tools, providers, sandboxes, logs (placeholder pages — read-only for now)

## Project Structure

```
ui/
  app/                          # Expo Router pages (file-based routing)
    _layout.tsx                 # Root: auth gate, providers
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
      auth.ts                   # Server URL + API key (persisted to localStorage)
      chat.ts                   # Per-channel message state + SSE handling
      ui.ts                     # Sidebar/panel state
    components/
      layout/                   # AppShell, Sidebar, DetailPanel
      chat/                     # MessageBubble, MessageInput, StreamingIndicator
    hooks/
      useResponsiveColumns.ts   # Responsive 1/2/3 column layout
      useHydrated.ts            # Zustand persist hydration hook
    types/api.ts                # TypeScript types for API responses
  metro.config.js               # NativeWind + zustand CJS fix
  tailwind.config.js            # Dark theme colors
```

## Development

```bash
npm run web                     # Web browser
npm run web -- --port 3000      # Custom port
npm run android                 # Android (needs dev client)
npm run ios                     # iOS (macOS only)
npx expo export --platform web  # Production build
npx expo start --web --clear    # Clear Metro cache + start
```

## Stack

- **Expo 55** + Expo Router v4
- **NativeWind v4** (Tailwind CSS for React Native)
- **TanStack Query v5** (server state / caching)
- **Zustand 5** (client state / persistence)
- **lucide-react** (icons)

## Known Issues

- **Zustand + Metro**: Zustand's ESM middleware uses `import.meta.env` which Metro can't handle. Fixed via `metro.config.js` forcing the CJS version. Don't remove that resolver override.
- **lucide-react vs lucide-react-native**: Using `lucide-react` (not `-native`) because v1.x of the native package has broken dist paths. Works fine on web; will need a wrapper or fix for native builds later.
