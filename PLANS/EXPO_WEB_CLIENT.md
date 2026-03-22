# Expo Web Client — Evaluation & Migration Plan

> **Goal**: One Expo codebase producing a web app (admin dashboard + chat UI) and mobile apps (Android first, iOS later). Replace the current Jinja2/HTMX admin dashboard and unify with the existing Android client.

---

## 1. Current State Audit

### 1.1 Admin Dashboard (Jinja2 + HTMX + Alpine.js + Tailwind)

**Stack**: Server-rendered HTML via FastAPI Jinja2Templates, styled with Tailwind (CDN), interactive via HTMX 2.0.4 and Alpine.js 3.14.8.

**Location**: `app/templates/admin/` (47 templates), `app/routers/admin*.py`, `app/static/admin.css`

**Auth**: None — assumes trusted network / same-host access.

**Features by section**:

| Section | Routes | Capabilities |
|---------|--------|--------------|
| **Dashboard** | `/admin` | Stats overview: sessions, memories, knowledge, tools, logs, sandboxes |
| **Bots** | `/admin/bots/*` | List, create, edit (76KB edit form), delete. Full YAML-equivalent config UI |
| **Channels** | `/admin/channels/*` | List, detail, settings, heartbeat config, linked knowledge/memories/plans/sessions/tasks |
| **Sessions** | `/admin/sessions/*` | List, detail view, context breakdown trace, correlations, child sessions |
| **Knowledge** | `/admin/knowledge/*` | List, create, edit (full editor), history, pinning |
| **Skills** | `/admin/skills/*` | List and edit interface |
| **Memories** | `/admin/memories` | List and search |
| **Tasks** | `/admin/tasks/*` | List and detail execution trace |
| **Delegations** | `/admin/delegations` | Automation delegation management |
| **Tools** | `/admin/tools` | Registered tool listing |
| **Providers** | `/admin/providers` | LLM provider config |
| **Sandboxes** | `/admin/sandboxes/*` | Docker sandbox management (create, stop, remove, lock) |
| **Filesystem** | `/admin/filesystem` | File index config |
| **Logs** | `/admin/logs` | Tool call trace viewer (21KB template) |

**UI patterns**: Sidebar navigation with recents/pins (localStorage), HTMX partial swaps for CRUD, dark theme (gray-900), responsive grid tables, modal-like forms.

### 1.2 Android Client (Expo + React Native + TypeScript)

**Location**: `android-client/`

**Stack**: Expo 52.0.0, Expo Router 4.0.0, React Native 0.76.7, React 18.3.1, TypeScript.

**Screens** (file-based routing in `app/(tabs)/`):

| Screen | File | Features |
|--------|------|----------|
| **Chat** | `index.tsx` | Message bubbles, mic button (animated pulse), text input, status bar (connection/bot/audio/session), voice state machine, session history loading |
| **Sessions** | `sessions.tsx` | List all sessions for current client, session switching |
| **Settings** | `settings.tsx` | Server URL, API key, bot selection, wake word config, TTS settings, audio mode toggle, transcription mode, overlay badge, connection test |

**Core modules** (`src/`):

- `agent.ts` (519 lines) — API client: `chat()`, `chatStream()` (SSE via XHR), `healthCheck()`, `testConnection()`, `listBots()`, `listSessions()`, `getSession()`, `transcribe()`
- `config.ts` — AsyncStorage-backed config (agentUrl, apiKey, botId, clientId, audio settings)
- `session.ts` — Session state management
- `service/VoiceService.ts` — Voice recording/playback orchestration with event listeners
- `voice/recorder.ts`, `stt.ts`, `tts.ts`, `wakeword.ts`, `audio-pipeline.ts`, `cheetah-stt.ts` — Full audio pipeline (Picovoice Cheetah STT, Porcupine wake word, expo-av recording, expo-speech TTS)
- `native/VoiceServiceBridge.ts`, `OverlayBridge.ts` — Android-specific: foreground service, floating overlay badge

**Voice dependencies**: Picovoice Cheetah (local STT), Porcupine (wake word), expo-av, expo-speech.

### 1.3 API Surface

All API endpoints use Bearer token auth (`Authorization: Bearer {API_KEY}`) except admin HTML routes.

**Chat (used by mobile client)**:
- `POST /chat` — Non-streaming, full response
- `POST /chat/stream` — SSE streaming (keepalive every 15s)
- `POST /chat/tool_result` — Client tool result submission
- `POST /transcribe` — Audio upload for server-side Whisper STT
- `GET /bots` — List available bots

