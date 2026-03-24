# Expo Universal Client — Revised Plan

> **Goal**: One Expo codebase → web, Android, iOS. Chat-centric UX where admin features are contextual, not a separate world. Replace the Jinja2/HTMX admin dashboard entirely.

---

## 1. What's Wrong With the Current Admin

The existing admin is a classic "entity CRUD browser" — separate pages for bots, channels, sessions, knowledge, tasks, etc. This means constant context-switching:

- **No cross-linking**: Sessions don't link back to their channel. Channel list shows bot_id as plain text. You copy-paste UUIDs between pages.
- **Two session surfaces**: Inline HTMX row expansion on the list page vs standalone `/sessions/{id}/detail`. The `?expand=` URL hack means sessions aren't bookmarkable.
- **Bot edit is a 1350-line scroll**: 14+ sections, no section nav, no way to jump to "Memory" without scrolling past everything else.
- **No contextual access**: To change a channel's bot config, you leave the channel, go to bots, find the bot, scroll the mega-form. To see what tasks a channel has, go to tasks, filter manually.
- **Recents only track bots/channels**: Can't pin a session or task you're debugging.
- **Dead-end navigation**: Task detail → session link → no way back to channel. Delegations → `?expand=` hack → lost context.

## 2. UX Architecture: Chat-Centric With Contextual Panels

### Core Concept

The primary surface is always a **channel/chat view**. Admin features aren't a separate "admin section" — they're contextual panels and drawers that open alongside what you're working with.

```
┌─────────────────────────────────────────────────────────┐
│ ┌──────────┐ ┌───────────────────────┐ ┌─────────────┐ │
│ │          │ │                       │ │             │ │
│ │ Channel  │ │    Chat / Content     │ │  Detail     │ │
│ │ Sidebar  │ │    Area               │ │  Panel      │ │
│ │          │ │                       │ │  (context-  │ │
│ │ - Chats  │ │  Messages, sessions,  │ │  sensitive) │ │
│ │ - Pinned │ │  or entity detail     │ │             │ │
│ │ - Search │ │                       │ │  Bot config │ │
│ │          │ │                       │ │  Session    │ │
│ │ ──────── │ │                       │ │  trace      │ │
│ │ Admin    │ │                       │ │  Knowledge  │ │
│ │ - Bots   │ │                       │ │  Tasks      │ │
│ │ - System │ │                       │ │  etc.       │ │
│ │          │ │                       │ │             │ │
│ └──────────┘ └───────────────────────┘ └─────────────┘ │
│ ┌─────────────────────────────────────────────────────┐ │
│ │  Command Palette (Cmd+K) — jump to anything         │ │
│ └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### Three-Column Layout (Web)

1. **Left sidebar** (~240px, collapsible):
   - **Channels section**: Active channels grouped by bot, with unread indicators, pinning, search/filter
   - **Admin section** (collapsible): Bots, Knowledge, Tasks, Tools, Providers, Sandboxes, Logs
   - **Recents**: Universal recents (any entity type), pinnable

2. **Center content area** (flexible):
   - When a channel is selected: Chat messages with streaming, input bar
   - When an admin entity is selected: Entity detail/edit view
   - When browsing a list: Table/grid view of entities

3. **Right detail panel** (~350px, toggleable, slide-in):
   - Context-sensitive based on what's selected or hovered
   - From a chat: Session info, bot config summary, active plans, linked knowledge
   - From a session message: Trace detail, tool calls, context breakdown
   - From a bot list item: Quick bot preview without leaving the list
   - Always has a "Open full" button to make it the center content

### Key UX Patterns

**Everything is a link**: Every entity reference (bot_id, session_id, channel_id, task_id) is clickable. Clicking opens in the detail panel by default, Cmd+Click opens in center content.

**Breadcrumb + context bar**: Top of center area shows: `Channel: #general → Session: abc123 → Bot: assistant`. Each segment is clickable. Shows connection status, session stats.

**Command palette (Cmd+K)**: Fuzzy search across all entities — channels, bots, sessions, knowledge, tasks. Type "bot:assistant" or "session:abc" or just search terms. Recent items shown by default.

**Inline editing**: Bot config, channel settings, knowledge entries can be edited in the detail panel without navigating away. Changes save immediately (optimistic updates via TanStack Query mutations).

**Tab groups in detail panel**: When viewing a channel's detail panel:
- Overview (bot, settings, status)
- Sessions (history, switch, restore)
- Knowledge (scoped entries, pin/unpin)
- Tasks (active/recent for this channel)
- Plans (active plans)
- Settings (heartbeat, compression, etc.)

**Trace overlay**: Clicking a message's trace icon opens a slide-over trace viewer (not a page navigation). Shows the full tool call chain, context assembly, timing.

### Mobile Layout (Two-Column → Single)

On mobile (and narrow web), collapses to single-column:
- Channel list → tap → chat view (with back gesture)
- Swipe left on chat → detail panel slides in
- Admin items accessible via hamburger menu or bottom sheet
- No admin editing on mobile (read-only admin, full chat)

### Comparison: Old vs New Navigation Flows

**"Change a channel's bot system prompt"**
- Old: Channels → find channel → detail → note bot_id → sidebar → Bots → find bot → scroll to System Prompt section → edit → save → back to channel (lost context)
- New: Click channel → detail panel shows bot summary → click "Edit Bot" → system prompt section opens in panel (or center) → edit → save → you're still looking at the channel

**"Debug why a task failed"**
- Old: Tasks → find task → detail → click session link → new page → lost task context → note correlation_id → Logs → search
- New: Tasks list → click task → detail panel shows task + session + trace inline → click any message to see its trace in the same panel

**"See what knowledge a bot has access to"**
- Old: Bots → find bot → scroll to Knowledge section → see list → click one → new page → lost bot context
- New: Click bot → detail panel → Knowledge tab → see entries → click one → expands inline or in sub-panel

---

## 3. Technology Stack

### One Expo App, All Platforms

This is a single Expo project that builds for web, Android, and iOS. No separate "android" and "web" phases. Platform differences are handled with:
- `Platform.select()` for minor style/behavior tweaks
- Platform-specific files (`.web.tsx`, `.native.tsx`) for truly different implementations (e.g., voice input)
- Responsive layout hooks for column count (3-col desktop, 2-col tablet, 1-col phone)

### Core Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Framework | Expo 52+ (managed) | One build system, all platforms |
| Routing | Expo Router v4 | File-based, URL-driven, deep linking |
| Styling | NativeWind v4 | Tailwind on web, StyleSheet on native; matches existing design vocabulary |
| Server state | TanStack Query v5 | Caching, revalidation, optimistic updates, pagination |
| Client state | Zustand | Lightweight, no boilerplate, persist middleware |
| Streaming | Zustand store + SSE | Per-channel chat stores updated by SSE events |
| Forms | React Hook Form + Zod | Complex bot config form needs validation |
| Icons | lucide-react-native | Tree-shakeable, cross-platform |
| Code editor | CodeMirror (web) / basic TextInput (native) | System prompt and knowledge editing |

### Voice/Audio (Deferred)

Voice features (wake word, local STT, TTS, foreground service, overlay) are explicitly **Phase Future**. The current android-client implementation is preserved as reference but not ported initially. When we get to it, we'll evaluate:
- Web Speech API for browser
- expo-av + expo-speech for native
- Whether Picovoice is still the right choice for local STT/wake word

---

## 4. Project Structure