**Sessions**:
- `GET /sessions?client_id=` — List sessions
- `GET /sessions/{id}` — Full session with messages
- `DELETE /sessions/{id}` — Delete session
- `GET /sessions/{id}/context` — Context breakdown trace
- `GET /sessions/{id}/plans` — Session plans with items
- `POST /sessions/{id}/plans/{plan_id}/status` — Update plan status
- `POST /sessions/{id}/summarize` — Force compaction

**API v1 (Channels, Sessions, Documents, Todos)**:
- `POST /api/v1/channels` — Create/retrieve channel
- `GET /api/v1/channels` — List channels
- `GET /api/v1/channels/{id}` — Channel info
- `PUT /api/v1/channels/{id}` — Update channel
- `POST /api/v1/channels/{id}/messages` — Inject message
- `POST /api/v1/channels/{id}/reset` — Reset session
- `GET /api/v1/channels/{id}/knowledge` — Channel knowledge
- `GET /api/v1/channels/{id}/messages/search` — Search messages
- `POST /api/v1/sessions` — Create/retrieve session
- `GET /api/v1/documents/search` — Full-text search
- CRUD for `/api/v1/todos`

**Admin HTML routes** (`/admin/*`): Server-rendered, return HTML fragments for HTMX. These are **not reusable** by a client app — the Expo app will need JSON API equivalents.

### 1.4 Streaming Protocol

SSE over `POST /chat/stream`. Event types:

```
skill_context, memory_context, knowledge_context  — RAG context loaded
tool_start, tool_request, tool_result              — Tool execution lifecycle
transcript                                         — STT output
response                                           — Final LLM response + client_actions
compaction_start, compaction_done                   — Memory compaction
error                                              — Error details
queued                                             — Session locked, message queued
passive_stored                                     — Passive message stored
```

Session locking prevents concurrent agent runs; excess requests are queued as Tasks.

### 1.5 Auth Model

- **Single shared API key** (`API_KEY` env var), verified via `Authorization: Bearer {key}` header
- **Admin dashboard**: No auth (trusted network assumption)
- **No user accounts, no JWT, no session cookies**

---

## 2. Technology Decisions

### 2.1 Expo Managed vs Bare Workflow

**Recommendation: Managed workflow (with config plugins for native modules)**

Rationale:
- The existing `android-client/` already uses Expo 52 managed workflow — no ejection needed
- Picovoice SDKs (Cheetah, Porcupine) work via Expo config plugins / dev client builds
- Managed workflow gives us Expo Web support out of the box via Metro bundler
- EAS Build handles native compilation; we never touch Xcode/Gradle directly
- Only eject if we hit a native module wall — unlikely given current dependencies

### 2.2 Navigation: Expo Router (file-based)

**Recommendation: Expo Router v4 (already in use)**

Structure with platform-specific layouts:
```
app/
  (auth)/
    login.tsx                  # API key / server config
  (app)/
    _layout.tsx                # Platform-adaptive: sidebar (web) vs tabs (mobile)
    (chat)/
      index.tsx                # Chat thread list / channel selector
      [channelId].tsx          # Chat thread view
    (admin)/                   # Web-only group (hidden on mobile)
      _layout.tsx
      index.tsx                # Dashboard overview
      bots/
        index.tsx              # Bot list
        [botId].tsx            # Bot edit
        new.tsx                # Bot create
      channels/
        index.tsx
        [channelId].tsx
      sessions/
        index.tsx
        [sessionId].tsx
      knowledge/
        index.tsx
        [knowledgeId].tsx
      tools.tsx
      providers.tsx
      sandboxes.tsx
      logs.tsx
    (settings)/
      index.tsx                # Settings screen
```

Key pattern: `(admin)` group uses `Platform.OS === 'web'` guard or Expo Router's platform-specific routes to hide admin features on mobile.

### 2.3 UI Library

**Recommendation: NativeWind v4 (Tailwind CSS for React Native)**

Rationale:
- Current admin dashboard already uses Tailwind — team familiarity, visual continuity
- NativeWind v4 compiles Tailwind classes to React Native styles at build time
- Full Tailwind CSS on web (no translation needed), StyleSheet on native
- Dark mode support via Tailwind `dark:` prefix (matching current admin theme)
- Smaller bundle than component libraries (Paper, Tamagui)
- Supplement with a small set of shared components (Button, Card, Input, Table, Modal) built on NativeWind