```
client/                           # Expo universal app
  app/                            # Expo Router pages
    _layout.tsx                   # Root layout (auth gate, providers)
    (auth)/
      login.tsx                   # Server URL + API key entry
    (app)/
      _layout.tsx                 # Three-column shell (responsive)
      index.tsx                   # Redirects to default channel or channel list
      channels/
        index.tsx                 # Channel list (center content)
        [channelId]/
          index.tsx               # Chat view (center content)
          settings.tsx            # Channel settings (center, full-page edit)
      admin/
        bots/
          index.tsx               # Bot list
          [botId]/
            index.tsx             # Bot detail/edit (tabbed)
        knowledge/
          index.tsx               # Knowledge list
          [knowledgeId].tsx       # Knowledge edit
        sessions/
          index.tsx               # Session browser
          [sessionId].tsx         # Session detail with trace
        tasks/
          index.tsx               # Task list
          [taskId].tsx            # Task detail
        tools.tsx                 # Tool browser
        providers.tsx             # Provider config
        sandboxes.tsx             # Sandbox management
        logs/
          index.tsx               # Log list
          [correlationId].tsx     # Trace viewer
        delegations.tsx           # Delegation tree
        memories.tsx              # Memory browser
        skills/
          index.tsx
          [skillId].tsx
  src/
    api/                          # TanStack Query hooks
      client.ts                   # Base API client (auth, base URL)
      hooks/
        useChannels.ts
        useBots.ts
        useSessions.ts
        useChat.ts                # SSE streaming + message mutations
        useKnowledge.ts
        useTasks.ts
        useAdmin.ts               # Stats, tools, providers, sandboxes
    stores/
      auth.ts                     # Server URL, API key (persisted)
      ui.ts                       # Panel state, sidebar collapsed, active entity
      chat.ts                     # Per-channel message stores, streaming state
    components/
      layout/
        AppShell.tsx              # Three-column responsive layout
        Sidebar.tsx               # Left sidebar
        DetailPanel.tsx           # Right detail panel
        CommandPalette.tsx        # Cmd+K search
        Breadcrumbs.tsx
      chat/
        MessageBubble.tsx
        MessageInput.tsx
        StreamingIndicator.tsx
        ToolCallCard.tsx
        TraceOverlay.tsx
      admin/
        BotForm.tsx               # Tabbed bot editor (not a 1350-line scroll)
        EntityLink.tsx            # Clickable entity reference (bot, session, etc.)
        DataTable.tsx             # Reusable sortable/filterable table
        JsonViewer.tsx            # For config/trace data
      shared/
        Button.tsx
        Card.tsx
        Input.tsx
        Modal.tsx
        Tabs.tsx
        Badge.tsx
    hooks/
      useResponsiveColumns.ts     # 1/2/3 column based on viewport
      usePlatform.ts              # Platform-specific behavior
    types/
      api.ts                      # API response types (generated or manual)
    voice/                        # Future: voice pipeline
    native/                       # Future: native bridges
  package.json
  tsconfig.json
  tailwind.config.js
  app.json                        # Expo config
```

---

## 5. Admin JSON API

The current admin routes return HTML. We need JSON equivalents. Strategy: extract query logic from `admin*.py` handlers into service functions, expose as both HTML and JSON endpoints.

### New endpoints under `/api/v1/admin/`

```
# Dashboard
GET  /admin/stats                           → { sessions, memories, knowledge, tools, sandboxes }

# Bots
GET    /admin/bots                          → [BotConfig]
GET    /admin/bots/{id}                     → BotConfig (full)
POST   /admin/bots                          → BotConfig
PUT    /admin/bots/{id}                     → BotConfig
DELETE /admin/bots/{id}                     → 204

# Channels
GET    /admin/channels                      → [Channel]
GET    /admin/channels/{id}                 → Channel (+ linked entities summary)
PUT    /admin/channels/{id}                 → Channel
DELETE /admin/channels/{id}                 → 204
GET    /admin/channels/{id}/sessions        → [Session]
GET    /admin/channels/{id}/knowledge       → [KnowledgeEntry]
GET    /admin/channels/{id}/tasks           → [Task]
GET    /admin/channels/{id}/plans           → [Plan]
GET    /admin/channels/{id}/memories        → [Memory]

# Sessions
GET    /admin/sessions                      → [Session] (paginated, filterable)
GET    /admin/sessions/{id}                 → Session (full messages, paginated)
GET    /admin/sessions/{id}/context         → ContextBreakdown
GET    /admin/sessions/{id}/trace           → [TraceEvent]
GET    /admin/sessions/{id}/correlations    → [Session]
GET    /admin/sessions/{id}/children        → [Session]
POST   /admin/sessions/{id}/summarize       → 204

# Knowledge
GET    /admin/knowledge                     → [KnowledgeEntry] (paginated)
GET    /admin/knowledge/{id}                → KnowledgeEntry (+ history)
POST   /admin/knowledge                     → KnowledgeEntry
PUT    /admin/knowledge/{id}                → KnowledgeEntry
DELETE /admin/knowledge/{id}                → 204
POST   /admin/knowledge/{id}/pin           → 204

# Skills
GET    /admin/skills                        → [Skill]
GET    /admin/skills/{id}                   → Skill
PUT    /admin/skills/{id}                   → Skill

# Memories
GET    /admin/memories                      → [Memory] (searchable, paginated)

# Tasks
GET    /admin/tasks                         → [Task] (filterable by status, bot, channel)
GET    /admin/tasks/{id}                    → Task (+ execution trace)

# Tools
GET    /admin/tools                         → [ToolSchema]

# Providers
GET    /admin/providers                     → [Provider]
PUT    /admin/providers/{id}                → Provider

# Sandboxes
GET    /admin/sandboxes                     → [Sandbox]
POST   /admin/sandboxes                     → Sandbox
POST   /admin/sandboxes/{id}/stop           → 204
DELETE /admin/sandboxes/{id}                → 204
PUT    /admin/sandboxes/{id}/lock           → 204

# Delegations
GET    /admin/delegations                   → [DelegationTree]

# Logs / Traces
GET    /admin/logs                          → [LogEntry] (paginated)
GET    /admin/logs/{correlationId}          → TraceDetail

# Filesystem
GET    /admin/filesystem                    → [FileIndex]
```