Alternatives considered:
- **React Native Paper**: Material Design look, good but opinionated; harder to match current dark theme
- **Tamagui**: Powerful but complex; compiler adds build-time overhead; overkill for this use case
- **Gluestack/NativeBase**: Recently merged; still stabilizing

### 2.4 State Management

**Recommendation: Zustand + TanStack Query (React Query)**

| Concern | Tool | Why |
|---------|------|-----|
| Server state (bots, sessions, knowledge, etc.) | TanStack Query v5 | Automatic caching, revalidation, optimistic updates, pagination. Replaces manual fetch + setState patterns |
| Client state (UI state, current bot, audio settings) | Zustand | Lightweight, no boilerplate, works identically on web + native. Replace current AsyncStorage-based config with Zustand + persist middleware |
| Streaming chat state | Zustand store per chat thread | SSE events update a Zustand store; React components subscribe to slices |

### 2.5 Auth Strategy

**Phase 1 (current model)**: Keep single API key auth. Store in Zustand persisted store (AsyncStorage on mobile, localStorage on web). Send as `Authorization: Bearer {key}` on all requests.

**Phase 2 (recommended upgrade)**: Add lightweight user accounts.

```
POST /auth/login   → { api_key } → { token: JWT, expires_in }
POST /auth/refresh → { token }   → { token: JWT, expires_in }
```

- JWT with short expiry (1h) + refresh token
- `api_key` becomes the admin credential; JWT is the session credential
- Web: httpOnly cookie for JWT (CSRF protection) or Authorization header
- Mobile: SecureStore (expo-secure-store) for token storage
- Admin routes get role-based guard (`admin` vs `viewer`)

This is a backend change that can be deferred — the Expo app should abstract auth behind a hook (`useAuth`) so swapping API-key for JWT is a config change.

### 2.6 Additional Libraries

| Need | Library | Notes |
|------|---------|-------|
| SSE client | `@microsoft/fetch-event-source` (web) / XHR adapter (native) | Current XHR approach works on native; web needs fetch-based SSE for POST |
| Forms | React Hook Form + Zod | Bot edit form is complex (76KB template); need validation |
| Icons | `lucide-react-native` | Tree-shakeable, works on web + native |
| Audio | `expo-av` + `expo-speech` | Already in use |
| Secure storage | `expo-secure-store` | For API key / tokens on mobile |
| Clipboard | `expo-clipboard` | Copy code blocks, session IDs |
| Haptics | `expo-haptics` | Tactile feedback on mobile send/mic actions |

---

## 3. Feature Scope

### 3.1 Web (Admin + Chat)

#### Chat Features
- **Channel sidebar**: List all channels, filter by bot/integration, search
- **Chat thread view**: Message bubbles with markdown rendering, code blocks, tool call indicators
- **Streaming display**: Real-time token streaming, tool execution progress, RAG context indicators
- **Message input**: Text input with send button, file/audio upload
- **Session management**: List sessions, switch, delete, view context breakdown
- **Plan viewer**: Session plans with status toggles (inline in chat or side panel)

#### Admin Features (parity with current dashboard)
- **Dashboard**: Stats overview (sessions, memories, knowledge, tools, sandboxes)
- **Bot management**: Full CRUD with YAML-equivalent form (system prompt editor, tool selection, model picker, all bot config fields)
- **Channel management**: List, detail, settings, linked entities
- **Session browser**: List, detail, context breakdown, correlations, child sessions
- **Knowledge management**: CRUD, history, pinning, full content editor
- **Skill management**: List and edit
- **Memory browser**: List and search
- **Task management**: List, detail, execution trace
- **Tool browser**: Registered tools with schemas
- **Provider config**: LLM provider management
- **Sandbox management**: Docker sandbox CRUD, lock management
- **Filesystem indexes**: Config viewer
- **Log viewer**: Tool call trace (replicate the 21KB trace template)
- **Delegation management**: Automation config

#### Web-Specific
- Keyboard shortcuts (Cmd+K for search, Cmd+Enter to send, etc.)
- Responsive layout: sidebar collapses on narrow viewports
- URL-based routing (deep links to any admin page or chat channel)

### 3.2 Mobile (Android First, iOS Future)

#### Chat Features (primary experience)
- **Chat interface**: Message bubbles, streaming display, text input
- **Voice input**: Mic button with animated state (idle → listening → processing → responding)
- **Wake word detection**: "Hey [bot name]" hands-free activation (Porcupine)
- **Local STT**: On-device transcription (Picovoice Cheetah) with server fallback
- **TTS playback**: Read responses aloud (expo-speech)
- **Audio modes**: Native audio (send raw audio to Gemini) vs STT-then-text
- **Always-listening mode**: Android foreground service + floating overlay badge
- **Push notifications**: Bot replies when app is backgrounded (expo-notifications + server-side push)
- **Session management**: List, switch, delete sessions
- **Bot switcher**: Quick bot selection

#### Mobile-Specific
- Haptic feedback on send/mic actions
- Pull-to-refresh on session list
- Share sheet integration (share text/URLs to bot)
- Offline queue: store messages when offline, send on reconnect
- Compact settings screen (server URL, API key, audio config, bot selection)

#### Explicitly NOT on Mobile
- Full admin dashboard (bot editing, knowledge management, sandbox control, etc.)
- Log/trace viewer
- Provider configuration

---

## 4. Migration Strategy

### 4.1 New Admin JSON API

The current admin dashboard uses server-rendered HTML with HTMX. The Expo app needs JSON APIs for the same operations. **This is the critical backend prerequisite.**

New endpoints needed (under `/api/v1/admin/`):

```
# Dashboard
GET  /admin/stats                          → { sessions, memories, knowledge, tools, sandboxes }

# Bots
GET    /admin/bots                         → [BotConfig]
GET    /admin/bots/{id}                    → BotConfig (full detail)
POST   /admin/bots                         → BotConfig (create)
PUT    /admin/bots/{id}                    → BotConfig (update)
DELETE /admin/bots/{id}                    → 204

# Channels
GET    /admin/channels                     → [Channel] (with filters)
GET    /admin/channels/{id}                → Channel (full detail + linked entities)
PUT    /admin/channels/{id}                → Channel (update settings)
DELETE /admin/channels/{id}                → 204

# Sessions (extend existing /sessions endpoints)
GET    /admin/sessions                     → [Session] (with pagination, filters)
GET    /admin/sessions/{id}/trace          → TraceData (context breakdown, tool calls)
GET    /admin/sessions/{id}/correlations   → [CorrelatedSession]

# Knowledge
GET    /admin/knowledge                    → [KnowledgeEntry] (with pagination)
GET    /admin/knowledge/{id}               → KnowledgeEntry (with history)
POST   /admin/knowledge                    → KnowledgeEntry
PUT    /admin/knowledge/{id}               → KnowledgeEntry
DELETE /admin/knowledge/{id}               → 204
POST   /admin/knowledge/{id}/pin           → 204

# Skills
GET    /admin/skills                       → [Skill]
GET    /admin/skills/{id}                  → Skill (with content)
PUT    /admin/skills/{id}                  → Skill

# Memories
GET    /admin/memories                     → [Memory] (with search, pagination)

# Tasks
GET    /admin/tasks                        → [Task]
GET    /admin/tasks/{id}                   → Task (with execution trace)

# Tools
GET    /admin/tools                        → [ToolSchema]

# Providers
GET    /admin/providers                    → [Provider]
PUT    /admin/providers/{id}               → Provider

# Sandboxes
GET    /admin/sandboxes                    → [Sandbox]
POST   /admin/sandboxes                    → Sandbox (create/ensure)
POST   /admin/sandboxes/{id}/stop          → 204
DELETE /admin/sandboxes/{id}               → 204
PUT    /admin/sandboxes/{id}/lock          → 204

# Delegations
GET    /admin/delegations                  → [Delegation]
POST   /admin/delegations                  → Delegation
DELETE /admin/delegations/{id}             → 204

# Filesystem
GET    /admin/filesystem                   → [FileIndex]

# Logs
GET    /admin/logs                         → [LogEntry] (with pagination, filters)
GET    /admin/logs/{id}                    → LogEntry (full trace)
```

**Strategy**: Extract the query/mutation logic from existing `admin*.py` route handlers (which currently return HTML) into shared service functions, then expose them as both HTML (existing) and JSON (new) endpoints. This keeps both dashboards working during migration.

### 4.2 Phase 1 — Parallel Web App (Weeks 1–4)