### Auth

Phase 1: Same API key as existing endpoints. `Authorization: Bearer {key}`. The admin JSON API uses the same key.

---

## 6. Implementation Phases

### Phase 0 — Skeleton + Chat (Week 1-2)

**Goal**: Expo app running on web with basic chat working end-to-end.

**Backend**:
- [ ] `/api/v1/admin/stats` endpoint (dashboard stats)
- [ ] `/api/v1/admin/channels` list endpoint
- [ ] `/api/v1/admin/bots` list endpoint
- [ ] CORS config for Expo dev server

**Client**:
- [ ] Init Expo project in `client/` with Expo Router, NativeWind, TanStack Query, Zustand
- [ ] Auth screen (server URL + API key entry, stored in Zustand persist)
- [ ] AppShell with responsive three-column layout (sidebar, content, detail panel)
- [ ] Sidebar: channel list from API, grouped by bot
- [ ] Chat view: message display with markdown rendering
- [ ] Chat input: text input with send, SSE streaming display
- [ ] Connection status indicator

**Validation**: Can chat with a bot through Expo Web. Messages stream in real-time.

### Phase 1 — Navigation + Read-Only Admin (Week 3-4)

**Goal**: Full navigation structure, all entities browsable (read-only), contextual detail panel working.

**Backend**:
- [ ] All GET admin endpoints (bots, channels, sessions, knowledge, tasks, tools, providers, sandboxes, logs)
- [ ] Session messages endpoint with pagination
- [ ] Trace/context endpoints

**Client**:
- [ ] Command palette (Cmd+K) with fuzzy search across entities
- [ ] Detail panel: context-sensitive, opens on entity click
- [ ] Channel detail panel: tabs for sessions, knowledge, tasks, plans, settings
- [ ] Session browser with message display and trace viewer
- [ ] Bot detail view (read-only, tabbed by section)
- [ ] Task list and detail with execution trace
- [ ] Knowledge browser
- [ ] Tool browser
- [ ] Log/trace viewer
- [ ] EntityLink component: every entity reference is clickable
- [ ] Breadcrumb navigation
- [ ] Universal recents (all entity types) with pinning

**Validation**: Can browse all admin data without touching the old dashboard. Navigation is contextual — never lose where you were.

### Phase 2 — Admin CRUD + Editing (Week 5-8)

**Goal**: Full admin editing capability, replacing the old dashboard.

**Backend**:
- [ ] All POST/PUT/DELETE admin endpoints
- [ ] Bot create/update/delete
- [ ] Knowledge create/update/delete
- [ ] Skill update
- [ ] Sandbox create/stop/remove/lock
- [ ] Provider update