**Goal**: Expo Web running alongside the old dashboard with chat functionality + basic admin.

**Backend**:
- [ ] Create `/api/v1/admin/` router with JSON endpoints (start with stats, bots, channels, sessions)
- [ ] Add CORS configuration for Expo Web dev server origin
- [ ] Optional: Add JWT auth endpoint (can defer)

**Expo App**:
- [ ] Initialize new Expo project in `web-client/` (fresh start — see Section 5 rationale)
- [ ] Set up Expo Router with platform-adaptive layout (sidebar web, tabs mobile)
- [ ] Configure NativeWind v4 with dark theme matching current dashboard
- [ ] Build shared API client with TanStack Query hooks
- [ ] Implement auth flow (API key entry → stored in Zustand persist)
- [ ] Build chat UI: channel list, message thread with streaming SSE, text input
- [ ] Build basic admin: dashboard stats, bot list/detail (read-only)
- [ ] Deploy Expo Web build as static files (served by FastAPI or separate nginx)

**Validation**: Chat works end-to-end on web. Admin shows read-only bot/session data.

### 4.3 Phase 2 — Admin Feature Parity (Weeks 5–10)

**Goal**: Full admin CRUD on web, matching all current dashboard features.

**Backend**:
- [ ] Complete all `/api/v1/admin/` endpoints
- [ ] Add WebSocket endpoint for real-time admin updates (optional, nice-to-have)

**Expo App**:
- [ ] Bot management: create, edit (full form with system prompt editor, tool picker, model selector), delete
- [ ] Channel management: detail view, settings, linked entities
- [ ] Session browser: list with filters, detail with context breakdown, trace viewer
- [ ] Knowledge management: CRUD, history, pinning, content editor
- [ ] Skill management: list and edit
- [ ] Memory browser with search
- [ ] Task viewer with execution trace
- [ ] Tool browser, provider config, sandbox management, filesystem indexes
- [ ] Log/trace viewer (port the complex trace visualization)
- [ ] Delegation management

**Validation**: Every feature accessible in current `/admin` is available in Expo Web. Side-by-side testing.

### 4.4 Phase 3 — Decommission Old Dashboard + Ship Mobile (Weeks 11–14)

**Backend**:
- [ ] Remove Jinja2 templates, HTMX admin routes, `app/static/admin.css`
- [ ] Remove Jinja2/HTMX dependencies from `requirements.txt`
- [ ] Serve Expo Web build at `/admin` (or `/` with API at `/api/`)
- [ ] Add push notification support (Firebase Cloud Messaging for Android)

**Mobile**:
- [ ] Port voice pipeline from `android-client/` into `web-client/` (platform-gated)
- [ ] Wake word, local STT, TTS, foreground service, overlay badge
- [ ] Push notifications (expo-notifications + FCM)
- [ ] EAS Build configuration for Android APK/AAB
- [ ] Beta testing via EAS internal distribution

**Decommission**:
- [ ] Redirect `/admin` old routes to Expo Web app
- [ ] Remove `app/templates/`, `app/routers/admin*.py`
- [ ] Archive `android-client/` (code lives on in `web-client/`)

**Validation**: Old dashboard fully removed. Mobile app installable via EAS. All admin + chat functionality working on web and mobile.

---

## 5. Open Questions & Recommendations

### 5.1 WebSocket vs SSE for Real-Time Chat

**Recommendation: Keep SSE (POST-based), add optional WebSocket later**

- Current SSE implementation works well and is battle-tested
- SSE over POST is unusual but solves the "send body with stream request" problem
- WebSocket would be cleaner for bidirectional communication (typing indicators, presence)
- Migration path: Add `WS /chat/ws` endpoint that wraps the same `run_stream()` internals; client detects and prefers WS when available
- **Decision**: SSE for Phase 1-2, evaluate WebSocket for Phase 3 based on needs

### 5.2 Auth Strategy

**Recommendation: API key for Phase 1, JWT for Phase 2+**

- Current single API key is fine for single-user / trusted-network deployments
- Multi-user needs (role-based admin access, per-user sessions) require JWT
- The Expo app should use a `useAuth()` hook that abstracts the mechanism
- **Decision**: Defer JWT to Phase 2 backend work; design the hook interface now

### 5.3 Monorepo Structure

**Recommendation: Same repo, separate directory**

```
/
  app/                  # FastAPI backend (existing)
  web-client/           # Expo app (new)
    app/                # Expo Router pages
    src/                # Shared logic (API client, stores, hooks)
      api/              # TanStack Query hooks
      stores/           # Zustand stores
      components/       # Shared UI components
      voice/            # Voice pipeline (ported from android-client)
      native/           # Native bridges (ported from android-client)
    package.json
  android-client/       # Existing (archived after Phase 3)
  bots/                 # Bot YAML configs (existing)
  skills/               # Skill markdown files (existing)
  docker-compose.yml    # Add expo dev service
```

Rationale:
- Shared git history, single PR for coordinated backend+frontend changes
- No monorepo tooling needed (Turborepo, Nx) — it's one Expo app + one Python backend
- Docker Compose can add an `expo-dev` service for local development
- **Decision**: Same repo. Revisit if the Expo app grows complex enough to warrant separation.

### 5.4 Fresh Expo Project vs Migrate `android-client/`

**Recommendation: Fresh project in `web-client/`, port modules incrementally**

Rationale:
- `android-client/` was built as Android-only with no web considerations
- Layout structure (`(tabs)/`) needs redesign for platform-adaptive sidebar/tabs
- Voice modules are cleanly separated in `src/voice/` and `src/native/` — easy to copy
- `src/agent.ts` API client should be rewritten with TanStack Query anyway
- Starting fresh avoids carrying Android-specific assumptions into the web build
- **Decision**: New project. Port `src/voice/`, `src/native/`, and `src/service/` in Phase 3.

### 5.5 Expo Web Deployment

Options:
1. **Static export** (`npx expo export --platform web`) → serve via FastAPI `StaticFiles` or nginx
2. **Separate domain/port** → `app.example.com` (Expo) + `api.example.com` (FastAPI)
3. **Docker multi-stage build** → Expo build step + FastAPI image serves the output

**Recommendation**: Option 1 for simplicity. Build step produces static files, FastAPI serves them at `/` (or `/app/`). API stays at `/api/`, `/chat/`, `/sessions/`, etc. Single port, no CORS issues in production.

---

## 6. Effort Estimate & Recommendation

### Effort Sizing (Solo Developer)

| Phase | Scope | Effort | Cumulative |
|-------|-------|--------|------------|
| **Phase 1** | Chat + basic admin on Expo Web | 3–4 weeks | 3–4 weeks |
| **Phase 2** | Full admin parity | 5–6 weeks | 8–10 weeks |
| **Phase 3** | Decommission + mobile ship | 3–4 weeks | 11–14 weeks |

**Backend API work** (creating JSON admin endpoints) is ~30% of Phase 1-2 effort. It's the long pole — most Expo UI work is blocked on having JSON APIs.

### Biggest Risks

1. **Admin API surface area**: 47 templates worth of features → many JSON endpoints to build and test. The bot edit form alone is 76KB of HTML.
2. **Trace/log viewer complexity**: The 21KB trace template has intricate nested visualization. Porting to React will be the hardest single UI component.
3. **SSE on web**: `POST`-based SSE is non-standard. `@microsoft/fetch-event-source` handles it, but needs testing across browsers.
4. **Voice on web**: Wake word (Porcupine) and local STT (Cheetah) are native-only. Web voice input would need Web Speech API or server-side Whisper only.

### Go / No-Go Criteria

**Go if**:
- [ ] You want a unified codebase for web + mobile (strong yes given existing Expo Android app)
- [ ] You're willing to invest ~3 months of focused effort
- [ ] The admin dashboard needs to be accessible outside the trusted network (auth story)
- [ ] Mobile chat + voice is a priority (Alexa-replacement vision)

**No-go if**:
- [ ] The current HTMX dashboard is "good enough" and mobile isn't a priority
- [ ] Time budget is < 2 months (Phase 1 alone is 3-4 weeks)
- [ ] Multi-platform UI maintenance cost is a concern (one Jinja2 codebase is simpler than React Native cross-platform)

### Recommendation

**Go — start with Phase 1 (chat-focused).** The existing Android Expo client proves the mobile stack works. Expo Web gives you a modern chat UI for free alongside mobile. Phase 1 delivers immediate value (web chat client) without committing to the full admin migration. Phase 2 can be evaluated after Phase 1 ships.

**Quick win**: Before Phase 1, prototype the Expo Web chat screen (~2 days) to validate SSE streaming and NativeWind rendering on web. If that works cleanly, commit to the full plan.