**Client**:
- [ ] Bot editor: tabbed form (Identity, System Prompt, Tools, Skills, Model, Memory, Knowledge, Delegation, Advanced) — NOT a single scroll
- [ ] Knowledge editor with content editing
- [ ] Skill editor
- [ ] Channel settings editor
- [ ] Provider config editor
- [ ] Sandbox management (create, stop, remove, lock)
- [ ] Session management (delete, summarize, reset)
- [ ] Optimistic updates (TanStack Query mutations)
- [ ] Form validation (Zod schemas)
- [ ] Inline editing in detail panel where appropriate

**Validation**: Full feature parity with old admin dashboard. Every CRUD operation works.

### Phase 3 — Polish + Decommission Old Dashboard (Week 9-10)

**Goal**: Production-ready web client, old dashboard removed.

**Backend**:
- [ ] Serve Expo Web static build from FastAPI (at `/` or `/app/`)
- [ ] Remove Jinja2 templates, admin HTML routes, static CSS
- [ ] Remove Jinja2/HTMX dependencies

**Client**:
- [ ] Keyboard shortcuts (Cmd+K search, Cmd+Enter send, Esc close panel, etc.)
- [ ] Dark/light theme (default dark matching current)
- [ ] Loading states, error boundaries, empty states
- [ ] Responsive testing: desktop (3-col), tablet (2-col), phone (1-col)
- [ ] Performance: virtualized lists for long session/message lists
- [ ] URL-based deep linking (every view has a stable URL)

**Validation**: Old dashboard removed. All admin + chat works on Expo Web.

### Phase Future — Mobile Native Features

When ready:
- [ ] Android build via EAS
- [ ] iOS build via EAS
- [ ] Voice input (evaluate Web Speech API, expo-av, Picovoice alternatives)
- [ ] Wake word detection
- [ ] TTS playback
- [ ] Push notifications
- [ ] Foreground service + overlay (Android)
- [ ] Offline message queue

---

## 7. Key Design Decisions

### 7.1 Why Not Separate Admin and Chat Apps?

They share 80% of the data model and API surface. A channel's chat messages, its bot config, its knowledge entries, its task history — these are all related. Separating them recreates the current problem of bouncing between contexts.

### 7.2 Why Fresh Project Instead of Migrating android-client?

The android-client was built Android-only with no web considerations. The layout (`(tabs)/`) doesn't suit the three-column web layout. The API client (`agent.ts`) uses raw XHR and manual state — we want TanStack Query. Voice modules are cleanly separated and can be copied when needed.

### 7.3 Why Three Columns Instead of Tabs?

Tabs (the old approach) force you to leave one context to enter another. Three columns let you keep the channel list visible while chatting while viewing entity details. The detail panel is the key innovation — it's how "related things are accessible together."

### 7.4 Bot Editor: Tabs Not Scroll

The current 1350-line bot edit form should be a tabbed interface:
- **Identity**: Name, ID, description, display settings
- **System Prompt**: Full editor (CodeMirror on web)
- **Tools**: Local tools, MCP servers, client tools, pinned tools
- **Skills**: Skill selection
- **Model**: Provider, model, elevation config
- **Memory & Knowledge**: Memory settings, knowledge entries, attachments
- **Delegation**: Delegate bots, harness access
- **Advanced**: Compaction, context config, sandbox profiles, host exec, filesystem

Each tab loads independently. You can link directly to a tab: `/admin/bots/{id}?tab=tools`.

### 7.5 Deployment

Static export (`npx expo export --platform web`) → served by FastAPI at root path. API stays at `/api/`, `/chat/`, `/sessions/`. Single port, no CORS in production.

---

## 8. Risks

1. **Admin API surface area**: Many endpoints to build. Mitigated by extracting shared service functions from existing admin HTML handlers.
2. **Trace viewer complexity**: The 21KB trace template is the hardest UI component to port. Plan: build a recursive TraceTree component with expandable nodes.
3. **SSE on web**: POST-based SSE is non-standard. `@microsoft/fetch-event-source` handles it. Test early (Phase 0).
4. **NativeWind on native**: Can be finicky with complex layouts. Web is primary target; native gets progressive enhancement.
